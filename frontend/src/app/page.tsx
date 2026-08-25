"use client";

import { useState, useRef, useEffect, useCallback, DragEvent, ChangeEvent } from "react";
import JSZip from "jszip";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Step = "upload" | "review" | "generate";

interface UploadResponse {
  session_id: string;
  excel_columns: string[];
  excel_preview: Record<string, string>[];
  total_rows: number;
  placeholders: string[];
  template_type: "pdf" | "word";
}

type OutputFormat = "original" | "pdf";

interface BulkResult {
  row_index: number;
  status: "ok" | "error" | "skipped";
  label: string | null;
  filename: string | null;
  mime_type: string | null;
  content_base64: string | null;
  error: string | null;
}

function previewFilename(
  excelPreview: Record<string, string>[],
  filenameColumn: string,
  ext: string
): string {
  const raw = (excelPreview[0]?.[filenameColumn] ?? "").trim();
  const sanitized = raw
    .replace(/[/\\:*?"<>|\x00-\x1f]/g, "_")
    .replace(/\s+/g, "_")
    .replace(/^[ .]+|[ .]+$/g, "")
    .slice(0, 60);
  return `${sanitized || "row_1"}${ext}`;
}

export default function Home() {
  const [step, setStep] = useState<Step>("upload");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Upload state
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const excelInputRef = useRef<HTMLInputElement>(null);
  const templateInputRef = useRef<HTMLInputElement>(null);

  // Data state
  const [sessionId, setSessionId] = useState("");
  const [excelColumns, setExcelColumns] = useState<string[]>([]);
  const [excelPreview, setExcelPreview] = useState<Record<string, string>[]>(
    []
  );
  const [totalRows, setTotalRows] = useState(0);
  const [placeholders, setPlaceholders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [rowIndex, setRowIndex] = useState(0);

  // Generated state
  const [generatedBlob, setGeneratedBlob] = useState<Blob | null>(null);
  const [generatedFilename, setGeneratedFilename] = useState("filled_document.pdf");

  // Setup modal / bulk generation state
  const [showSetupModal, setShowSetupModal] = useState(false);
  const [filenameColumn, setFilenameColumn] = useState("");
  const [templateType, setTemplateType] = useState<"pdf" | "word">("pdf");
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("original");
  const [bulkResults, setBulkResults] = useState<BulkResult[] | null>(null);
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const modalSelectRef = useRef<HTMLSelectElement>(null);

  // The template's own extension (e.g. ".docm") — what "original" format downloads as.
  const templateExt = templateFile
    ? `.${templateFile.name.split(".").pop() || "pdf"}`
    : ".pdf";
  const currentExt = outputFormat === "pdf" ? ".pdf" : templateExt;

  // ───── Drag and Drop ─────
  const [dragOver, setDragOver] = useState<"excel" | "template" | null>(null);

  const handleDragOver = useCallback(
    (e: DragEvent, zone: "excel" | "template") => {
      e.preventDefault();
      setDragOver(zone);
    },
    []
  );

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragOver(null);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent, zone: "excel" | "template") => {
      e.preventDefault();
      setDragOver(null);
      const file = e.dataTransfer.files[0];
      if (!file) return;
      if (zone === "excel") setExcelFile(file);
      else setTemplateFile(file);
    },
    []
  );

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>, zone: "excel" | "template") => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (zone === "excel") setExcelFile(file);
      else setTemplateFile(file);
    },
    []
  );

  // ───── Upload ─────
  const handleUpload = async () => {
    if (!excelFile || !templateFile) return;
    setLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("excel_file", excelFile);
      formData.append("template_file", templateFile);

      const res = await fetch(`${API_URL}/api/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Upload failed");
      }

      const data: UploadResponse = await res.json();
      setSessionId(data.session_id);
      setExcelColumns(data.excel_columns);
      setExcelPreview(data.excel_preview);
      setTotalRows(data.total_rows);
      setPlaceholders(data.placeholders);
      setFilenameColumn(data.excel_columns[0] || "");
      setTemplateType(data.template_type);
      setOutputFormat("original");

      // Auto-map using LLM
      await autoMap(data);

      // Ask how to name/format documents before moving to review
      setShowSetupModal(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const autoMap = async (data: UploadResponse) => {
    try {
      const res = await fetch(`${API_URL}/api/map`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: data.session_id,
          excel_columns: data.excel_columns,
          placeholders: data.placeholders,
          excel_preview: data.excel_preview,
        }),
      });

      if (res.ok) {
        const mapData = await res.json();
        setMapping(mapData.mapping);
      } else {
        // Fallback: empty mapping
        const emptyMap: Record<string, string> = {};
        data.placeholders.forEach((p) => (emptyMap[p] = ""));
        setMapping(emptyMap);
      }
    } catch {
      const emptyMap: Record<string, string> = {};
      data.placeholders.forEach((p) => (emptyMap[p] = ""));
      setMapping(emptyMap);
    }

    setStep("review");
  };

  const closeSetupModal = useCallback(() => setShowSetupModal(false), []);

  const handleSkipSetup = useCallback(() => {
    setFilenameColumn("");
    setShowSetupModal(false);
  }, []);

  useEffect(() => {
    if (showSetupModal) {
      modalSelectRef.current?.focus();
    }
  }, [showSetupModal]);

  useEffect(() => {
    if (!showSetupModal) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeSetupModal();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [showSetupModal, closeSetupModal]);

  // ───── Generate ─────
  const handleGenerate = async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          mapping,
          row_index: rowIndex,
          filename_column: filenameColumn || undefined,
          output_format: outputFormat,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Generation failed");
      }

      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const nameMatch = disposition.match(/filename="([^"]+)"/);
      setGeneratedFilename(nameMatch ? nameMatch[1] : "filled_document");
      setGeneratedBlob(blob);
      setBulkResults(null); // clear any stale bulk-results view from a prior "Generate All Rows" run
      setStep("generate");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!generatedBlob) return;
    const url = URL.createObjectURL(generatedBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = generatedFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // ───── Bulk generate all rows ─────
  const handleGenerateAll = async () => {
    setBulkGenerating(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/api/generate-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          mapping,
          filename_column: filenameColumn || undefined,
          output_format: outputFormat,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Bulk generation failed");
      }

      const data = await res.json();
      setBulkResults(data.results);
      setStep("generate");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Bulk generation failed");
    } finally {
      setBulkGenerating(false);
    }
  };

  const handleDownloadResult = (result: BulkResult) => {
    if (!result.content_base64 || !result.filename || !result.mime_type) return;
    const binary = atob(result.content_base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: result.mime_type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = result.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleDownloadAll = async () => {
    if (!bulkResults) return;
    const zip = new JSZip();
    for (const r of bulkResults) {
      if (r.status === "ok" && r.content_base64 && r.filename) {
        zip.file(r.filename, r.content_base64, { base64: true });
      }
    }
    const blob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "filled_documents.zip";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleReset = () => {
    setStep("upload");
    setExcelFile(null);
    setTemplateFile(null);
    setSessionId("");
    setExcelColumns([]);
    setExcelPreview([]);
    setPlaceholders([]);
    setMapping({});
    setRowIndex(0);
    setGeneratedBlob(null);
    setGeneratedFilename("filled_document.pdf");
    setError(null);
    setShowSetupModal(false);
    setFilenameColumn("");
    setTemplateType("pdf");
    setOutputFormat("original");
    setBulkResults(null);
  };

  // ───── Stepper ─────
  const steps: { key: Step; label: string }[] = [
    { key: "upload", label: "Upload Files" },
    { key: "review", label: "Review Mapping" },
    { key: "generate", label: "Generate" },
  ];

  const stepIndex = steps.findIndex((s) => s.key === step);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <div className="header-badge">⚡ AI-Powered</div>
        <h1>DocFiller</h1>
        <p>
          Upload your Excel data and PDF template — AI maps the fields, you
          review, and get a perfectly filled document.
        </p>
      </header>

      {/* Stepper */}
      <div className="stepper">
        {steps.map((s, i) => (
          <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              className={`step-indicator ${i === stepIndex
                  ? "active"
                  : i < stepIndex
                    ? "completed"
                    : ""
                }`}
            >
              <div className="step-number">
                {i < stepIndex ? "✓" : i + 1}
              </div>
              <span className="step-label">{s.label}</span>
            </div>
            {i < steps.length - 1 && (
              <div
                className={`step-connector ${i < stepIndex ? "completed" : ""
                  }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="error-banner">
          <span>⚠️</span>
          <p>{error}</p>
        </div>
      )}

      {/* Setup modal — name (and eventually format) before generating */}
      {showSetupModal && (
        <div
          className="modal-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) closeSetupModal();
          }}
        >
          <div className="card" role="dialog" aria-modal="true" aria-label="Set up your documents">
            <h2 className="card-title">Set up your documents</h2>
            <p className="card-subtitle">
              Choose which column names each generated file
            </p>

            <div className="row-selector">
              <label htmlFor="filename-column-select">Document name from column:</label>
              <select
                id="filename-column-select"
                ref={modalSelectRef}
                className="mapping-select"
                value={filenameColumn}
                onChange={(e) => setFilenameColumn(e.target.value)}
              >
                {excelColumns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </div>
            <p className="preview-value">
              e.g. &quot;{previewFilename(excelPreview, filenameColumn, currentExt)}&quot;
            </p>

            {templateType === "word" ? (
              <div className="row-selector">
                <label htmlFor="format-select">Format:</label>
                <select
                  id="format-select"
                  className="mapping-select"
                  value={outputFormat}
                  onChange={(e) => setOutputFormat(e.target.value as OutputFormat)}
                >
                  <option value="original">Word ({templateExt}) — same as your template</option>
                  <option value="pdf">PDF</option>
                </select>
              </div>
            ) : (
              <p className="preview-value">Format: PDF — same as your template</p>
            )}

            <div className="actions actions-center">
              <button className="btn btn-primary" onClick={closeSetupModal}>
                Continue
              </button>
              <button className="btn btn-secondary" onClick={handleSkipSetup}>
                Skip
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 1: Upload */}
      {step === "upload" && (
        <div className="card">
          <h2 className="card-title">Upload Your Files</h2>
          <p className="card-subtitle">
            Drop your Excel data source and PDF template below
          </p>

          <div className="upload-grid">
            {/* Excel zone */}
            <div
              className={`upload-zone ${dragOver === "excel" ? "dragover" : ""
                } ${excelFile ? "has-file" : ""}`}
              onClick={() => excelInputRef.current?.click()}
              onDragOver={(e) => handleDragOver(e, "excel")}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, "excel")}
            >
              <span className="upload-icon">
                {excelFile ? "✅" : "📊"}
              </span>
              <div className="upload-label">
                {excelFile ? "File Selected" : "Excel Data Source"}
              </div>
              <div className="upload-hint">.xlsx, .xls, or .xlsm</div>
              {excelFile && (
                <div className="upload-filename">{excelFile.name}</div>
              )}
              <input
                ref={excelInputRef}
                type="file"
                accept=".xlsx,.xls,.xlsm"
                onChange={(e) => handleFileChange(e, "excel")}
              />
            </div>

            {/* Template zone */}
            <div
              className={`upload-zone ${dragOver === "template" ? "dragover" : ""
                } ${templateFile ? "has-file" : ""}`}
              onClick={() => templateInputRef.current?.click()}
              onDragOver={(e) => handleDragOver(e, "template")}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, "template")}
            >
              <span className="upload-icon">
                {templateFile ? "✅" : "📄"}
              </span>
              <div className="upload-label">
                {templateFile ? "File Selected" : "Document Template"}
              </div>
              <div className="upload-hint">
                .pdf with &lt;&lt;placeholders&gt;&gt; or .docx/.docm with «merge fields»
              </div>
              {templateFile && (
                <div className="upload-filename">{templateFile.name}</div>
              )}
              <input
                ref={templateInputRef}
                type="file"
                accept=".pdf,.docx,.docm"
                onChange={(e) => handleFileChange(e, "template")}
              />
            </div>
          </div>

          <div className="actions actions-center">
            <button
              className="btn btn-primary"
              disabled={!excelFile || !templateFile || loading}
              onClick={handleUpload}
            >
              {loading ? (
                <>
                  <span className="spinner" />
                  Processing...
                </>
              ) : (
                <>🚀 Upload & Analyze</>
              )}
            </button>
          </div>

          {loading && (
            <div className="status-bar">
              <div className="spinner" />
              <span className="status-text">
                Parsing files and mapping fields with AI...
              </span>
            </div>
          )}
        </div>
      )}

      {/* Step 2: Review Mapping */}
      {step === "review" && !showSetupModal && (
        <div className="card">
          <h2 className="card-title">Review Field Mapping</h2>
          <p className="card-subtitle">
            AI has suggested mappings below. Adjust any that need correction.
          </p>

          <div className="row-selector">
            <label>Excel Row:</label>
            <input
              type="number"
              min={0}
              max={totalRows - 1}
              value={rowIndex}
              onChange={(e) =>
                setRowIndex(Math.max(0, parseInt(e.target.value) || 0))
              }
            />
            <span>of {totalRows} rows (0-indexed)</span>
          </div>

          <div className="row-selector">
            <span>
              Naming documents by:{" "}
              <strong>{filenameColumn || "row number (default)"}</strong>
              {templateType === "word" && (
                <>
                  {" "}
                  · Format:{" "}
                  <strong>
                    {outputFormat === "pdf" ? "PDF" : `Word (${templateExt})`}
                  </strong>
                </>
              )}
            </span>
            <button
              className="btn btn-secondary"
              onClick={() => setShowSetupModal(true)}
            >
              Change
            </button>
          </div>

          <table className="mapping-table">
            <thead>
              <tr>
                <th>Template Placeholder</th>
                <th></th>
                <th>Excel Column</th>
              </tr>
            </thead>
            <tbody>
              {placeholders.map((ph) => (
                <tr key={ph}>
                  <td>
                    <div className="placeholder-name">
                      <span className="placeholder-tag">&lt;&lt;</span>
                      {ph}
                      <span className="placeholder-tag">&gt;&gt;</span>
                    </div>
                  </td>
                  <td className="mapping-arrow">→</td>
                  <td>
                    <select
                      className="mapping-select"
                      value={mapping[ph] || ""}
                      onChange={(e) =>
                        setMapping({ ...mapping, [ph]: e.target.value })
                      }
                    >
                      <option value="">— Select Column —</option>
                      {excelColumns.map((col) => (
                        <option key={col} value={col}>
                          {col}
                        </option>
                      ))}
                    </select>
                    {mapping[ph] && excelPreview[0] && (
                      <div className="preview-value">
                        Preview: {excelPreview[0][mapping[ph]] || "—"}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="actions">
            <button className="btn btn-secondary" onClick={handleReset}>
              ← Start Over
            </button>
            <button
              className="btn btn-success"
              disabled={loading || bulkGenerating}
              onClick={handleGenerate}
            >
              {loading ? (
                <>
                  <span className="spinner" />
                  Generating...
                </>
              ) : (
                <>✨ Generate Document</>
              )}
            </button>
            <button
              className="btn btn-primary"
              disabled={loading || bulkGenerating}
              onClick={handleGenerateAll}
            >
              {bulkGenerating ? (
                <>
                  <span className="spinner" />
                  Generating...
                </>
              ) : (
                <>📚 Generate All Rows ({totalRows})</>
              )}
            </button>
          </div>

          {loading && (
            <div className="status-bar">
              <div className="spinner" />
              <span className="status-text">
                {outputFormat === "pdf"
                  ? "Filling your template and converting to PDF..."
                  : "Filling your template with data..."}
              </span>
            </div>
          )}

          {bulkGenerating && (
            <div className="status-bar">
              <div className="spinner" />
              <span className="status-text">
                {outputFormat === "pdf"
                  ? `Generating and converting ${totalRows} documents to PDF…`
                  : `Generating ${totalRows} documents…`}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Download (single document) */}
      {step === "generate" && bulkResults === null && (
        <div className="card success-card">
          <span className="success-icon">🎉</span>
          <h2>Document Ready!</h2>
          <p>Your filled document has been generated successfully.</p>

          <div className="actions actions-center">
            <button className="btn btn-success" onClick={handleDownload}>
              📥 Download Document
            </button>
            <button className="btn btn-secondary" onClick={handleReset}>
              ↻ Fill Another
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Bulk results */}
      {step === "generate" && bulkResults !== null && (
        <div className="card">
          <h2 className="card-title">
            {bulkResults.filter((r) => r.status === "ok").length} of{" "}
            {bulkResults.length} documents generated
            {bulkResults.some((r) => r.status === "error") &&
              ` · ${bulkResults.filter((r) => r.status === "error").length} failed`}
          </h2>

          {bulkResults.some((r) => r.status === "error") && (
            <div className="error-banner">
              <span>⚠️</span>
              <p>Some documents failed to generate — see the table below.</p>
            </div>
          )}

          <div className="actions">
            <button
              className="btn btn-primary"
              onClick={handleDownloadAll}
              disabled={!bulkResults.some((r) => r.status === "ok")}
            >
              📦 Download All ({bulkResults.filter((r) => r.status === "ok").length})
            </button>
          </div>

          <table className="mapping-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {bulkResults.map((r) => (
                <tr key={r.row_index}>
                  <td>{r.filename || `Row ${r.row_index + 1}`}</td>
                  <td>
                    {r.status === "ok" ? (
                      <span className="preview-value">Ready</span>
                    ) : (
                      <span className="status-error">{r.error}</span>
                    )}
                  </td>
                  <td>
                    {r.status === "ok" && (
                      <button
                        className="btn btn-secondary"
                        onClick={() => handleDownloadResult(r)}
                      >
                        📥 Download
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="actions actions-center">
            <button
              className="btn btn-secondary"
              onClick={() => setStep("review")}
            >
              ← Back to Mapping
            </button>
            <button className="btn btn-secondary" onClick={handleReset}>
              ↻ Fill Another
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
