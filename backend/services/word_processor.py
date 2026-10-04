"""Word document (.docx/.docm) mail merge processor."""
import io
import re
import zipfile
from xml.sax.saxutils import escape

class UnsupportedCharacterError(ValueError):
    """A value contains a character XML 1.0 cannot represent."""


# XML 1.0 forbids these outright (everything below 0x20 except tab/newline/CR,
# lone surrogates, and U+FFFE/U+FFFF); no escaping can make them legal. Failing is safer than
# silently deleting characters from a legal document.
_XML_ILLEGAL_CHARS = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\ud800-\\udfff\\ufffe\\uffff]")


# One <w:r>...</w:r> run element containing a specific structural marker —
# used to strip the four structural runs of a MERGEFIELD field code
# (begin/instrText/separate/end) while leaving the result run (the run
# containing the actual filled text) untouched. Each pattern is scoped to a
# single run via a non-greedy body that stops at the first </w:r>.
_STRUCTURAL_RUN_PATTERNS = [
    re.compile(r'<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:fldChar\s+w:fldCharType="begin"\s*/>(?:(?!</w:r>).)*?</w:r>', re.DOTALL),
    re.compile(r"<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:instrText\b(?:(?!</w:r>).)*?</w:r>", re.DOTALL),
    re.compile(r'<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:fldChar\s+w:fldCharType="separate"\s*/>(?:(?!</w:r>).)*?</w:r>', re.DOTALL),
    re.compile(r'<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:fldChar\s+w:fldCharType="end"\s*/>(?:(?!</w:r>).)*?</w:r>', re.DOTALL),
]


def extract_merge_fields(doc_bytes: bytes) -> list[str]:
    """
    Extract MERGEFIELD names from a Word document (.docx or .docm).
    Returns a deduplicated list preserving order of first appearance.
    """
    with zipfile.ZipFile(io.BytesIO(doc_bytes)) as z:
        with z.open("word/document.xml") as f:
            content = f.read().decode("utf-8")

    fields = re.findall(r"MERGEFIELD\s+(\S+)", content)
    return list(dict.fromkeys(fields))


def fill_word_template(doc_bytes: bytes, fill_values: dict[str, str]) -> bytes:
    """
    Fill Word mail merge fields with provided values.

    Replaces the «FieldName» display text inside each mail merge field
    with the corresponding value from fill_values.

    Returns the filled document as bytes (preserves original format,
    including macros for .docm files).
    """
    with zipfile.ZipFile(io.BytesIO(doc_bytes)) as z_in:
        file_map = {name: z_in.read(name) for name in z_in.namelist()}

    doc_xml = file_map["word/document.xml"].decode("utf-8")

    for field_name, value in fill_values.items():
        text = str(value) if value is not None else ""
        if _XML_ILLEGAL_CHARS.search(text):
            raise UnsupportedCharacterError(
                f"Value for '{field_name}' contains a character that can't be stored in a Word document"
            )
        # Escape the *value* (&, <, >) so it can't corrupt document.xml. Never the
        # search key: field names come out of the raw XML already entity-encoded.
        doc_xml = doc_xml.replace(f"\u00ab{field_name}\u00bb", escape(text))

    file_map["word/document.xml"] = doc_xml.encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z_out:
        for name, data in file_map.items():
            z_out.writestr(name, data)

    return output.getvalue()


def flatten_merge_fields(doc_bytes: bytes) -> bytes:
    """
    Strip MERGEFIELD field-code structure (fldChar begin/separate/end,
    instrText), leaving only the literal filled text behind.

    fill_word_template only replaces the *display* text inside each field —
    Word renders the cached result, so the underlying field code is still
    intact and a MERGEFIELD-aware consumer (LibreOffice included) may
    re-render the field from its instruction instead of the cached display
    text, which would silently produce an unfilled document. This must run
    only on the conversion path, never on the Word download path, since it
    changes the document's XML structure (the DOCX download must keep
    today's exact bytes and behavior).
    """
    with zipfile.ZipFile(io.BytesIO(doc_bytes)) as z_in:
        file_map = {name: z_in.read(name) for name in z_in.namelist()}

    doc_xml = file_map["word/document.xml"].decode("utf-8")

    for pattern in _STRUCTURAL_RUN_PATTERNS:
        doc_xml = pattern.sub("", doc_xml)

    file_map["word/document.xml"] = doc_xml.encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z_out:
        for name, data in file_map.items():
            z_out.writestr(name, data)

    return output.getvalue()
