import { useState } from "react";
import { askQuestion } from "./api";


/** One chat turn — a user question paired with the assistant response. */
function MessageBubble({ turn, onJumpToPage }) {
  return (
    <div className="msg-turn">
      {/* ── user bubble ─────────────────────────────────────────── */}
      <div className="msg-user">
        <span className="msg-role">You</span>
        <p className="msg-text">{turn.question}</p>
      </div>

      {/* ── assistant bubble ────────────────────────────────────── */}
      <div className="msg-assistant">
        <span className="msg-role">SmartLearn</span>
        <p className="msg-text answer-body">{turn.answer}</p>

        {/* citations */}
        {turn.citations?.length > 0 && (
          <div className="citations-row">
            <span className="citations-label">Sources</span>
            {turn.citations.map((page) => (
              <button
                key={page}
                className="chip chip-btn"
                type="button"
                onClick={() => onJumpToPage(page)}
              >
                📌 Page {page}
              </button>
            ))}
          </div>
        )}

        {/* sources preview */}
        {turn.sources?.length > 0 && (
          <details className="sources-details">
            <summary className="sources-summary">
              {turn.sources.length} source{turn.sources.length !== 1 ? "s" : ""}
            </summary>
            <ol className="sources-list">
              {turn.sources.map((s, i) => (
                <li key={i}>
                  <span className="src-page">p.{s.page}</span>
                  <span className="src-score">
                    {s.score?.toFixed(3)}
                  </span>
                  <p className="src-preview">{s.preview}</p>
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
    </div>
  );
}


export default function ChatPanel({ enabled, onBusy, disabled, onJumpToPage }) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  /* ── derived flags ────────────────────────────────────────────────── */
  const blocked = !enabled || !message.trim() || disabled || loading;

  const handleAsk = async (e) => {
    e.preventDefault();
    const question = message.trim();
    if (!question) return;

    setLoading(true);
    onBusy?.(true);
    setError(null);
    setMessage("");

    try {
      const data = await askQuestion(question);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          question,
          answer: data.answer,
          citations: data.citations ?? [],
          sources: data.sources ?? [],
        },
      ]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      onBusy?.(false);
    }
  };

  return (
    <section className="chat-panel">
      {/* ── message list ─────────────────────────────────────────── */}
      {messages.length > 0 && (
        <div className="msg-list">
          {messages.map((turn) => (
            <MessageBubble
              key={turn.id}
              turn={turn}
              onJumpToPage={onJumpToPage}
            />
          ))}
        </div>
      )}

      {/* ── error ────────────────────────────────────────────────── */}
      {error && <div className="alert-error" role="alert">{error}</div>}

      {/* ── input form ───────────────────────────────────────────── */}
      <form onSubmit={handleAsk} className="card">
        <label htmlFor="message-input" className="card-label">
          Ask a question
        </label>
        <textarea
          id="message-input"
          className="textarea"
          rows={4}
          placeholder={enabled ? "e.g. What is a knowledge graph?" : "Upload a PDF first to ask questions"}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleAsk(e);
            }
          }}
          disabled={!enabled}
        />
        <button type="submit" className="btn btn-primary" disabled={blocked}>
          {loading ? "Thinking…" : "Ask Question"}
        </button>
      </form>
    </section>
  );
}
