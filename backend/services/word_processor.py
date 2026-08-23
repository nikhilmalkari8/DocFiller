"""Word document (.docx/.docm) mail merge processor."""
import io
import re
import zipfile


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
        safe_value = str(value) if value is not None else ""
        doc_xml = doc_xml.replace(f"\u00ab{field_name}\u00bb", safe_value)

    file_map["word/document.xml"] = doc_xml.encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z_out:
        for name, data in file_map.items():
            z_out.writestr(name, data)

    return output.getvalue()
