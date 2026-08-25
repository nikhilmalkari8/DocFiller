import io
import zipfile

from services.word_processor import extract_merge_fields, fill_word_template, flatten_merge_fields
from tests.conftest import make_docx_bytes, make_valid_docx_bytes


def test_extract_merge_fields_finds_fields_preserving_first_seen_order():
    docx = make_docx_bytes(["Name", "Date", "Amount"])
    assert extract_merge_fields(docx) == ["Name", "Date", "Amount"]


def test_extract_merge_fields_dedupes_repeated_field():
    docx = make_docx_bytes(["Name", "Date", "Name"])
    assert extract_merge_fields(docx) == ["Name", "Date"]


def test_extract_merge_fields_returns_empty_list_when_none_present():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>No fields here.</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    assert extract_merge_fields(buf.getvalue()) == []


def test_fill_word_template_replaces_display_text_with_value():
    docx = make_docx_bytes(["Name", "Date"])

    filled = fill_word_template(docx, {"Name": "John Doe", "Date": "2024-01-15"})

    with zipfile.ZipFile(io.BytesIO(filled)) as z:
        content = z.read("word/document.xml").decode("utf-8")

    assert "John Doe" in content
    assert "2024-01-15" in content
    assert "«Name»" not in content
    assert "«Date»" not in content


def test_fill_word_template_handles_none_value_as_empty_string():
    docx = make_docx_bytes(["Name"])

    filled = fill_word_template(docx, {"Name": None})

    with zipfile.ZipFile(io.BytesIO(filled)) as z:
        content = z.read("word/document.xml").decode("utf-8")
    assert "«Name»" not in content


def test_fill_word_template_preserves_other_files_in_the_zip():
    docx = make_docx_bytes(["Name"])
    filled = fill_word_template(docx, {"Name": "John Doe"})

    with zipfile.ZipFile(io.BytesIO(filled)) as z:
        assert z.namelist() == ["word/document.xml"]


def test_make_valid_docx_bytes_is_a_real_openable_package():
    docx = make_valid_docx_bytes(["Name"])
    assert extract_merge_fields(docx) == ["Name"]
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        names = z.namelist()
        assert "[Content_Types].xml" in names
        assert "_rels/.rels" in names
        assert "word/document.xml" in names


# --- flatten_merge_fields ---


def test_flatten_merge_fields_strips_field_structure_keeps_filled_value():
    docx = make_valid_docx_bytes(["Name", "Date"])
    filled = fill_word_template(docx, {"Name": "John Doe", "Date": "2024-01-15"})

    flattened = flatten_merge_fields(filled)

    with zipfile.ZipFile(io.BytesIO(flattened)) as z:
        content = z.read("word/document.xml").decode("utf-8")

    assert "John Doe" in content
    assert "2024-01-15" in content
    assert "MERGEFIELD" not in content
    assert "fldChar" not in content
    assert "instrText" not in content


def test_flatten_merge_fields_preserves_other_zip_parts_byte_identical():
    docx = make_valid_docx_bytes(["Name"])
    filled = fill_word_template(docx, {"Name": "John Doe"})

    with zipfile.ZipFile(io.BytesIO(filled)) as z:
        original_content_types = z.read("[Content_Types].xml")
        original_rels = z.read("_rels/.rels")

    flattened = flatten_merge_fields(filled)

    with zipfile.ZipFile(io.BytesIO(flattened)) as z:
        assert z.read("[Content_Types].xml") == original_content_types
        assert z.read("_rels/.rels") == original_rels


def test_flatten_merge_fields_passes_through_doc_with_no_merge_fields_unchanged():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>No fields here.</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    no_fields_doc = buf.getvalue()

    flattened = flatten_merge_fields(no_fields_doc)

    with zipfile.ZipFile(io.BytesIO(flattened)) as z:
        content = z.read("word/document.xml").decode("utf-8")
    assert "No fields here." in content
