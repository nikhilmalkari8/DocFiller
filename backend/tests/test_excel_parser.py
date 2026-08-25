import pytest

from services.excel_parser import get_all_rows, get_row_data, parse_excel
from tests.conftest import make_excel_bytes


def test_parse_excel_extracts_columns_preview_and_total_rows():
    data = parse_excel(
        make_excel_bytes(
            ["Name", "Date", "Amount"],
            [["John Doe", "2024-01-15", 5000], ["Jane Smith", "2024-02-20", 7500]],
        )
    )

    assert data["columns"] == ["Name", "Date", "Amount"]
    assert data["total_rows"] == 2
    assert data["preview"] == [
        {"Name": "John Doe", "Date": "2024-01-15", "Amount": "5000"},
        {"Name": "Jane Smith", "Date": "2024-02-20", "Amount": "7500"},
    ]


def test_parse_excel_preview_caps_at_five_rows_but_counts_all():
    rows = [[f"Person {i}", "2024-01-01", i] for i in range(8)]
    data = parse_excel(make_excel_bytes(["Name", "Date", "Amount"], rows))

    assert data["total_rows"] == 8
    assert len(data["preview"]) == 5


def test_parse_excel_raises_on_no_headers():
    with pytest.raises(ValueError):
        parse_excel(make_excel_bytes([], []))


def test_parse_excel_handles_missing_trailing_cells_in_a_row():
    # A row shorter than the header row (e.g. trailing columns left blank in the sheet)
    data = parse_excel(make_excel_bytes(["Name", "Date", "Amount"], [["Solo Name"]]))

    assert data["preview"] == [{"Name": "Solo Name", "Date": "", "Amount": ""}]


def test_get_row_data_returns_correct_row_by_index():
    xb = make_excel_bytes(
        ["Name", "Date", "Amount"],
        [["John Doe", "2024-01-15", 5000], ["Jane Smith", "2024-02-20", 7500]],
    )

    assert get_row_data(xb, 0) == {"Name": "John Doe", "Date": "2024-01-15", "Amount": "5000"}
    assert get_row_data(xb, 1) == {"Name": "Jane Smith", "Date": "2024-02-20", "Amount": "7500"}


def test_get_row_data_out_of_range_returns_empty_dict():
    xb = make_excel_bytes(["Name", "Date"], [["John Doe", "2024-01-15"]])

    assert get_row_data(xb, 5) == {}


def test_get_row_data_on_completely_empty_workbook_returns_empty_dict():
    # Same StopIteration risk as parse_excel's no-headers case — regression guard
    # for the identical fix applied to this function.
    assert get_row_data(make_excel_bytes([], []), 0) == {}


def test_get_all_rows_returns_every_data_row():
    xb = make_excel_bytes(
        ["Name", "Date"],
        [
            ["John Doe", "2024-01-15"],
            ["Jane Smith", "2024-02-20"],
            ["Ann Lee", "2024-03-01"],
        ],
    )

    rows = get_all_rows(xb)

    assert rows == [
        get_row_data(xb, 0),
        get_row_data(xb, 1),
        get_row_data(xb, 2),
    ]
    assert rows == [
        {"Name": "John Doe", "Date": "2024-01-15"},
        {"Name": "Jane Smith", "Date": "2024-02-20"},
        {"Name": "Ann Lee", "Date": "2024-03-01"},
    ]


def test_get_all_rows_on_headers_only_sheet_returns_empty_list():
    xb = make_excel_bytes(["Name", "Date"], [])

    assert get_all_rows(xb) == []
