"""DocFiller – Intelligent Document Filler API."""
import os
import uuid
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from services.excel_parser import parse_excel, get_row_data
from services.pdf_processor import extract_placeholders, fill_pdf
from services.word_processor import extract_merge_fields, fill_word_template
from services.llm_mapper import map_fields

app = FastAPI(title="DocFiller API", version="1.0.0")

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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


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

    # Build the values dict: placeholder_name -> actual value from Excel
    fill_values = {}
    for placeholder, column in request.mapping.items():
        if column and column in row_data:
            fill_values[placeholder] = row_data[column]
        else:
            fill_values[placeholder] = ""  # Leave empty if no mapping

    # Fill the template (PDF or Word)
    template_type = session.get("template_type", "pdf")
    template_ext = session.get("template_ext", ".pdf")

    try:
        if template_type == "word":
            filled_doc = fill_word_template(session["template_bytes"], fill_values)
            mime_type = (
                "application/vnd.ms-word.document.macroEnabled.12"
                if template_ext == ".docm"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            filename = f"filled_document{template_ext}"
        else:
            filled_doc = fill_pdf(session["template_bytes"], fill_values)
            mime_type = "application/pdf"
            filename = "filled_document.pdf"
    except Exception as e:
        raise HTTPException(500, f"Failed to generate document: {str(e)}")

    return Response(
        content=filled_doc,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
