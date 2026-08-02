import { useState } from "react";
import PdfUploader from "./PdfUploader";
import ChatPanel from "./ChatPanel";

function App() {
  const [upload, setUpload] = useState(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [askLoading, setAskLoading] = useState(false);
  const [error, setError] = useState(null);

  const busy = uploadLoading || askLoading;

  return (
    <main>
      <header className="app-header">
        <h1>SmartLearn AI</h1>
        <p>Upload a lecture PDF and ask questions</p>
      </header>

      <PdfUploader
        busy={busy}
        currentUpload={upload}
        onSuccess={(data) => { setUpload(data); setError(null); }}
        onError={(msg) => setError(msg)}
        onLoadingChange={(v) => setUploadLoading(v)}
      />

      {uploadLoading && <div className="status-bar"><span className="status-spinner" />Uploading PDF…</div>}
      {askLoading && <div className="status-bar"><span className="status-spinner" />Asking AI…</div>}

      {error && <div className="alert-error" role="alert">{error}</div>}

      <div className="divider" />

      <ChatPanel
        key={upload?.filename ?? "pending"}
        uploaded={!!upload}
        busy={busy}
        onLoadingChange={(v) => setAskLoading(v)}
        onError={(msg) => setError(msg)}
      />
    </main>
  );
}

export default App;