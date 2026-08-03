import { API } from "./api";

/**
 * Build the backend URL that serves the uploaded PDF for a chat session.
 *
 * The returned URL has the form ``/documents/{chatId}/file#page={page}``
 * so the browser's built-in PDF viewer jumps directly to the cited page
 * when the ``activePage`` prop changes.
 */
export function getDocumentFileURL(chatId, page = 1) {
  return `${API}/documents/${encodeURIComponent(chatId)}/file#page=${page}`;
}

export default function PdfPreview({ upload, activePage, previewKey }) {
  /* ── empty state ─────────────────────────────────────────────────── */
  if (!upload) {
    return (
      <div className="card pdf-preview-card">
        <span className="card-label">PDF Preview</span>
        <div className="pdf-placeholder">
          <span className="pdf-placeholder-icon">📄</span>
          <span className="pdf-placeholder-text">
            Upload a PDF to preview it here
          </span>
        </div>
      </div>
    );
  }

  /* ── derive URL ──────────────────────────────────────────────────── */
  const chatId = upload.chat_id || "day2-demo";
  const page = activePage ?? 1;

  return (
    <div className="card pdf-preview-card">
      <span className="card-label">
        PDF Preview — {upload.filename ?? chatId}
      </span>
      <div className="pdf-iframe-wrap">
        <iframe
          key={`${previewKey}-p${page}`}
          src={getDocumentFileURL(chatId, page)}
          className="pdf-iframe"
          title="Uploaded PDF preview"
        />
      </div>
    </div>
  );
}
