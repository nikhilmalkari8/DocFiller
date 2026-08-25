"""DOCX -> PDF conversion via headless LibreOffice.

Pure sync, bytes-in/bytes-out — no asyncio or FastAPI knowledge, so callers
control how this runs off the event loop, and swapping the subprocess call
for an HTTP call to a sidecar service (e.g. Gotenberg) later is a one-file
change.
"""
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Optional


class ConversionError(Exception):
    """Conversion ran but failed (non-zero exit, no output produced)."""


class ConversionUnavailableError(Exception):
    """The soffice binary isn't installed on this server."""


def is_conversion_available() -> bool:
    return shutil.which("soffice") is not None


def convert_many_to_pdf(
    docs: list[bytes], source_ext: str, timeout: int = 120
) -> list[Optional[bytes]]:
    """
    Convert a batch of documents to PDF in one soffice invocation (each
    document's process-startup cost is paid once for the whole batch, not
    once per document). Returns results positionally aligned to `docs`;
    `None` for any document that failed to convert.

    Any document whose output is missing after the batch run is retried
    individually, so one bad document can't take the whole batch down with
    it — the batch invocation is a performance optimization, not something
    that should compromise per-document failure isolation.
    """
    if not is_conversion_available():
        raise ConversionUnavailableError(
            "soffice (LibreOffice) is not installed on this server"
        )

    results = _run_batch(docs, source_ext, timeout)

    for i, result in enumerate(results):
        if result is None:
            retried = _run_batch([docs[i]], source_ext, timeout)
            results[i] = retried[0]

    return results


def convert_to_pdf(doc_bytes: bytes, source_ext: str = ".docx", timeout: int = 120) -> bytes:
    result = convert_many_to_pdf([doc_bytes], source_ext, timeout)[0]
    if result is None:
        raise ConversionError("Failed to convert document to PDF")
    return result


def _run_batch(docs: list[bytes], source_ext: str, timeout: int) -> list[Optional[bytes]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        # A unique profile dir per invocation — concurrent soffice runs
        # sharing a profile directory deadlock against each other.
        profile_dir = os.path.join(tmpdir, f"profile-{uuid.uuid4().hex}")
        outdir = os.path.join(tmpdir, "out")
        os.makedirs(outdir, exist_ok=True)

        input_paths = []
        for i, doc_bytes in enumerate(docs):
            # Keep the source extension so soffice picks the right import
            # filter (a .docm needs to be recognized as macro-enabled Word,
            # not treated as a generic .docx).
            input_path = os.path.join(tmpdir, f"input-{i}{source_ext}")
            with open(input_path, "wb") as f:
                f.write(doc_bytes)
            input_paths.append(input_path)

        cmd = [
            "soffice",
            "--headless",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            outdir,
            *input_paths,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            # A hung/pathological document must not take the rest of the
            # batch down with it — treat as "no outputs produced" so the
            # caller's per-file retry logic kicks in for every input here.
            return [None] * len(input_paths)

        results: list[Optional[bytes]] = []
        for input_path in input_paths:
            base = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(outdir, f"{base}.pdf")
            if os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    results.append(f.read())
            else:
                results.append(None)

        if proc.returncode != 0 and all(r is None for r in results):
            stderr = proc.stderr.decode(errors="replace") if proc.stderr else ""
            raise ConversionError(f"soffice conversion failed: {stderr}")

        return results
