import pytest

from services.format_converter import ConversionError, ConversionUnavailableError
from tests.conftest import make_docx_bytes, make_excel_bytes, make_pdf_bytes


def _upload(client, excel_bytes=None, template_bytes=None, template_name="template.pdf"):
    excel_bytes = excel_bytes or make_excel_bytes(
        ["Name", "Date"], [["John Doe", "2024-01-15"]]
    )
    template_bytes = template_bytes or make_pdf_bytes(["Name", "Date"])
    return client.post(
        "/api/upload",
        files={
            "excel_file": ("data.xlsx", excel_bytes, "application/vnd.ms-excel"),
            "template_file": (template_name, template_bytes, "application/octet-stream"),
        },
    )


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["pdf_conversion"], bool)


# --- /api/upload ---


def test_upload_pdf_template_success(client):
    resp = _upload(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["excel_columns"] == ["Name", "Date"]
    assert body["placeholders"] == ["Date", "Name"]
    assert body["total_rows"] == 1
    assert "session_id" in body and body["session_id"]


def test_upload_word_template_success(client):
    resp = _upload(client, template_bytes=make_docx_bytes(["Name", "Date"]), template_name="t.docx")
    assert resp.status_code == 200
    body = resp.json()
    assert body["placeholders"] == ["Name", "Date"]
    assert body["template_type"] == "word"


def test_upload_pdf_template_reports_template_type_pdf(client):
    resp = _upload(client)
    assert resp.status_code == 200
    assert resp.json()["template_type"] == "pdf"


def test_upload_docm_template_reports_template_type_word(client):
    resp = _upload(client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docm")
    assert resp.status_code == 200
    assert resp.json()["template_type"] == "word"


def test_upload_rejects_bad_excel_extension(client):
    resp = client.post(
        "/api/upload",
        files={
            "excel_file": ("data.csv", b"a,b\n1,2", "text/csv"),
            "template_file": ("template.pdf", make_pdf_bytes(["Name"]), "application/pdf"),
        },
    )
    assert resp.status_code == 400
    assert "xlsx" in resp.json()["detail"]


def test_upload_rejects_bad_template_extension(client):
    resp = client.post(
        "/api/upload",
        files={
            "excel_file": ("data.xlsx", make_excel_bytes(["Name"], [["a"]]), "application/vnd.ms-excel"),
            "template_file": ("template.txt", b"hello", "text/plain"),
        },
    )
    assert resp.status_code == 400
    assert "PDF or Word" in resp.json()["detail"]


def test_upload_rejects_malformed_excel_bytes(client):
    resp = client.post(
        "/api/upload",
        files={
            "excel_file": ("data.xlsx", b"not a real xlsx file", "application/vnd.ms-excel"),
            "template_file": ("template.pdf", make_pdf_bytes(["Name"]), "application/pdf"),
        },
    )
    assert resp.status_code == 400
    assert "Failed to parse Excel file" in resp.json()["detail"]


def test_upload_pdf_with_no_placeholders_returns_400(client):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "No placeholders in this document.")
    blank_pdf = doc.write()
    doc.close()

    resp = client.post(
        "/api/upload",
        files={
            "excel_file": ("data.xlsx", make_excel_bytes(["Name"], [["a"]]), "application/vnd.ms-excel"),
            "template_file": ("template.pdf", blank_pdf, "application/pdf"),
        },
    )
    assert resp.status_code == 400
    assert "No placeholders found" in resp.json()["detail"]


def test_upload_word_with_no_merge_fields_returns_400(client):
    resp = client.post(
        "/api/upload",
        files={
            "excel_file": ("data.xlsx", make_excel_bytes(["Name"], [["a"]]), "application/vnd.ms-excel"),
            "template_file": ("template.docx", make_docx_bytes([]), "application/octet-stream"),
        },
    )
    assert resp.status_code == 400
    assert "No merge fields found" in resp.json()["detail"]


# --- /api/map ---


def test_map_unknown_session_returns_404(client):
    resp = client.post(
        "/api/map",
        json={"session_id": "does-not-exist", "excel_columns": ["Name"], "placeholders": ["Name"]},
    )
    assert resp.status_code == 404


def test_map_valid_session_returns_mapping(client, monkeypatch):
    session_id = _upload(client).json()["session_id"]
    # Deliberately a mapping _fallback_mapping could never produce for these inputs
    # (it always exact-matches "Name"->"Name" first) — so this test actually fails
    # if the mock isn't engaged and the real fallback runs instead.
    monkeypatch.setattr("main.map_fields", lambda **kwargs: {"Name": "Date", "Date": "Name"})

    resp = client.post(
        "/api/map",
        json={"session_id": session_id, "excel_columns": ["Name", "Date"], "placeholders": ["Name", "Date"]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"mapping": {"Name": "Date", "Date": "Name"}}


def test_map_propagates_mapper_failure_as_500(client, monkeypatch):
    session_id = _upload(client).json()["session_id"]

    def failing(**kwargs):
        raise RuntimeError("all providers down")

    monkeypatch.setattr("main.map_fields", failing)

    resp = client.post(
        "/api/map",
        json={"session_id": session_id, "excel_columns": ["Name"], "placeholders": ["Name"]},
    )
    assert resp.status_code == 500


# --- /api/generate ---


def test_generate_unknown_session_returns_404(client):
    resp = client.post("/api/generate", json={"session_id": "does-not-exist", "mapping": {}})
    assert resp.status_code == 404


def test_generate_pdf_success(client):
    session_id = _upload(client).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "row_index": 0},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert 'filename="filled_document.pdf"' in resp.headers["content-disposition"]
    assert b"John Doe" in resp.content


def test_generate_word_docx_success(client):
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name", "Date"]), template_name="t.docx"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "row_index": 0},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert 'filename="filled_document.docx"' in resp.headers["content-disposition"]


def test_generate_word_docm_uses_macro_enabled_mime_type(client):
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docm"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "row_index": 0},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.ms-word.document.macroEnabled.12"
    assert 'filename="filled_document.docm"' in resp.headers["content-disposition"]


def test_generate_with_filename_column_names_file_from_that_column(client):
    session_id = _upload(client).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={
            "session_id": session_id,
            "mapping": {"Name": "Name", "Date": "Date"},
            "row_index": 0,
            "filename_column": "Name",
        },
    )

    assert resp.status_code == 200
    assert 'filename="John_Doe.pdf"' in resp.headers["content-disposition"]


def test_generate_with_out_of_range_row_index_produces_blank_fields(client):
    """Documents current behavior: get_row_data returns {} for an out-of-range row
    rather than raising, so /api/generate still succeeds but fills nothing. Not a
    crash, but flagged here so a future change to this behavior is a deliberate,
    visible diff rather than a silent one."""
    session_id = _upload(client).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "row_index": 99},
    )

    assert resp.status_code == 200
    assert b"John Doe" not in resp.content


# --- /api/generate: output_format ---


def _sentinel_converter(monkeypatch, pdf_bytes=b"%PDF-converted-sentinel"):
    """Replaces the real LibreOffice-backed converter with a sentinel so
    these route tests exercise main.py's own logic, independent of whether
    LibreOffice is installed on the machine running the suite."""
    calls = []

    def fake_convert_to_pdf(doc_bytes, source_ext=".docx", timeout=120):
        import threading

        calls.append(threading.current_thread())
        return pdf_bytes

    monkeypatch.setattr("main.convert_to_pdf", fake_convert_to_pdf)
    return calls


def test_generate_word_pdf_format_returns_pdf(client, monkeypatch):
    _sentinel_converter(monkeypatch)
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docx"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "output_format": "pdf"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert 'filename="filled_document.pdf"' in resp.headers["content-disposition"]


def test_generate_word_original_or_absent_format_returns_word_converter_never_called(client, monkeypatch):
    calls = _sentinel_converter(monkeypatch)
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docx"
    ).json()["session_id"]

    for output_format in [None, "original", "docx"]:
        body = {"session_id": session_id, "mapping": {"Name": "Name"}}
        if output_format is not None:
            body["output_format"] = output_format
        resp = client.post("/api/generate", json=body)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    assert calls == []


def test_generate_pdf_template_pdf_or_absent_format_converter_never_called(client, monkeypatch):
    calls = _sentinel_converter(monkeypatch)
    session_id = _upload(client).json()["session_id"]  # PDF template

    for output_format in [None, "pdf"]:
        body = {"session_id": session_id, "mapping": {"Name": "Name"}}
        if output_format is not None:
            body["output_format"] = output_format
        resp = client.post("/api/generate", json=body)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    assert calls == []


def test_generate_pdf_template_docx_format_returns_400(client, monkeypatch):
    _sentinel_converter(monkeypatch)
    session_id = _upload(client).json()["session_id"]  # PDF template

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "output_format": "docx"},
    )
    assert resp.status_code == 400


def test_generate_bogus_output_format_returns_422(client):
    session_id = _upload(client).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "output_format": "excel"},
    )
    assert resp.status_code == 422


def test_generate_conversion_unavailable_returns_503_no_word_content_returned(client, monkeypatch):
    def raising_converter(doc_bytes, source_ext=".docx", timeout=120):
        raise ConversionUnavailableError("soffice not installed")

    monkeypatch.setattr("main.convert_to_pdf", raising_converter)
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docx"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "output_format": "pdf"},
    )
    assert resp.status_code == 503
    assert resp.headers.get("content-type") != (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_generate_conversion_failure_returns_500_no_word_content_returned(client, monkeypatch):
    def raising_converter(doc_bytes, source_ext=".docx", timeout=120):
        raise ConversionError("soffice exited non-zero")

    monkeypatch.setattr("main.convert_to_pdf", raising_converter)
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docx"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "output_format": "pdf"},
    )
    assert resp.status_code == 500
    assert resp.headers.get("content-type") != (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_generate_conversion_runs_off_the_event_loop(client, monkeypatch):
    import threading

    calls = _sentinel_converter(monkeypatch)
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docx"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={"session_id": session_id, "mapping": {"Name": "Name"}, "output_format": "pdf"},
    )

    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0] != threading.main_thread()


def test_generate_pdf_format_with_filename_column_names_file_pdf_not_docx(client, monkeypatch):
    _sentinel_converter(monkeypatch)
    session_id = _upload(
        client, template_bytes=make_docx_bytes(["Name"]), template_name="t.docx"
    ).json()["session_id"]

    resp = client.post(
        "/api/generate",
        json={
            "session_id": session_id,
            "mapping": {"Name": "Name"},
            "output_format": "pdf",
            "filename_column": "Name",
        },
    )

    assert resp.status_code == 200
    assert 'filename="John_Doe.pdf"' in resp.headers["content-disposition"]


# --- /api/generate-all ---


def _upload_multi(client, rows, headers=("Name", "Date"), template_bytes=None, template_name="template.pdf"):
    excel_bytes = make_excel_bytes(list(headers), rows)
    template_bytes = template_bytes or make_pdf_bytes(list(headers))
    return _upload(client, excel_bytes=excel_bytes, template_bytes=template_bytes, template_name=template_name)


def test_generate_all_unknown_session_returns_404(client):
    resp = client.post("/api/generate-all", json={"session_id": "does-not-exist", "mapping": {}})
    assert resp.status_code == 404


def test_generate_all_three_row_pdf_success_with_filename_column(client):
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"], ["Jane Smith", "2024-02-20"], ["Ann Lee", "2024-03-01"]],
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={
            "session_id": session_id,
            "mapping": {"Name": "Name", "Date": "Date"},
            "filename_column": "Name",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_rows"] == 3
    assert body["success_count"] == 3
    assert body["error_count"] == 0
    assert body["skipped_count"] == 0

    filenames = [r["filename"] for r in body["results"]]
    assert filenames == ["John_Doe.pdf", "Jane_Smith.pdf", "Ann_Lee.pdf"]

    import base64

    expected_values = [b"John Doe", b"Jane Smith", b"Ann Lee"]
    for result, expected in zip(body["results"], expected_values):
        assert result["status"] == "ok"
        decoded = base64.b64decode(result["content_base64"])
        assert decoded.startswith(b"%PDF")
        assert expected in decoded


def test_generate_all_without_filename_column_uses_row_numbers(client):
    session_id = _upload_multi(
        client, [["John Doe", "2024-01-15"], ["Jane Smith", "2024-02-20"]]
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}},
    )

    assert resp.status_code == 200
    filenames = [r["filename"] for r in resp.json()["results"]]
    assert filenames == ["row_1.pdf", "row_2.pdf"]


def test_generate_all_word_docm_template(client):
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docm",
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}},
    )

    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["mime_type"] == "application/vnd.ms-word.document.macroEnabled.12"
    assert result["filename"].endswith(".docm")


def test_generate_all_partial_failure_does_not_block_other_rows(client, monkeypatch):
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"], ["Jane Smith", "2024-02-20"], ["Ann Lee", "2024-03-01"]],
    ).json()["session_id"]

    import main as main_module

    real_fill_pdf = main_module.fill_pdf

    def flaky_fill_pdf(template_bytes, values):
        if values.get("Name") == "Jane Smith":
            raise RuntimeError("simulated fill failure")
        return real_fill_pdf(template_bytes, values)

    monkeypatch.setattr(main_module, "fill_pdf", flaky_fill_pdf)

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success_count"] == 2
    assert body["error_count"] == 1
    assert body["results"][0]["status"] == "ok"
    assert body["results"][0]["content_base64"] is not None
    assert body["results"][1]["status"] == "error"
    assert body["results"][1]["error"] is not None
    assert body["results"][1]["content_base64"] is None
    assert body["results"][2]["status"] == "ok"
    assert body["results"][2]["content_base64"] is not None


def test_generate_all_row_with_all_mapped_columns_empty_is_skipped(client):
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"], ["", ""]],
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_count"] == 1
    assert body["results"][1]["status"] == "skipped"
    assert body["results"][1]["content_base64"] is None


def test_generate_all_excel_read_failure_returns_clean_400(client, monkeypatch):
    session_id = _upload_multi(client, [["John Doe", "2024-01-15"]]).json()["session_id"]

    import main as main_module

    def failing_get_all_rows(file_bytes):
        raise ValueError("corrupt sheet")

    monkeypatch.setattr(main_module, "get_all_rows", failing_get_all_rows)

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name"}},
    )

    assert resp.status_code == 400
    assert "Failed to read Excel rows" in resp.json()["detail"]


def test_generate_all_too_many_rows_returns_400(client):
    rows = [[f"Person {i}", "2024-01-01"] for i in range(201)]
    session_id = _upload_multi(client, rows).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}},
    )

    assert resp.status_code == 400
    assert "limited to 200 rows" in resp.json()["detail"]


def test_generate_all_bogus_output_format_returns_422(client):
    session_id = _upload_multi(
        client, [["John Doe", "2024-01-15"]]
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={
            "session_id": session_id,
            "mapping": {"Name": "Name", "Date": "Date"},
            "output_format": "excel",
        },
    )
    assert resp.status_code == 422


# --- /api/generate-all: output_format ---


def _sentinel_batch_converter(monkeypatch, results_by_source_ext=None, fail_index=None):
    """Replaces main.convert_many_to_pdf with a sentinel returning distinct
    fake PDF bytes per input (so tests can tell results apart), optionally
    with one index coming back None (simulating that row's conversion
    failing even after format_converter's own internal retry)."""
    calls = []

    def fake_convert_many(docs, source_ext, timeout=120):
        calls.append((docs, source_ext))
        results = []
        for i, _doc in enumerate(docs):
            if fail_index is not None and i == fail_index:
                results.append(None)
            else:
                results.append(f"%PDF-fake-{i}".encode())
        return results

    monkeypatch.setattr("main.convert_many_to_pdf", fake_convert_many)
    return calls


def test_generate_all_word_pdf_format_every_ok_result_is_pdf(client, monkeypatch):
    _sentinel_batch_converter(monkeypatch)
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"], ["Jane Smith", "2024-02-20"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docx",
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "output_format": "pdf"},
    )

    assert resp.status_code == 200
    body = resp.json()
    import base64

    for result in body["results"]:
        assert result["status"] == "ok"
        assert result["mime_type"] == "application/pdf"
        assert result["filename"].endswith(".pdf")
        assert base64.b64decode(result["content_base64"]).startswith(b"%PDF")


def test_generate_all_pdf_format_converter_called_once_for_whole_batch(client, monkeypatch):
    calls = _sentinel_batch_converter(monkeypatch)
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"], ["Jane Smith", "2024-02-20"], ["Ann Lee", "2024-03-01"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docx",
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "output_format": "pdf"},
    )

    assert resp.status_code == 200
    assert len(calls) == 1  # one batch call, not once per row
    assert len(calls[0][0]) == 3  # all three documents in that one call


def test_generate_all_word_original_or_absent_format_converter_never_called(client, monkeypatch):
    calls = _sentinel_batch_converter(monkeypatch)
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docm",
    ).json()["session_id"]

    for output_format in [None, "original"]:
        body = {"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}}
        if output_format is not None:
            body["output_format"] = output_format
        resp = client.post("/api/generate-all", json=body)
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["mime_type"] == "application/vnd.ms-word.document.macroEnabled.12"
        assert result["filename"].endswith(".docm")

    assert calls == []


def test_generate_all_pdf_template_docx_format_returns_400(client, monkeypatch):
    _sentinel_batch_converter(monkeypatch)
    session_id = _upload_multi(client, [["John Doe", "2024-01-15"]]).json()["session_id"]  # PDF template

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "output_format": "docx"},
    )
    assert resp.status_code == 400


def test_generate_all_converter_unavailable_fails_fast_before_any_row_filled(client, monkeypatch):
    fill_calls = []
    import main as main_module

    def spy_fill_word_template(doc_bytes, values):
        fill_calls.append(values)
        return b"filled-sentinel"

    def raising_availability_check():
        return False

    monkeypatch.setattr(main_module, "fill_word_template", spy_fill_word_template)
    monkeypatch.setattr("main.is_conversion_available", raising_availability_check)

    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docx",
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "output_format": "pdf"},
    )

    assert resp.status_code == 503
    assert fill_calls == []  # fail-fast: no row was filled before the availability check


def test_generate_all_one_row_conversion_failure_does_not_block_others(client, monkeypatch):
    _sentinel_batch_converter(monkeypatch, fail_index=1)
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"], ["Jane Smith", "2024-02-20"], ["Ann Lee", "2024-03-01"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docx",
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={"session_id": session_id, "mapping": {"Name": "Name", "Date": "Date"}, "output_format": "pdf"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["status"] == "ok"
    assert body["results"][1]["status"] == "error"
    assert body["results"][1]["error"] is not None
    assert body["results"][2]["status"] == "ok"


def test_generate_all_pdf_format_with_filename_column_names_pdf(client, monkeypatch):
    _sentinel_batch_converter(monkeypatch)
    session_id = _upload_multi(
        client,
        [["John Doe", "2024-01-15"]],
        template_bytes=make_docx_bytes(["Name", "Date"]),
        template_name="t.docx",
    ).json()["session_id"]

    resp = client.post(
        "/api/generate-all",
        json={
            "session_id": session_id,
            "mapping": {"Name": "Name", "Date": "Date"},
            "output_format": "pdf",
            "filename_column": "Name",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["results"][0]["filename"] == "John_Doe.pdf"


# --- transforms in mapping (TICKET-005) ---

AMOUNT_WORDS_SPEC = {"type": "amount_in_words", "source": "Amount"}
MIXED_MAPPING = {"Name": "Name", "AmountWords": AMOUNT_WORDS_SPEC}


def _docx_xml(docx_bytes):
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _upload_amounts(client, rows, headers=("Name", "Amount")):
    resp = _upload(
        client,
        excel_bytes=make_excel_bytes(list(headers), rows),
        template_bytes=make_docx_bytes(["Name", "AmountWords"]),
        template_name="t.docx",
    )
    assert resp.status_code == 200
    return resp.json()["session_id"]


def test_generate_accepts_mixed_string_and_spec_mapping(client):
    sid = _upload_amounts(client, [["John Doe", 1200000]])
    resp = client.post("/api/generate", json={"session_id": sid, "mapping": MIXED_MAPPING, "row_index": 0})
    assert resp.status_code == 200
    xml = _docx_xml(resp.content)
    assert "John Doe" in xml
    assert "one million two hundred thousand and 00/100 dollars" in xml


def test_generate_all_accepts_mixed_string_and_spec_mapping(client):
    import base64

    sid = _upload_amounts(client, [["John Doe", 1200000]])
    resp = client.post("/api/generate-all", json={"session_id": sid, "mapping": MIXED_MAPPING})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success_count"] == 1
    xml = _docx_xml(base64.b64decode(body["results"][0]["content_base64"]))
    assert "John Doe" in xml
    assert "one million two hundred thousand and 00/100 dollars" in xml


def test_generate_transform_handles_a_float_numeric_cell(client):
    sid = _upload_amounts(client, [["John Doe", 1234.56]])
    resp = client.post("/api/generate", json={"session_id": sid, "mapping": MIXED_MAPPING, "row_index": 0})
    assert resp.status_code == 200
    assert "one thousand two hundred thirty-four and 56/100 dollars" in _docx_xml(resp.content)


INVALID_SPECS = [
    pytest.param({"type": "percent", "source": "Amount"}, id="unknown_type"),
    pytest.param({"type": "amount_in_words", "source": "No Such Column"}, id="source_not_a_column"),
    pytest.param(
        {"type": "date_format", "source": "Amount", "format": "%H"}, id="unsupported_date_directive"
    ),
]


@pytest.mark.parametrize("bad_spec", INVALID_SPECS)
@pytest.mark.parametrize("endpoint", ["/api/generate", "/api/generate-all"])
def test_invalid_spec_is_rejected_with_400_naming_the_placeholder(client, endpoint, bad_spec):
    sid = _upload_amounts(client, [["John Doe", 1200000]])
    resp = client.post(
        endpoint,
        json={"session_id": sid, "mapping": {"Name": "Name", "AmountWords": bad_spec}},
    )
    assert resp.status_code == 400
    assert "AmountWords" in resp.json()["detail"]


def test_invalid_spec_in_bulk_fails_before_any_row_is_filled(client, monkeypatch):
    import main as main_module

    calls = []
    monkeypatch.setattr(main_module, "fill_word_template", lambda *a, **k: calls.append(1) or b"x")
    monkeypatch.setattr(main_module, "fill_pdf", lambda *a, **k: calls.append(1) or b"x")

    sid = _upload_amounts(client, [["John Doe", 1200000], ["Jane Smith", 5000]])
    resp = client.post(
        "/api/generate-all",
        json={"session_id": sid, "mapping": {"AmountWords": {"type": "nope"}}},
    )
    assert resp.status_code == 400
    assert calls == []


def test_mapping_value_of_the_wrong_json_type_is_422(client):
    sid = _upload_amounts(client, [["John Doe", 1200000]])
    resp = client.post("/api/generate", json={"session_id": sid, "mapping": {"Name": 5}})
    assert resp.status_code == 422


def test_generate_bad_cell_value_for_a_transform_is_400_naming_the_placeholder(client):
    sid = _upload_amounts(client, [["John Doe", "TBD"]])
    resp = client.post("/api/generate", json={"session_id": sid, "mapping": MIXED_MAPPING, "row_index": 0})
    assert resp.status_code == 400
    assert "AmountWords" in resp.json()["detail"]


def test_generate_all_row_transform_error_does_not_block_other_rows(client):
    sid = _upload_amounts(client, [["John Doe", 1200000], ["Jane Smith", "TBD"], ["Ann Lee", 5000]])
    resp = client.post("/api/generate-all", json={"session_id": sid, "mapping": MIXED_MAPPING})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success_count"] == 2
    assert body["error_count"] == 1
    assert [r["status"] for r in body["results"]] == ["ok", "error", "ok"]
    assert body["results"][1]["content_base64"] is None
    assert "AmountWords" in body["results"][1]["error"]


def test_generate_all_fully_blank_row_is_skipped_not_errored_with_transforms(client):
    sid = _upload_amounts(client, [["John Doe", 1200000], ["", ""]])
    resp = client.post("/api/generate-all", json={"session_id": sid, "mapping": MIXED_MAPPING})

    body = resp.json()
    assert resp.status_code == 200
    assert body["skipped_count"] == 1
    assert body["error_count"] == 0
    assert [r["status"] for r in body["results"]] == ["ok", "skipped"]


def test_generate_all_blank_amount_with_a_name_present_is_an_error_not_a_skip(client):
    sid = _upload_amounts(client, [["John Doe", ""]])
    resp = client.post("/api/generate-all", json={"session_id": sid, "mapping": MIXED_MAPPING})

    body = resp.json()
    assert body["error_count"] == 1
    assert body["skipped_count"] == 0
    assert body["results"][0]["status"] == "error"


def test_generate_all_skip_is_decided_on_raw_columns_not_join_separators(client):
    """A join template with literal separators yields non-blank text from blank
    inputs ('{City}, {State}' -> ','); that must not stop a blank row being skipped."""
    sid = _upload_amounts(client, [["", ""]], headers=("City", "State"))
    mapping = {"AmountWords": {"type": "join", "template": "{City}, {State}"}}
    resp = client.post("/api/generate-all", json={"session_id": sid, "mapping": mapping})

    body = resp.json()
    assert body["skipped_count"] == 1
    assert body["results"][0]["status"] == "skipped"


# --- /api/map transform opt-in (TICKET-005, D7) ---

def _map_request(sid, **extra):
    return {
        "session_id": sid,
        "excel_columns": ["Name", "Amount"],
        "placeholders": ["Name", "AmountWords"],
        **extra,
    }


def test_map_does_not_allow_transforms_by_default(client, monkeypatch):
    import main as main_module

    seen = {}

    def fake_map_fields(**kwargs):
        seen.update(kwargs)
        return {"Name": "Name", "AmountWords": ""}

    monkeypatch.setattr(main_module, "map_fields", fake_map_fields)
    sid = _upload_amounts(client, [["John Doe", 1200000]])

    resp = client.post("/api/map", json=_map_request(sid))

    assert resp.status_code == 200
    assert seen["allow_transforms"] is False


def test_map_can_opt_in_to_transforms_and_returns_the_spec_verbatim(client, monkeypatch):
    import main as main_module

    seen = {}

    def fake_map_fields(**kwargs):
        seen.update(kwargs)
        return {"Name": "Name", "AmountWords": AMOUNT_WORDS_SPEC}

    monkeypatch.setattr(main_module, "map_fields", fake_map_fields)
    sid = _upload_amounts(client, [["John Doe", 1200000]])

    resp = client.post("/api/map", json=_map_request(sid, allow_transforms=True))

    assert resp.status_code == 200
    assert seen["allow_transforms"] is True
    assert resp.json()["mapping"]["AmountWords"] == AMOUNT_WORDS_SPEC


def test_non_string_source_in_a_spec_is_400_not_500(client):
    sid = _upload_amounts(client, [["John Doe", 1200000]])
    bad = {"AmountWords": {"type": "copy", "source": ["Amount"]}}
    for endpoint in ("/api/generate", "/api/generate-all"):
        resp = client.post(endpoint, json={"session_id": sid, "mapping": bad})
        assert resp.status_code == 400, endpoint
        assert "AmountWords" in resp.json()["detail"]


def test_generate_strict_transform_on_out_of_range_row_is_400(client):
    """D9: plain-string mappings stay lenient (blank doc), but a strict transform
    on a row past the end of the sheet must fail rather than print a blank amount."""
    sid = _upload_amounts(client, [["John Doe", 1200000]])
    resp = client.post("/api/generate", json={"session_id": sid, "mapping": MIXED_MAPPING, "row_index": 99})
    assert resp.status_code == 400
    assert "AmountWords" in resp.json()["detail"]
