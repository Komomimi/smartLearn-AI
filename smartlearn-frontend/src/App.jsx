import { useState, useCallback } from "react";
import PdfUploader from "./PdfUploader";
import PdfPreview from "./PdfPreview";
import ChatPanel from "./ChatPanel";


function App() {
  /* ── shared state ─────────────────────────────────────────────────── */
  const [upload, setUpload] = useState(null);        // upload success response
  const [activePage, setActivePage] = useState(1);   // current citation page
  const [uploadLoading, setUploadLoading] = useState(false);
  const [askLoading, setAskLoading] = useState(false);
  const [error, setError] = useState(null);
  const [previewKey, setPreviewKey] = useState(0);   // bumped on new upload

  const busy = uploadLoading || askLoading;

  /* ── page‑jump handler ────────────────────────────────────────────── */
  const handleJumpToPage = useCallback((page) => {
    setActivePage(page);
  }, []);

  /* ── upload success ───────────────────────────────────────────────── */
  const handleUploadSuccess = useCallback((data) => {
    setUpload(data);
    setError(null);
    setActivePage(1);
    setPreviewKey(Date.now());   // forces PdfPreview remount + ChatPanel reset
  }, []);

  return (
    <main>
      {/* ── header ──────────────────────────────────────────────────── */}
      <header className="app-header">
        <h1>SmartLearn AI</h1>
        <p>Upload a lecture PDF and ask questions</p>
      </header>

      {/* ── upload section ───────────────────────────────────────────── */}
      <PdfUploader
        busy={busy}
        currentUpload={upload}
        onSuccess={handleUploadSuccess}
        onError={(msg) => setError(msg)}
        onLoadingChange={(v) => setUploadLoading(v)}
      />

      {uploadLoading && (
        <div className="status-bar">
          <span className="status-spinner" />
          Uploading PDF…
        </div>
      )}
      {askLoading && (
        <div className="status-bar">
          <span className="status-spinner" />
          Asking AI…
        </div>
      )}

      {error && <div className="alert-error" role="alert">{error}</div>}

      {/* ── split layout: preview | chat ────────────────────────────── */}
      <div className="split-layout">
        <div className="split-left">
          <PdfPreview
            upload={upload}
            activePage={activePage}
            previewKey={previewKey}
          />
        </div>

        <div className="split-right">
          <ChatPanel
            key={previewKey}
            enabled={!!upload}
            disabled={busy}
            onBusy={(v) => setAskLoading(v)}
            onJumpToPage={handleJumpToPage}
          />
        </div>
      </div>
    </main>
  );
}

export default App;