import { useRef, useState, useEffect } from "react";
import { uploadPDF, getUploadStatus } from "./api";
import useLoading from "./useLoading";

/** Generate a unique chat session id (browser-native, no library needed). */
function newChatId() {
  return crypto.randomUUID();
}

const STEP_LABELS = {
  extracting: "提取文本中…",
  chunking: "文本分块中…",
  embedding: "生成向量嵌入中…",
  indexing: "构建搜索索引中…",
};

export default function PdfUploader({ busy, currentUpload, activeChatId, onSuccess, onError, onLoadingChange }) {
  const [file, setFile] = useState(null);
  const [replacing, setReplacing] = useState(false);
  const [loading, setLoadingAndReport] = useLoading(onLoadingChange);
  const inputRef = useRef(null);

  /* ── async processing state ──────────────────────────── */
  const [processingId, setProcessingId] = useState(null);  // chat_id being processed
  const [progressStep, setProgressStep] = useState(null);   // "extracting" | "chunking" | ...
  const [progressFilename, setProgressFilename] = useState("");

  const disabled = !file || busy || loading;

  /* ── poll upload status when processing ───────────────── */
  useEffect(() => {
    if (!processingId) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const info = await getUploadStatus(processingId);
        if (cancelled) return;
        if (info.step === "ready") {
          onSuccess(info);
          setProcessingId(null);
          setProgressStep(null);
          setProgressFilename("");
          setFile(null);
          setReplacing(false);
          setLoadingAndReport(false);
          if (inputRef.current) inputRef.current.value = "";
        } else if (info.step === "error") {
          onError(info.error || "Processing failed");
          setProcessingId(null);
          setProgressStep(null);
          setProgressFilename("");
          setLoadingAndReport(false);
        } else {
          setProgressStep(info.step);
          setProgressFilename(info.filename || "");
          setTimeout(poll, 800);  // poll every 800ms
        }
      } catch (err) {
        if (!cancelled) {
          onError("Failed to check processing status");
          setProcessingId(null);
          setProgressStep(null);
          setLoadingAndReport(false);
        }
      }
    };

    poll();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingId]);

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
      const chatId = currentUpload ? activeChatId : newChatId();
      const data = await uploadPDF(chatId, file);
      // Upload accepted — start polling for processing
      setProcessingId(data.chat_id);
      setProgressStep("extracting");
      setProgressFilename(data.filename);
    } catch (err) {
      onError(err.message);
      setLoadingAndReport(false);
    }
  };

  /* ── show progress bar when processing ────────────────── */
  if (processingId) {
    return (
      <div className="card">
        <span className="card-label">Processing — {progressFilename}</span>
        <div className="progress-track">
          <div className="progress-fill" />
        </div>
        <p className="progress-label">
          {STEP_LABELS[progressStep] || "处理中…"}
        </p>
      </div>
    );
  }

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
