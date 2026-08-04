import { useState, useCallback, useEffect } from "react";
import PdfUploader from "./PdfUploader";
import PdfPreview from "./PdfPreview";
import ChatPanel from "./ChatPanel";
import SessionTabs from "./SessionTabs";
import { listSessions, deleteSession, restoreSession, getSessionMessages } from "./api";

function App() {
  /* ── session state ───────────────────────────────────── */
  const [sessions, setSessions] = useState([]);        // list of {chat_id, filename, pages, characters}
  const [activeId, setActiveId] = useState(null);       // currently selected chat_id
  const [sessionMessages, setSessionMessages] = useState([]); // history for current session
  const [upload, setUpload] = useState(null);           // upload response for current session
  const [activePage, setActivePage] = useState(1);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [askLoading, setAskLoading] = useState(false);
  const [error, setError] = useState(null);
  const [previewKey, setPreviewKey] = useState(0);
  const [showUpload, setShowUpload] = useState(false);  // "New Upload" mode

  const busy = uploadLoading || askLoading;

  /* ── load session list on mount ───────────────────────── */
  useEffect(() => {
    let cancelled = false;
    listSessions()
      .then((data) => {
        if (!cancelled && data.length > 0) {
          setSessions(data);
          setActiveId(data[0].chat_id);
        } else if (!cancelled) {
          setShowUpload(true);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  /* ── when activeId changes, restore the session ──────── */
  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    setError(null);
    setUploadLoading(true);
    restoreSession(activeId)
      .then((data) => {
        if (!cancelled) {
          setUpload(data);
          setActivePage(1);
          setPreviewKey(Date.now());
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setUploadLoading(false);
      });

    getSessionMessages(activeId)
      .then((msgs) => {
        if (!cancelled) setSessionMessages(msgs);
      })
      .catch(() => {});

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  /* ── handlers ──────────────────────────────────────────── */
  const selectSession = useCallback((chatId) => {
    if (chatId !== activeId) setActiveId(chatId);
  }, [activeId]);

  const handleDeleteSession = useCallback(async (chatId) => {
    if (busy) return;
    setError(null);
    try {
      await deleteSession(chatId);
    } catch (err) {
      setError(err.message);
      return;
    }
    setSessions((prev) => {
      const next = prev.filter((s) => s.chat_id !== chatId);
      if (chatId === activeId) {
        if (next.length > 0) {
          setActiveId(next[0].chat_id);
        } else {
          setActiveId(null);
          setUpload(null);
          setSessionMessages([]);
          setShowUpload(true);
        }
      }
      return next;
    });
  }, [activeId, busy]);

  const handleUploadSuccess = useCallback((data) => {
    // data comes from getUploadStatus polling — it's {step:"ready", chat_id, filename, pages, characters}
    setUpload(data);
    setError(null);
    setActivePage(1);
    setPreviewKey(Date.now());
    setShowUpload(false);
    setSessions((prev) => {
      const exists = prev.some((s) => s.chat_id === data.chat_id);
      if (exists) {
        return prev.map((s) =>
          s.chat_id === data.chat_id
            ? { ...s, filename: data.filename, pages: data.pages, characters: data.characters }
            : s
        );
      }
      return [{ chat_id: data.chat_id, filename: data.filename, pages: data.pages, characters: data.characters }, ...prev];
    });
    setActiveId(data.chat_id);
  }, []);

  const handleJumpToPage = useCallback((page) => {
    setActivePage(page);
  }, []);

  return (
    <main>
      {/* ── header ───────────────────────────────────── */}
      <header className="app-header">
        <h1>SmartLearn AI</h1>
        <p>Upload a lecture PDF and ask questions</p>
      </header>

      {/* ── session tabs ─────────────────────────────── */}
      {sessions.length > 0 && (
        <SessionTabs
          sessions={sessions}
          activeId={activeId}
          onSelect={selectSession}
          onDelete={handleDeleteSession}
          onNewUpload={() => {
            setShowUpload(true);
            setError(null);
          }}
          loading={busy}
        />
      )}

      {/* ── upload section (conditionally shown) ──────── */}
      {(showUpload || sessions.length === 0) && (
        <PdfUploader
          busy={busy}
          currentUpload={showUpload ? null : upload}
          activeChatId={activeId}
          onSuccess={handleUploadSuccess}
          onError={(msg) => setError(msg)}
          onLoadingChange={(v) => setUploadLoading(v)}
        />
      )}

      {uploadLoading && (
        <div className="status-bar">
          <span className="status-spinner" />
          Loading session...
        </div>
      )}
      {askLoading && (
        <div className="status-bar">
          <span className="status-spinner" />
          Asking AI...
        </div>
      )}

      {error && <div className="alert-error" role="alert">{error}</div>}

      {/* ── split layout ─────────────────────────────── */}
      {activeId && (
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
              key={activeId}
              chatId={activeId}
              enabled={!!upload}
              disabled={busy}
              onBusy={(v) => setAskLoading(v)}
              onJumpToPage={handleJumpToPage}
            />
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
