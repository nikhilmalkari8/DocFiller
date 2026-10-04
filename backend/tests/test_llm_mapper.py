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


# --- transform specs in LLM output (TICKET-005) ---
# The LLM may only *select* a catalog transform; anything it proposes is
# validated against the catalog and the real Excel columns, same as plain
# column mappings (llm-mapping-verification.md). Off by default (D7).

import json

import pytest

PENAL_COLUMNS = ["Name", "Penal Sum", "First", "Last"]


def _parse(value, allow_transforms=True, placeholder="Penal Sum in Words"):
    return _parse_and_validate(
        json.dumps({placeholder: value}),
        excel_columns=PENAL_COLUMNS,
        placeholders=[placeholder],
        allow_transforms=allow_transforms,
    )[placeholder]


def test_valid_spec_is_returned_unchanged():
    spec = {"type": "amount_in_words", "source": "Penal Sum"}
    assert _parse(spec) == spec


def test_valid_join_spec_is_returned():
    spec = {"type": "join", "template": "{First} {Last}"}
    assert _parse(spec) == spec


def test_spec_source_is_normalised_to_the_real_columns_case():
    got = _parse({"type": "amount_in_words", "source": "penal sum"})
    assert got == {"type": "amount_in_words", "source": "Penal Sum"}


def test_join_template_tokens_are_normalised_to_real_column_case():
    got = _parse({"type": "join", "template": "{first} {LAST}"})
    assert got == {"type": "join", "template": "{First} {Last}"}


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "percent", "source": "Penal Sum"},                         # not in catalog
        {"type": "amount_in_words", "source": "Invented Column"},           # invented source
        {"type": "join", "template": "{First} {Invented}"},                 # invented join column
        {"type": "amount_in_words", "source": "Penal Sum", "extra": 1},     # extra param
        {"type": "amount_in_words"},                                        # missing source
        {"source": "Penal Sum"},                                            # no type
        {"type": "copy", "source": ["Penal Sum"]},                          # non-string source
        {"type": "copy", "source": {"a": 1}},
        5,
        ["amount_in_words"],
    ],
)
def test_invalid_spec_is_dropped_to_empty_string(bad):
    assert _parse(bad) == ""


def test_spec_is_dropped_when_transforms_are_not_allowed():
    spec = {"type": "amount_in_words", "source": "Penal Sum"}
    assert _parse(spec, allow_transforms=False) == ""


def test_plain_column_string_still_works_when_transforms_are_allowed():
    assert _parse("Penal Sum", placeholder="Penal Sum") == "Penal Sum"


# --- prompt & threading (TICKET-005) ---

from services.llm_mapper import _build_prompt
from services.transforms import CATALOG


def test_prompt_lists_every_catalog_transform_when_allowed():
    prompt = _build_prompt(["Penal Sum"], ["Penal Sum in Words"], None, allow_transforms=True)
    for name in CATALOG:
        assert name in prompt
    assert '"type"' in prompt  # includes an example spec object


def test_prompt_mentions_no_transforms_when_not_allowed():
    prompt = _build_prompt(["Penal Sum"], ["Penal Sum in Words"], None, allow_transforms=False)
    for name in CATALOG:
        assert name not in prompt


def test_prompt_default_is_no_transforms():
    default = _build_prompt(["Penal Sum"], ["X"], None)
    assert default == _build_prompt(["Penal Sum"], ["X"], None, allow_transforms=False)


def test_map_fields_without_keys_returns_plain_strings_even_when_transforms_allowed(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = map_fields(["Name"], ["Name"], allow_transforms=True)

    assert result == {"Name": "Name"}  # same as today's fallback


def test_map_fields_passes_allow_transforms_to_the_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    seen = {}

    def fake_openai(api_key, prompt, columns, placeholders, allow_transforms=False):
        seen["allow"] = allow_transforms
        seen["prompt"] = prompt
        return {"Name": "Name"}

    monkeypatch.setattr("services.llm_mapper._map_with_openai", fake_openai)

    map_fields(["Name"], ["Name"], allow_transforms=True)
    assert seen["allow"] is True
    assert "amount_in_words" in seen["prompt"]

    map_fields(["Name"], ["Name"])
    assert seen["allow"] is False
    assert "amount_in_words" not in seen["prompt"]
