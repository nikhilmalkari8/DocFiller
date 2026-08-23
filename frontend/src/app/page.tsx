"use client";

import { useState, useRef, useCallback, DragEvent, ChangeEvent } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Step = "upload" | "review" | "generate";

interface UploadResponse {
  session_id: string;
  excel_columns: string[];
  excel_preview: Record<string, string>[];
  total_rows: number;
  placeholders: string[];
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

      // Auto-map using LLM
      await autoMap(data);
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
      {step === "review" && (
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
              disabled={loading}
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
          </div>

          {loading && (
            <div className="status-bar">
              <div className="spinner" />
              <span className="status-text">
                Filling your template with data...
              </span>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Download */}
      {step === "generate" && (
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
    </div>
  );
}
