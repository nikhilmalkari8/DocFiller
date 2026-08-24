import pymupdf

from services.pdf_processor import extract_placeholders, fill_pdf
from tests.conftest import make_pdf_bytes


def test_extract_placeholders_finds_and_dedupes():
    pdf = make_pdf_bytes(["Name", "Date", "Name"])
    assert extract_placeholders(pdf) == ["Date", "Name"]


def test_extract_placeholders_returns_empty_list_when_none_present():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello World, no placeholders here.")
    buf = doc.write()
    doc.close()

    assert extract_placeholders(buf) == []


def test_fill_pdf_replaces_placeholder_with_value_and_removes_markup():
    pdf = make_pdf_bytes(["Name", "Date"])

    filled = fill_pdf(pdf, {"Name": "John Doe", "Date": "2024-01-15"})

    assert extract_placeholders(filled) == []

    doc = pymupdf.open(stream=filled, filetype="pdf")
    text = "".join(page.get_text("text") for page in doc)
    doc.close()
    assert "John Doe" in text
    assert "2024-01-15" in text
    assert "<<Name>>" not in text
    assert "<<Date>>" not in text


def test_fill_pdf_leaves_unmapped_placeholder_text_untouched():
    pdf = make_pdf_bytes(["Name", "Date"])

    # Only "Name" is in the mapping; "Date" isn't touched by fill_pdf at all
    # (main.py is responsible for supplying "" for unmapped placeholders).
    filled = fill_pdf(pdf, {"Name": "John Doe"})

    assert extract_placeholders(filled) == ["Date"]
