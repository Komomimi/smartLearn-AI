import { useState } from "react";
import { askQuestion } from "./api";
import useLoading from "./useLoading";

export default function ChatPanel({ uploaded, busy, onLoadingChange, onError }) {
  const [message, setMessage] = useState("");
  const [loading, setLoadingAndReport] = useLoading(onLoadingChange);
  const [answer, setAnswer] = useState(null);

  const disabled = !uploaded || !message.trim() || busy || loading;

  const handleAsk = async (e) => {
    e.preventDefault();
    const trimmed = message.trim();
    if (!trimmed) return;
    setLoadingAndReport(true);
    onError(null);
    try {
      const data = await askQuestion(trimmed);
      setAnswer(data);
    } catch (err) {
      onError(err.message);
    } finally {
      setLoadingAndReport(false);
    }
  };

  return (
    <>
      <form onSubmit={handleAsk} className="card">
        <label htmlFor="message-input" className="card-label">Step 2 — Ask a question</label>
        <textarea
          id="message-input"
          className="textarea"
          rows={4}
          placeholder={uploaded ? "e.g. What is the main topic of this lecture?" : "Upload a PDF first to ask questions"}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          disabled={!uploaded}
        />
        <button type="submit" className="btn btn-primary" disabled={disabled}>
          {loading ? "Thinking…" : "Ask Question"}
        </button>
      </form>

      {answer && (
        <div className="card">
          <span className="card-label">Answer</span>
          <p className="answer-body">{answer.answer}</p>
          {answer.citations?.length > 0 && (
            <div className="citations-row">
              <span className="citations-label">Sources</span>
              {answer.citations.map((n) => (
                <span className="chip" key={n}>📌 Page {n}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
