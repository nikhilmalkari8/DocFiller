"""DocFiller – Intelligent Document Filler API."""
import asyncio
import base64
import os
import uuid
from typing import Literal, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from services.excel_parser import parse_excel, get_row_data, get_all_rows
from services.filenames import build_filenames
from services.format_converter import (
    ConversionError,
    ConversionUnavailableError,
    convert_many_to_pdf,
    convert_to_pdf,
    is_conversion_available,
)
from services.pdf_processor import extract_placeholders, fill_pdf
from services.word_processor import extract_merge_fields, fill_word_template, flatten_merge_fields
from services.llm_mapper import map_fields

app = FastAPI(title="DocFiller API", version="1.0.0")

MAX_BULK_ROWS = 200

OutputFormat = Optional[Literal["original", "pdf", "docx"]]

# Serializes all LibreOffice conversions process-wide. There's no auth on
# this API and no per-request concurrency limit elsewhere, so without this a
# few overlapping PDF-conversion requests could run several ~150-300MB
# soffice processes at once on a small container. Costs nothing at this
# project's real traffic (conversions queue instead of running in parallel).
_conversion_semaphore = asyncio.Semaphore(1)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://docfiller-app.vercel.app",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage (for MVP; use Redis/DB in production)
sessions: dict[str, dict] = {}


class MapRequest(BaseModel):
    session_id: str
    excel_columns: list[str]
    placeholders: list[str]
    excel_preview: Optional[list[dict]] = None


class GenerateRequest(BaseModel):
    session_id: str
    mapping: dict[str, str]
    row_index: Optional[int] = 0
    filename_column: Optional[str] = None
    output_format: OutputFormat = None


class GenerateAllRequest(BaseModel):
    session_id: str
    mapping: dict[str, str]
    output_format: OutputFormat = None
    filename_column: Optional[str] = None


@app.get("/api/health")
async def health():
    return {"status": "ok", "pdf_conversion": is_conversion_available()}


@app.post("/api/upload")
async def upload_files(
    excel_file: UploadFile = File(...),
    template_file: UploadFile = File(...),
):
    """
    Upload an Excel file and a PDF template.
    Parses both and returns columns, preview data, and placeholders.
    """
    # Validate file types
    excel_ext = os.path.splitext(excel_file.filename or "")[1].lower()
    template_ext = os.path.splitext(template_file.filename or "")[1].lower()

    if excel_ext not in (".xlsx", ".xls", ".xlsm"):
        raise HTTPException(400, f"Excel file must be .xlsx, .xls, or .xlsm, got {excel_ext}")
    if template_ext not in (".pdf", ".docx", ".docm"):
        raise HTTPException(400, f"Template must be a PDF or Word file (.pdf, .docx, .docm), got {template_ext}")

    # Read file bytes
    excel_bytes = await excel_file.read()
    template_bytes = await template_file.read()

    # Parse Excel
    try:
        excel_data = parse_excel(excel_bytes)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse Excel file: {str(e)}")

    # Extract placeholders/merge fields from template
    is_word = template_ext in (".docx", ".docm")
    try:
        if is_word:
            placeholders = extract_merge_fields(template_bytes)
        else:
            placeholders = extract_placeholders(template_bytes)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse template: {str(e)}")

    if not placeholders:
        if is_word:
            raise HTTPException(
                400,
                "No merge fields found in the Word template. "
                "Make sure the document contains MERGEFIELD fields (e.g., «FieldName»).",
            )
        else:
            raise HTTPException(
                400,
                "No placeholders found in the PDF template. "
                "Make sure placeholders are wrapped with << >> (e.g., <<Applicant Name>>).",
            )

    # Store in session
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "excel_bytes": excel_bytes,
        "template_bytes": template_bytes,
        "excel_data": excel_data,
        "placeholders": placeholders,
        "template_type": "word" if is_word else "pdf",
        "template_ext": template_ext,
    }

    return {
        "session_id": session_id,
        "excel_columns": excel_data["columns"],
        "excel_preview": excel_data["preview"],
        "total_rows": excel_data["total_rows"],
        "placeholders": placeholders,
        "template_type": "word" if is_word else "pdf",
    }


@app.post("/api/map")
async def map_columns(request: MapRequest):
    """
    Use LLM to intelligently map placeholders to Excel columns.
    """
    if request.session_id not in sessions:
        raise HTTPException(404, "Session not found. Please re-upload files.")

    try:
        mapping = map_fields(
            excel_columns=request.excel_columns,
            placeholders=request.placeholders,
            excel_preview=request.excel_preview,
        )
    except Exception as e:
        raise HTTPException(500, f"Mapping failed: {str(e)}")

    return {"mapping": mapping}


def _build_fill_values(mapping: dict[str, str], row_data: dict[str, str]) -> dict[str, str]:
    """Build the values dict: placeholder_name -> actual value from Excel."""
    fill_values = {}
    for placeholder, column in mapping.items():
        if column and column in row_data:
            fill_values[placeholder] = row_data[column]
        else:
            fill_values[placeholder] = ""  # Leave empty if no mapping
    return fill_values


def _fill_document(session: dict, fill_values: dict[str, str]) -> tuple[bytes, str, str]:
    """Fill the template (PDF or Word). Returns (bytes, mime_type, ext)."""
    template_type = session.get("template_type", "pdf")
    template_ext = session.get("template_ext", ".pdf")

    if template_type == "word":
        filled_doc = fill_word_template(session["template_bytes"], fill_values)
        mime_type = (
            "application/vnd.ms-word.document.macroEnabled.12"
            if template_ext == ".docm"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return filled_doc, mime_type, template_ext
    else:
        filled_doc = fill_pdf(session["template_bytes"], fill_values)
        return filled_doc, "application/pdf", ".pdf"


async def _apply_output_format(
    session: dict, filled_doc: bytes, mime_type: str, template_ext: str, output_format: OutputFormat
) -> tuple[bytes, str, str]:
    """
    Resolve the requested output_format against the template's actual type,
    converting Word -> PDF if asked. PDF templates never convert (PDF->Word
    is out of scope by decision — too lossy for real client documents).
    Returns (bytes, mime_type, ext), raising HTTPException for anything that
    can't be satisfied.
    """
    template_type = session.get("template_type", "pdf")
    requested = output_format or "original"

    if template_type == "pdf":
        if requested == "docx":
            raise HTTPException(400, "Converting a PDF template to Word isn't supported.")
        return filled_doc, mime_type, template_ext

    # template_type == "word"
    if requested in ("original", "docx"):
        return filled_doc, mime_type, template_ext

    # requested == "pdf"
    flattened = flatten_merge_fields(filled_doc)
    try:
        async with _conversion_semaphore:
            pdf_bytes = await run_in_threadpool(convert_to_pdf, flattened, template_ext)
    except ConversionUnavailableError:
        raise HTTPException(503, "PDF conversion is unavailable on this server")
    except ConversionError as e:
        raise HTTPException(500, f"Failed to convert document to PDF: {str(e)}")

    return pdf_bytes, "application/pdf", ".pdf"


@app.post("/api/generate")
async def generate_document(request: GenerateRequest):
    """
    Generate a filled PDF using the provided mapping.
    """
    session = sessions.get(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found. Please re-upload files.")

    # Get the row data from Excel
    try:
        row_data = get_row_data(session["excel_bytes"], request.row_index or 0)
    except Exception as e:
        raise HTTPException(400, f"Failed to read row {request.row_index}: {str(e)}")

    fill_values = _build_fill_values(request.mapping, row_data)

    try:
        filled_doc, mime_type, template_ext = _fill_document(session, fill_values)
    except Exception as e:
        raise HTTPException(500, f"Failed to generate document: {str(e)}")

    filled_doc, mime_type, template_ext = await _apply_output_format(
        session, filled_doc, mime_type, template_ext, request.output_format
    )

    if request.filename_column:
        filename = build_filenames([row_data], request.filename_column, template_ext)[0]
    else:
        filename = f"filled_document{template_ext}"

    return Response(
        content=filled_doc,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.post("/api/generate-all")
async def generate_all_documents(request: GenerateAllRequest):
    """
    Generate a filled document for every row in the Excel sheet.
    Returns all documents inline as base64 — nothing is retained server-side.
    """
    session = sessions.get(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found. Please re-upload files.")

    template_type = session.get("template_type", "pdf")
    template_ext = session.get("template_ext", ".pdf")
    requested_format = request.output_format or "original"
    converting_to_pdf = template_type == "word" and requested_format == "pdf"

    if template_type == "pdf" and requested_format == "docx":
        raise HTTPException(400, "Converting a PDF template to Word isn't supported.")

    # Fail fast, before filling a single row, if conversion was requested but
    # isn't available — cheaper than filling N rows only to discover that.
    if converting_to_pdf and not is_conversion_available():
        raise HTTPException(503, "PDF conversion is unavailable on this server")

    try:
        rows = get_all_rows(session["excel_bytes"])
    except Exception as e:
        raise HTTPException(400, f"Failed to read Excel rows: {str(e)}")

    if len(rows) > MAX_BULK_ROWS:
        raise HTTPException(
            400,
            f"Too many rows ({len(rows)}). Bulk generation is limited to {MAX_BULK_ROWS} rows per request.",
        )

    output_ext = ".pdf" if converting_to_pdf else template_ext
    try:
        filenames = build_filenames(rows, request.filename_column, output_ext)
    except Exception as e:
        raise HTTPException(400, f"Failed to derive document filenames: {str(e)}")

    results = []
    success_count = 0
    error_count = 0
    skipped_count = 0

    for i, row_data in enumerate(rows):
        fill_values = _build_fill_values(request.mapping, row_data)
        label = row_data.get(request.filename_column) if request.filename_column else None

        if not any(fill_values.values()):
            skipped_count += 1
            results.append(
                {
                    "row_index": i,
                    "status": "skipped",
                    "label": label,
                    "filename": None,
                    "mime_type": None,
                    "content_base64": None,
                    "error": "Row has no data for any mapped column",
                }
            )
            continue

        try:
            filled_doc, mime_type, _ = _fill_document(session, fill_values)
            results.append(
                {
                    "row_index": i,
                    "status": "ok",
                    "label": label,
                    "filename": filenames[i],
                    "mime_type": mime_type,
                    "content_base64": base64.b64encode(filled_doc).decode(),
                    "error": None,
                    "_raw_bytes": filled_doc,  # dropped before the response is returned
                }
            )
            success_count += 1
        except Exception as e:
            error_count += 1
            results.append(
                {
                    "row_index": i,
                    "status": "error",
                    "label": label,
                    "filename": None,
                    "mime_type": None,
                    "content_base64": None,
                    "error": f"Failed to fill template: {str(e)}",
                }
            )

    if converting_to_pdf:
        ok_indices = [i for i, r in enumerate(results) if r["status"] == "ok"]
        if ok_indices:
            flattened_docs = [flatten_merge_fields(results[i]["_raw_bytes"]) for i in ok_indices]
            try:
                async with _conversion_semaphore:
                    pdf_results = await run_in_threadpool(
                        convert_many_to_pdf, flattened_docs, template_ext
                    )
            except ConversionUnavailableError:
                raise HTTPException(503, "PDF conversion is unavailable on this server")
            except ConversionError as e:
                raise HTTPException(500, f"Failed to convert documents to PDF: {str(e)}")

            for idx, pdf_bytes in zip(ok_indices, pdf_results):
                if pdf_bytes is None:
                    success_count -= 1
                    error_count += 1
                    results[idx]["status"] = "error"
                    results[idx]["filename"] = None
                    results[idx]["mime_type"] = None
                    results[idx]["content_base64"] = None
                    results[idx]["error"] = "Failed to convert document to PDF"
                else:
                    results[idx]["mime_type"] = "application/pdf"
                    results[idx]["content_base64"] = base64.b64encode(pdf_bytes).decode()

    for r in results:
        r.pop("_raw_bytes", None)

    return {
        "total_rows": len(rows),
        "success_count": success_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "results": results,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
