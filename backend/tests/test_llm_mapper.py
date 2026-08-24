from services.llm_mapper import _fallback_mapping, _parse_and_validate, map_fields


# --- _fallback_mapping (pure, no network) ---


def test_fallback_mapping_exact_match():
    result = _fallback_mapping(excel_columns=["Name", "Date"], placeholders=["Name"])
    assert result == {"Name": "Name"}


def test_fallback_mapping_normalized_match_ignores_case_space_underscore():
    result = _fallback_mapping(
        excel_columns=["Applicant Name"], placeholders=["applicant_name"]
    )
    assert result == {"applicant_name": "Applicant Name"}


def test_fallback_mapping_substring_match():
    result = _fallback_mapping(excel_columns=["Name"], placeholders=["Full Name"])
    assert result == {"Full Name": "Name"}


def test_fallback_mapping_no_match_returns_empty_string():
    result = _fallback_mapping(excel_columns=["Name", "Date"], placeholders=["Unrelated Field"])
    assert result == {"Unrelated Field": ""}


# --- _parse_and_validate (pure, no network) ---
# This is the safety net from llm-mapping-verification.md: a mapped column that
# isn't a real Excel column must never be trusted as-is.


def test_parse_and_validate_accepts_exact_column_match():
    result = _parse_and_validate(
        '{"Applicant Name": "Name"}',
        excel_columns=["Name", "Date"],
        placeholders=["Applicant Name"],
    )
    assert result == {"Applicant Name": "Name"}


def test_parse_and_validate_rejects_invented_column_name():
    result = _parse_and_validate(
        '{"Applicant Name": "TotallyMadeUpColumn"}',
        excel_columns=["Name", "Date"],
        placeholders=["Applicant Name"],
    )
    assert result == {"Applicant Name": ""}


def test_parse_and_validate_matches_column_case_insensitively():
    result = _parse_and_validate(
        '{"Applicant Name": "name"}',
        excel_columns=["Name", "Date"],
        placeholders=["Applicant Name"],
    )
    assert result == {"Applicant Name": "Name"}


def test_parse_and_validate_strips_markdown_code_fences():
    response = '```json\n{"Applicant Name": "Name"}\n```'
    result = _parse_and_validate(
        response, excel_columns=["Name", "Date"], placeholders=["Applicant Name"]
    )
    assert result == {"Applicant Name": "Name"}


def test_parse_and_validate_missing_placeholder_in_response_defaults_to_empty():
    result = _parse_and_validate(
        "{}", excel_columns=["Name", "Date"], placeholders=["Applicant Name"]
    )
    assert result == {"Applicant Name": ""}


# --- map_fields provider fallback chain — network calls always mocked ---


def test_map_fields_uses_openai_when_key_present_and_succeeds(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    openai_called = []
    gemini_called = []
    monkeypatch.setattr(
        "services.llm_mapper._map_with_openai",
        lambda *a, **k: (openai_called.append(1), {"Name": "Name"})[1],
    )
    monkeypatch.setattr(
        "services.llm_mapper._map_with_gemini",
        lambda *a, **k: (gemini_called.append(1), {"Name": "Name"})[1],
    )

    result = map_fields(excel_columns=["Name"], placeholders=["Name"])

    assert result == {"Name": "Name"}
    assert openai_called == [1]
    assert gemini_called == []


def test_map_fields_falls_back_to_gemini_when_openai_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def failing_openai(*a, **k):
        raise RuntimeError("OpenAI is down")

    gemini_called = []
    monkeypatch.setattr("services.llm_mapper._map_with_openai", failing_openai)
    monkeypatch.setattr(
        "services.llm_mapper._map_with_gemini",
        lambda *a, **k: (gemini_called.append(1), {"Name": "Name"})[1],
    )

    result = map_fields(excel_columns=["Name"], placeholders=["Name"])

    assert result == {"Name": "Name"}
    assert gemini_called == [1]


def test_map_fields_falls_back_to_basic_matching_when_no_keys_set(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = map_fields(excel_columns=["Name"], placeholders=["Name"])

    assert result == {"Name": "Name"}  # _fallback_mapping's exact-match path


def test_map_fields_falls_back_to_basic_matching_when_both_providers_fail(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "services.llm_mapper._map_with_openai",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    monkeypatch.setattr(
        "services.llm_mapper._map_with_gemini",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )

    result = map_fields(excel_columns=["Name"], placeholders=["Name"])

    assert result == {"Name": "Name"}  # _fallback_mapping's exact-match path
