"""Tests for services/transforms.py — the pure transformation engine (TICKET-005)."""
import inspect
from decimal import Decimal

import pytest

from services import transforms
from services.transforms import (
    CATALOG,
    TransformError,
    TransformSpecError,
    apply_transform,
    normalise_column_case,
    parse_money,
    validate_spec,
)

COLUMNS = ["Name", "Amount"]


# --- registry & spec validation ---

def test_catalog_contains_exactly_the_v1_transforms():
    assert set(CATALOG) == {"copy", "amount_in_words", "currency", "date_format", "join"}


def test_spec_error_is_a_transform_error():
    assert issubclass(TransformSpecError, TransformError)


def test_unknown_type_is_a_spec_error():
    with pytest.raises(TransformSpecError):
        validate_spec({"type": "percent", "source": "Amount"}, COLUMNS)


@pytest.mark.parametrize("bad", [None, "copy", 5, ["copy"], {}, {"source": "Name"}])
def test_non_dict_or_typeless_spec_is_a_spec_error(bad):
    with pytest.raises(TransformSpecError):
        validate_spec(bad, COLUMNS)


def test_missing_required_param_is_a_spec_error():
    with pytest.raises(TransformSpecError):
        validate_spec({"type": "copy"}, COLUMNS)


def test_unexpected_extra_key_is_a_spec_error():
    with pytest.raises(TransformSpecError):
        validate_spec({"type": "copy", "source": "Name", "bogus": 1}, COLUMNS)


def test_source_not_in_columns_is_a_spec_error():
    with pytest.raises(TransformSpecError):
        validate_spec({"type": "copy", "source": "Nope"}, COLUMNS)


def test_valid_spec_passes_validation():
    validate_spec({"type": "copy", "source": "Name"}, COLUMNS)


def test_apply_transform_rejects_a_bad_spec_with_spec_error():
    with pytest.raises(TransformSpecError):
        apply_transform({"type": "nope"}, {"Name": "x"})


# --- copy ---

def test_copy_returns_the_cell_value():
    assert apply_transform({"type": "copy", "source": "Name"}, {"Name": "John Doe"}) == "John Doe"


def test_copy_blank_cell_is_empty_string():
    assert apply_transform({"type": "copy", "source": "Name"}, {"Name": ""}) == ""


def test_copy_missing_column_is_empty_string_like_a_plain_mapping():
    """D9: out-of-range rows give {} — copy stays lenient, matching today's behaviour."""
    assert apply_transform({"type": "copy", "source": "Name"}, {}) == ""


def test_referenced_columns_for_copy():
    assert CATALOG["copy"].referenced_columns({"type": "copy", "source": "Name"}) == {"Name"}


# --- money parsing ---

@pytest.mark.parametrize("raw", ["1200000", "1200000.0", "$1,200,000", "$1,200,000.00", " 1200000 "])
def test_parse_money_accepts_common_shapes_as_decimal(raw):
    value = parse_money(raw)
    assert isinstance(value, Decimal)
    assert value == Decimal("1200000")


def test_parse_money_keeps_cents():
    assert parse_money("1234.56") == Decimal("1234.56")
    assert parse_money("1234.500") == Decimal("1234.50")


@pytest.mark.parametrize(
    "raw",
    [
        "", "   ", "abc", "$", "-5", "(1,200)", "1,20,0000",
        "1234.567", "1234.5600000000001",   # float artifacts are errors, never rounded
        "1e+16",
        "1000000000000000",                 # one quadrillion
    ],
)
def test_parse_money_rejects_bad_input(raw):
    with pytest.raises(TransformError):
        parse_money(raw)


def test_transforms_module_never_uses_float():
    assert "float(" not in inspect.getsource(transforms)


# --- amount_in_words ---

def words(raw):
    return apply_transform({"type": "amount_in_words", "source": "Amount"}, {"Amount": raw})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0", "zero and 00/100 dollars"),
        ("0.5", "zero and 50/100 dollars"),
        ("1", "one and 00/100 dollars"),  # D8: always plural, bank-check convention
        ("21", "twenty-one and 00/100 dollars"),
        ("99", "ninety-nine and 00/100 dollars"),
        ("100", "one hundred and 00/100 dollars"),
        ("101", "one hundred one and 00/100 dollars"),  # no British "and"
        ("110", "one hundred ten and 00/100 dollars"),
        ("1000", "one thousand and 00/100 dollars"),
        ("1001", "one thousand one and 00/100 dollars"),
        ("1234.56", "one thousand two hundred thirty-four and 56/100 dollars"),
        ("1000000", "one million and 00/100 dollars"),
        ("1000001", "one million one and 00/100 dollars"),
        ("1200000", "one million two hundred thousand and 00/100 dollars"),
        ("$1,200,000", "one million two hundred thousand and 00/100 dollars"),
        ("1200000.0", "one million two hundred thousand and 00/100 dollars"),
        ("1000000000", "one billion and 00/100 dollars"),
        (
            "999999999999999.99",
            "nine hundred ninety-nine trillion nine hundred ninety-nine billion "
            "nine hundred ninety-nine million nine hundred ninety-nine thousand "
            "nine hundred ninety-nine and 99/100 dollars",
        ),
    ],
)
def test_amount_in_words(raw, expected):
    assert words(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "-1"])
def test_amount_in_words_rejects_bad_data(raw):
    with pytest.raises(TransformError):
        words(raw)


def test_amount_in_words_output_is_lowercase_without_commas():
    out = words("1234567.89")
    assert out == out.lower()
    assert "," not in out


# --- currency ---

def currency(raw):
    return apply_transform({"type": "currency", "source": "Amount"}, {"Amount": raw})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1200000", "$1,200,000.00"),
        ("1234.5", "$1,234.50"),
        ("0", "$0.00"),
        ("$1,200,000", "$1,200,000.00"),
    ],
)
def test_currency(raw, expected):
    assert currency(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "-5"])
def test_currency_rejects_bad_data(raw):
    with pytest.raises(TransformError):
        currency(raw)


# --- date_format (D3: ISO input only; D4: whitelisted pattern directives) ---

def fmt_date(raw, pattern):
    spec = {"type": "date_format", "source": "Date", "format": pattern}
    return apply_transform(spec, {"Date": raw})


@pytest.mark.parametrize(
    "raw, pattern, expected",
    [
        ("2024-01-15 00:00:00", "%B %-d, %Y", "January 15, 2024"),
        ("2024-01-15", "%B %-d, %Y", "January 15, 2024"),
        ("2024-01-05", "%B %-d, %Y", "January 5, 2024"),
        ("2024-01-05", "%m/%d/%Y", "01/05/2024"),
        ("2024-01-05", "%-m/%-d/%y", "1/5/24"),
        ("2024-01-05", "%b %d %Y", "Jan 05 2024"),
        ("2024-12-31", "%d of %B", "31 of December"),
    ],
)
def test_date_format(raw, pattern, expected):
    assert fmt_date(raw, pattern) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "01/15/2024", "Jan 15, 2024", "2024-02-30", "2024-01-15 13:45:00", "03/04/2024"],
)
def test_date_format_rejects_non_iso_or_invalid_dates(raw):
    with pytest.raises(TransformError):
        fmt_date(raw, "%Y")


@pytest.mark.parametrize("pattern", ["%H", "%A", "%c", "%%", "%Q", "%", ""])
def test_date_format_rejects_unsupported_patterns_as_spec_errors(pattern):
    spec = {"type": "date_format", "source": "Date", "format": pattern}
    with pytest.raises(TransformSpecError):
        validate_spec(spec, ["Date"])


def test_date_format_requires_a_format():
    with pytest.raises(TransformSpecError):
        validate_spec({"type": "date_format", "source": "Date"}, ["Date"])


def test_date_format_month_names_do_not_depend_on_the_locale():
    """Month names come from a fixed English table, not the C library's strftime."""
    assert ".strftime(" not in inspect.getsource(transforms)


# --- join (D5: template-only, exact column names, blanks dropped) ---

JOIN_COLUMNS = ["First", "Middle", "Last", "First Name", "Last Name", "City", "State"]


def join(template, row):
    return apply_transform({"type": "join", "template": template}, row)


def test_join_combines_columns():
    assert join("{First} {Last}", {"First": "John", "Last": "Doe"}) == "John Doe"


def test_join_supports_column_names_with_spaces():
    row = {"First Name": "John", "Last Name": "Doe"}
    assert join("{First Name} {Last Name}", row) == "John Doe"


def test_join_literal_braces():
    assert join("{{ref}} {First}", {"First": "John"}) == "{ref} John"


def test_join_blank_piece_is_dropped_and_spaces_collapsed():
    row = {"First": "John", "Middle": "", "Last": "Doe"}
    assert join("{First} {Middle} {Last}", row) == "John Doe"


def test_join_all_blank_is_empty_string():
    assert join("{First} {Last}", {"First": "", "Last": ""}) == ""


def test_join_known_limitation_dangling_separator():
    """Documented v1 limitation: separators around a blank piece are kept."""
    assert join("{City}, {State}", {"City": "", "State": "NY"}) == ", NY"


def test_join_referenced_columns_are_the_template_tokens():
    spec = {"type": "join", "template": "{{x}} {First} {Last} {First}"}
    assert CATALOG["join"].referenced_columns(spec) == {"First", "Last"}


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "join", "template": "{Nope}"},                  # unknown column
        {"type": "join", "template": "{First"},                  # unbalanced
        {"type": "join", "template": "First}"},                  # unbalanced
        {"type": "join", "template": ""},                        # empty
        {"type": "join", "template": 5},                         # wrong type
        {"type": "join", "template": "{First}", "source": "First"},  # extra param
        {"type": "join"},                                        # missing template
    ],
)
def test_join_bad_specs_are_spec_errors(spec):
    with pytest.raises(TransformSpecError):
        validate_spec(spec, JOIN_COLUMNS)


# --- normalise_column_case (used to tidy LLM-proposed specs) ---

def test_normalise_column_case_fixes_source_without_mutating_input():
    spec = {"type": "copy", "source": "name"}
    assert normalise_column_case(spec, ["Name"]) == {"type": "copy", "source": "Name"}
    assert spec == {"type": "copy", "source": "name"}


def test_normalise_column_case_fixes_join_tokens_and_keeps_literal_braces():
    spec = {"type": "join", "template": "{{x}} {first} {LAST}"}
    got = normalise_column_case(spec, ["First", "Last"])
    assert got == {"type": "join", "template": "{{x}} {First} {Last}"}


def test_normalise_column_case_leaves_unknown_columns_for_validation_to_reject():
    spec = {"type": "copy", "source": "Nope"}
    assert normalise_column_case(spec, ["Name"]) == spec


def test_every_catalog_entry_has_an_llm_facing_description_and_example():
    """The mapper prompt is generated from CATALOG, so an entry without these
    can't be offered to the LLM sensibly."""
    for name, transform in CATALOG.items():
        assert transform.description.strip(), name
        assert transform.example["type"] == name


# --- QA review fixes (TICKET-005) ---

@pytest.mark.parametrize("bad_source", [["Amount"], {"a": 1}, 5, None])
def test_non_string_source_is_a_spec_error_not_a_crash(bad_source):
    spec = {"type": "copy", "source": bad_source}
    with pytest.raises(TransformSpecError):
        validate_spec(spec, COLUMNS)
    with pytest.raises(TransformSpecError):
        apply_transform(spec, {"Amount": "1"})


@pytest.mark.parametrize("raw", ["１２３", "١٢٣", "१२३"])  # fullwidth, Arabic-Indic, Devanagari
def test_money_rejects_non_ascii_digits(raw):
    with pytest.raises(TransformError):
        parse_money(raw)


@pytest.mark.parametrize("raw", ["٢٠٢٤-٠١-١٥", "２０２４-０１-１５"])
def test_dates_reject_non_ascii_digits(raw):
    with pytest.raises(TransformError):
        fmt_date(raw, "%Y")


# --- error messages must not echo long cell contents back (QA finding 3) ---

LONG_VALUE = "SSN 123-45-6789 " * 20


@pytest.mark.parametrize(
    "call",
    [
        lambda v: parse_money(v),
        lambda v: fmt_date(v, "%Y"),
        lambda v: words(v),
    ],
)
def test_error_messages_truncate_the_echoed_cell_value(call):
    with pytest.raises(TransformError) as exc:
        call(LONG_VALUE)
    message = str(exc.value)
    assert len(message) < 120
    assert "…" in message
    assert LONG_VALUE not in message


def test_error_messages_still_show_a_short_bad_value():
    with pytest.raises(TransformError, match="TBD"):
        parse_money("TBD")
