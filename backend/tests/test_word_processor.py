import io
import zipfile

from services.word_processor import (
    UnsupportedCharacterError,
    extract_merge_fields,
    fill_word_template,
    flatten_merge_fields,
)
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


# --- XML escaping of filled values (TICKET-006) ---
# fill_word_template used to splice values into document.xml raw, so a value like
# "Smith & Sons LLC" produced malformed XML — a 200 response carrying a corrupt .docx.

import xml.etree.ElementTree as ET

import pytest

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _document_xml(docx_bytes):
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _wt_text(docx_bytes):
    """Text of every <w:t>; raises ParseError if document.xml isn't well-formed."""
    root = ET.fromstring(_document_xml(docx_bytes).encode("utf-8"))
    return "".join(t.text or "" for t in root.iter(f"{_W}t"))


@pytest.mark.parametrize(
    "value",
    [
        "Smith & Sons LLC",
        "a < b",
        "a > b",
        "AT&amp;T",                                   # literal text must stay literal
        "O'Brien \"Q\"",
        "</w:t></w:r><w:r><w:t>injected",             # can't break out of the text node
    ],
)
def test_filled_value_round_trips_exactly_through_well_formed_xml(value):
    filled = fill_word_template(make_valid_docx_bytes(["Name"]), {"Name": value})
    assert _wt_text(filled) == value


def test_two_fields_with_special_characters_keep_the_whole_document_intact():
    docx = make_valid_docx_bytes(["Name", "Date"])
    filled = fill_word_template(docx, {"Name": "Smith & Sons LLC", "Date": "2024-01-15"})
    assert _wt_text(filled) == "Smith & Sons LLC2024-01-15"


@pytest.mark.parametrize("value", ["John Doe", "2024-01-15", "", "  pad  ", "l1\nl2", "Ünïcødé €", "50,000.00"])
def test_values_without_special_characters_leave_document_xml_exactly_as_before(value):
    """Characterization: escaping must not change a single byte for ordinary values."""
    docx = make_valid_docx_bytes(["Name"])
    filled = fill_word_template(docx, {"Name": value})
    expected = _document_xml(docx).replace("«Name»", value)
    assert _document_xml(filled) == expected
    with zipfile.ZipFile(io.BytesIO(docx)) as zin, zipfile.ZipFile(io.BytesIO(filled)) as zout:
        assert zin.namelist() == zout.namelist()
        for name in zin.namelist():
            if name != "word/document.xml":
                assert zin.read(name) == zout.read(name)


def test_field_name_with_an_ampersand_is_still_matched_not_double_encoded():
    """Field names come out of extract_merge_fields as raw XML ('A&amp;B'); the
    search key must not be escaped or that field would silently stop filling."""
    docx = make_valid_docx_bytes(["A&amp;B"])
    [name] = extract_merge_fields(docx)
    assert name == "A&amp;B"
    filled = fill_word_template(docx, {name: "X & Y"})
    assert "«" not in _document_xml(filled)
    assert _wt_text(filled) == "X & Y"


def test_flatten_after_fill_survives_special_characters():
    docx = make_valid_docx_bytes(["Name"])
    for value in ["Smith & Sons LLC", "</w:r>MERGEFIELD"]:
        flattened = flatten_merge_fields(fill_word_template(docx, {"Name": value}))
        assert _wt_text(flattened) == value
        xml = _document_xml(flattened)
        assert "fldChar" not in xml and "instrText" not in xml


@pytest.mark.parametrize(
    "value",
    [
        "bad\x0bvalue", "nul\x00", "esc\x1b[0m", "x\ufffey",
        # range boundaries, so shrinking the character class can't go unnoticed
        "a\x08b", "a\x0cb", "a\x0eb", "a\x1fb", "a\uffffb",
        # lone surrogates aren't XML chars; they used to surface as a 500
        "lone\ud800surrogate", "lone\udfffsurrogate",
    ],
)
def test_characters_illegal_in_xml_fail_clearly_naming_the_field_not_the_value(value):
    """Q1: XML 1.0 can't represent these at all. Failing is safer than silently
    stripping characters out of a legal document."""
    with pytest.raises(UnsupportedCharacterError) as exc:
        fill_word_template(make_valid_docx_bytes(["Name"]), {"Name": value})
    assert "Name" in str(exc.value)
    assert value not in str(exc.value)


def test_tab_and_newline_and_carriage_return_are_still_allowed():
    filled = fill_word_template(make_valid_docx_bytes(["Name"]), {"Name": "a\tb\nc\rd"})
    ET.fromstring(_document_xml(filled).encode("utf-8"))  # parses


@pytest.mark.parametrize(
    "value",
    ["a\x7fb", "a\x85b", "a\u2028b", "a\ufffdb", "a\U0001f600b", "a\U0001fffeb", "a\U0010ffffb"],
)
def test_legal_but_unusual_characters_are_accepted_and_round_trip(value):
    """Counterpart to the illegal-character tests: don't over-reject."""
    filled = fill_word_template(make_valid_docx_bytes(["Name"]), {"Name": value})
    assert _wt_text(filled) == value
