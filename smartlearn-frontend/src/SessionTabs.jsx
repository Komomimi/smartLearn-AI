export default function SessionTabs({ sessions, activeId, onSelect, onDelete, onNewUpload, loading }) {
  return (
    <div className="session-tabs-bar">
      {sessions.map((s) => {
        const isActive = s.chat_id === activeId;
        return (
          <button
            key={s.chat_id}
            className={`session-tab${isActive ? " active" : ""}`}
            onClick={() => onSelect(s.chat_id)}
            title={s.filename}
          >
            <span className="session-tab-name">{s.filename}</span>
            <span className="session-tab-meta">{s.pages}p</span>
            {!loading && (
              <span
                className="session-tab-close"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.chat_id);
                }}
                title="Delete session"
              >
                ×
              </span>
            )}
          </button>
        );
      })}

      <button
        className="session-tab session-tab-new"
        onClick={onNewUpload}
        disabled={loading}
      >
        + New Upload
      </button>
    </div>
  );
}
