from services.filenames import build_filenames


def test_plain_values_become_filenames():
    rows = [{"Bond Number": "BND-1041"}, {"Bond Number": "BND-1042"}]
    assert build_filenames(rows, "Bond Number", ".pdf") == ["BND-1041.pdf", "BND-1042.pdf"]


def test_illegal_characters_are_sanitized():
    rows = [{"Name": "a/b:c*d"}]
    result = build_filenames(rows, "Name", ".pdf")
    assert result == ["a_b_c_d.pdf"]
    for ch in '/\\:*?"<>|':
        assert ch not in result[0]


def test_long_value_truncated_to_sixty_chars():
    rows = [{"Name": "x" * 90}]
    result = build_filenames(rows, "Name", ".pdf")
    basename = result[0][: -len(".pdf")]
    assert len(basename) == 60


def test_blank_cell_falls_back_to_row_number():
    rows = [{"Name": "John"}, {"Name": ""}]
    assert build_filenames(rows, "Name", ".pdf") == ["John.pdf", "row_2.pdf"]


def test_no_filename_column_falls_back_to_row_number_for_every_row():
    rows = [{"Name": "John"}, {"Name": "Jane"}]
    assert build_filenames(rows, None, ".pdf") == ["row_1.pdf", "row_2.pdf"]


def test_leading_and_trailing_dots_and_spaces_are_stripped():
    rows = [{"Name": "  .hidden.  "}]
    result = build_filenames(rows, "Name", ".pdf")
    assert not result[0].startswith(".")
    assert not result[0][: -len(".pdf")].endswith(".")
    assert not result[0][: -len(".pdf")].endswith(" ")


def test_duplicate_names_get_row_suffix_and_stay_unique():
    rows = [
        {"Name": "John Doe"},
        {"Name": "Someone Else"},
        {"Name": "John Doe"},
        {"Name": "Another"},
        {"Name": "John Doe"},
    ]
    result = build_filenames(rows, "Name", ".pdf")
    assert result[0] == "John_Doe_row_1.pdf"
    assert result[2] == "John_Doe_row_3.pdf"
    assert result[4] == "John_Doe_row_5.pdf"
    assert len(set(result)) == len(result)


def test_all_same_name_sheet_stays_fully_unique():
    rows = [{"Name": "Same"} for _ in range(6)]
    result = build_filenames(rows, "Name", ".pdf")
    assert len(set(result)) == len(result) == 6


def test_suffixed_name_colliding_with_another_rows_raw_value_stays_unique():
    """Regression: a row whose raw value happens to sanitize to the exact
    string another (colliding) row would be suffixed to must not produce a
    silent duplicate filename — this caused real data loss in Download All's
    zip (one document silently overwriting another)."""
    rows = [
        {"Name": "Bond"},  # row 1 (n=1) -- collides with row 3 below
        {"Name": "Other"},  # row 2 (n=2)
        {"Name": "Bond"},  # row 3 (n=3) -- "Bond" collides, both get _row_{n}
        {"Name": "Bond_row_3"},  # row 4 (n=4) -- sanitizes to exactly "Bond_row_3"
    ]
    result = build_filenames(rows, "Name", ".pdf")
    assert len(set(result)) == len(result), f"duplicate filenames produced: {result}"
