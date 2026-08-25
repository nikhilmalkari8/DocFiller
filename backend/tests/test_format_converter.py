import os
import shutil
import threading

import pymupdf
import pytest

from services import format_converter
from services.format_converter import (
    ConversionError,
    ConversionUnavailableError,
    convert_many_to_pdf,
    convert_to_pdf,
    is_conversion_available,
)
from tests.conftest import make_valid_docx_bytes


def _fake_run_factory(missing_indices=None, returncode=0):
    """Builds a fake replacement for subprocess.run that inspects the real
    soffice command being built (--outdir, input paths) and writes fake PDF
    bytes to the output paths it implies — except for indices in
    missing_indices, simulating soffice failing to convert that one input."""
    missing_indices = set(missing_indices or [])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        outdir_index = cmd.index("--outdir") + 1
        outdir = cmd[outdir_index]
        input_paths = cmd[outdir_index + 1 :]

        for i, input_path in enumerate(input_paths):
            if i in missing_indices:
                continue
            base = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(outdir, f"{base}.pdf")
            with open(output_path, "wb") as f:
                f.write(b"%PDF-fake-output")

        class FakeCompletedProcess:
            pass

        result = FakeCompletedProcess()
        result.returncode = returncode
        result.stderr = b"simulated soffice stderr"
        return result

    fake_run.calls = calls
    return fake_run


def test_command_shape_and_flags(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    fake_run = _fake_run_factory()
    monkeypatch.setattr(format_converter.subprocess, "run", fake_run)

    convert_many_to_pdf([b"doc-bytes"], ".docm")

    assert len(fake_run.calls) == 1
    cmd = fake_run.calls[0]
    assert "--headless" in cmd
    assert "--convert-to" in cmd
    assert cmd[cmd.index("--convert-to") + 1] == "pdf:writer_pdf_Export"
    assert "--outdir" in cmd
    assert any(arg.startswith("-env:UserInstallation=file://") for arg in cmd)
    # input file keeps the source extension
    assert any(arg.endswith(".docm") for arg in cmd)


def test_profile_dir_is_unique_per_call(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    fake_run = _fake_run_factory()
    monkeypatch.setattr(format_converter.subprocess, "run", fake_run)

    convert_many_to_pdf([b"doc-bytes"], ".docx")
    convert_many_to_pdf([b"doc-bytes"], ".docx")

    profile_args = [
        next(a for a in cmd if a.startswith("-env:UserInstallation=file://"))
        for cmd in fake_run.calls
    ]
    assert profile_args[0] != profile_args[1]


def test_convert_many_passes_all_inputs_in_one_invocation(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    fake_run = _fake_run_factory()
    monkeypatch.setattr(format_converter.subprocess, "run", fake_run)

    results = convert_many_to_pdf([b"doc-a", b"doc-b", b"doc-c"], ".docx")

    assert len(fake_run.calls) == 1  # one batch invocation, not three
    assert len(results) == 3
    assert all(r == b"%PDF-fake-output" for r in results)


def test_missing_output_is_retried_individually_not_the_whole_batch(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    # First call (the batch): index 1 fails to produce output.
    # Second call (the retry of just index 1): succeeds.
    call_count = {"n": 0}
    batch_run = _fake_run_factory(missing_indices=[1])
    retry_run = _fake_run_factory()

    def dispatch(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return batch_run(cmd, **kwargs)
        return retry_run(cmd, **kwargs)

    monkeypatch.setattr(format_converter.subprocess, "run", dispatch)

    results = convert_many_to_pdf([b"doc-a", b"doc-b", b"doc-c"], ".docx")

    assert call_count["n"] == 2  # one batch + one individual retry, not three
    assert results[0] == b"%PDF-fake-output"
    assert results[1] == b"%PDF-fake-output"  # recovered by retry
    assert results[2] == b"%PDF-fake-output"
    # the retry invocation only re-sent the one failed document
    retry_cmd = retry_run.calls[0]
    outdir_index = retry_cmd.index("--outdir") + 1
    assert len(retry_cmd[outdir_index + 1 :]) == 1


def test_when_retry_also_fails_that_slot_stays_none_others_unaffected(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    call_count = {"n": 0}
    batch_run = _fake_run_factory(missing_indices=[1])
    failing_retry_run = _fake_run_factory(missing_indices=[0])  # the retry's only doc is at index 0

    def dispatch(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return batch_run(cmd, **kwargs)
        return failing_retry_run(cmd, **kwargs)

    monkeypatch.setattr(format_converter.subprocess, "run", dispatch)

    results = convert_many_to_pdf([b"doc-a", b"doc-b", b"doc-c"], ".docx")

    assert results[0] == b"%PDF-fake-output"
    assert results[1] is None
    assert results[2] == b"%PDF-fake-output"


def test_batch_timeout_falls_back_to_individual_retry_others_recover(monkeypatch):
    # The batch invocation hangs and times out; each document is then retried
    # individually and succeeds, so a slow/hung document doesn't take down
    # the whole batch's results.
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    call_count = {"n": 0}
    retry_run = _fake_run_factory()

    def dispatch(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise format_converter.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return retry_run(cmd, **kwargs)

    monkeypatch.setattr(format_converter.subprocess, "run", dispatch)

    results = convert_many_to_pdf([b"doc-a", b"doc-b", b"doc-c"], ".docx")

    assert call_count["n"] == 4  # 1 timed-out batch + 3 individual retries
    assert results == [b"%PDF-fake-output"] * 3


def test_individual_retry_timeout_leaves_that_slot_none_others_unaffected(monkeypatch):
    # The batch times out; on individual retry, one specific document (the
    # pathological one) times out again while its siblings convert fine.
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    call_count = {"n": 0}
    retry_run = _fake_run_factory()

    def dispatch(cmd, **kwargs):
        call_count["n"] += 1
        # call 1: the whole-batch attempt, times out.
        # calls 2-4: individual retries for docs 0, 1, 2 in order — the
        # retry for doc 1 (call 3) times out again; the others succeed.
        if call_count["n"] in (1, 3):
            raise format_converter.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return retry_run(cmd, **kwargs)

    monkeypatch.setattr(format_converter.subprocess, "run", dispatch)

    results = convert_many_to_pdf([b"doc-a", b"doc-b", b"doc-c"], ".docx")

    assert results[0] == b"%PDF-fake-output"
    assert results[1] is None
    assert results[2] == b"%PDF-fake-output"


def test_missing_soffice_raises_conversion_unavailable_error(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: None)
    assert is_conversion_available() is False
    with pytest.raises(ConversionUnavailableError):
        convert_many_to_pdf([b"doc-bytes"], ".docx")


def test_nonzero_exit_with_no_outputs_at_all_raises_conversion_error(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    fake_run = _fake_run_factory(missing_indices=[0], returncode=1)
    monkeypatch.setattr(format_converter.subprocess, "run", fake_run)

    with pytest.raises(ConversionError):
        convert_many_to_pdf([b"doc-bytes"], ".docx")


def test_convert_to_pdf_raises_when_its_slot_comes_back_none(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    fake_run = _fake_run_factory(missing_indices=[0], returncode=0)
    monkeypatch.setattr(format_converter.subprocess, "run", fake_run)

    with pytest.raises(ConversionError):
        convert_to_pdf(b"doc-bytes", ".docx")


def test_temp_files_cleaned_up_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")
    fake_run = _fake_run_factory()
    monkeypatch.setattr(format_converter.subprocess, "run", fake_run)

    before = set(os.listdir(format_converter.tempfile.gettempdir()))
    convert_many_to_pdf([b"doc-bytes"], ".docx")
    after = set(os.listdir(format_converter.tempfile.gettempdir()))

    assert after - before == set(), "temp directory left behind after a successful conversion"


def test_temp_files_cleaned_up_when_soffice_raises(monkeypatch):
    monkeypatch.setattr(format_converter.shutil, "which", lambda name: "/usr/bin/soffice")

    def raising_run(cmd, **kwargs):
        raise OSError("simulated crash")

    monkeypatch.setattr(format_converter.subprocess, "run", raising_run)

    before = set(os.listdir(format_converter.tempfile.gettempdir()))
    with pytest.raises(Exception):
        convert_many_to_pdf([b"doc-bytes"], ".docx")
    after = set(os.listdir(format_converter.tempfile.gettempdir()))

    assert after - before == set(), "temp directory left behind after a crashed conversion"


# --- Real, unmocked conversion — the test that actually proves correctness.
# Mocked tests above prove the glue code (command shape, retry, cleanup) but
# would happily pass even if real conversion produced a blank PDF full of
# raw "«Name»" placeholders — this is the one that catches that.


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_real_conversion_produces_filled_pdf_not_raw_placeholders():
    from services.word_processor import fill_word_template, flatten_merge_fields

    docx = make_valid_docx_bytes(["Name"])
    filled = fill_word_template(docx, {"Name": "John Doe"})
    flattened = flatten_merge_fields(filled)

    pdf_bytes = convert_to_pdf(flattened, ".docx")

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()

    assert "John Doe" in text
    assert "«Name»" not in text
    assert "MERGEFIELD" not in text


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_real_batch_conversion_of_three_documents_each_shows_own_value():
    from services.word_processor import fill_word_template, flatten_merge_fields

    docx = make_valid_docx_bytes(["Name"])
    docs = [
        flatten_merge_fields(fill_word_template(docx, {"Name": name}))
        for name in ["John Doe", "Jane Smith", "Ann Lee"]
    ]

    results = convert_many_to_pdf(docs, ".docx")

    assert len(results) == 3
    for result, expected_name in zip(results, ["John Doe", "Jane Smith", "Ann Lee"]):
        assert result is not None
        doc = pymupdf.open(stream=result, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        assert expected_name in text
