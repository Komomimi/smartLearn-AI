import { useRef, useState } from "react";
import { uploadPDF } from "./api";
import useLoading from "./useLoading";

export default function PdfUploader({ busy, currentUpload, onSuccess, onError, onLoadingChange }) {
  const [file, setFile] = useState(null);
  const [replacing, setReplacing] = useState(false);
  const [loading, setLoadingAndReport] = useLoading(onLoadingChange);
  const inputRef = useRef(null);

  const disabled = !file || busy || loading;

  const handleFileChange = (e) => {
    const f = e.target.files?.[0] || null;
    if (!f) return;
    setFile(f);
    setReplacing(true);
    onError(null);
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) return;
    onError(null);
    setLoadingAndReport(true);
    try {
      const data = await uploadPDF(file);
      onSuccess(data);
      setFile(null);
      setReplacing(false);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      onError(err.message);
    } finally {
      setLoadingAndReport(false);
    }
  };

  const showForm = !currentUpload || replacing;

  return (
    <div className="card">
      <span className="card-label">Step 1 — Upload PDF</span>

      {showForm ? (
        <form onSubmit={handleUpload}>
          <div
            className={`drop-zone${file ? " has-file" : ""}`}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
          >
            <span className="drop-zone-icon">{file ? "✅" : "📁"}</span>
            {file ? (
              <span className="drop-zone-filename">{file.name}</span>
            ) : (
              <span className="drop-zone-text">Click to select a PDF file</span>
            )}
          </div>

          <button type="submit" className="btn btn-primary" disabled={disabled}>
            {loading ? "Uploading…" : "Upload PDF"}
          </button>
        </form>
      ) : (
        <>
          <div className="drop-zone has-file" style={{ marginBottom: "0.75rem" }}>
            <span className="drop-zone-icon">✅</span>
            <span className="drop-zone-filename">{currentUpload.filename}</span>
            <span className="drop-zone-text" style={{ fontSize: "0.78rem" }}>
              {currentUpload.pages} pages · {currentUpload.characters.toLocaleString()} chars
            </span>
          </div>
          <button
            className="btn btn-secondary"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            style={{ width: "100%" }}
          >
            Replace PDF
          </button>
        </>
      )}

      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        className="file-input-hidden"
        onChange={handleFileChange}
      />
    </div>
  );
}
