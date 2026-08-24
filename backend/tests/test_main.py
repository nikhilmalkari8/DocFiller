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
    assert resp.json() == {"status": "ok"}


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
