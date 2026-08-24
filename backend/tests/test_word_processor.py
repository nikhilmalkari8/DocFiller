import io
import zipfile

from services.word_processor import extract_merge_fields, fill_word_template
from tests.conftest import make_docx_bytes


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
