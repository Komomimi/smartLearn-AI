import { useState, useEffect } from "react";
import { getSettings, saveSettings } from "./api";

export default function SettingsPanel({ onClose }) {
  const [embeddingModelPath, setEmbeddingModelPath] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);

  /* ── load current settings when the panel opens ──────── */
  useEffect(() => {
    getSettings()
      .then((s) => {
        setEmbeddingModelPath(s.embedding_model_path || "");
        setLlmApiKey(s.llm_api_key || "");
        setLlmBaseUrl(s.llm_base_url || "");
        setLlmModel(s.llm_model || "");
        setLoaded(true);
      })
      .catch(() => {
        setLoaded(true);
      });
  }, []);

  if (!loaded) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-card" onClick={(e) => e.stopPropagation()}>
          <p className="settings-hint">Loading settings…</p>
        </div>
      </div>
    );
  }

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    try {
      await saveSettings({
        embedding_model_path: embeddingModelPath.trim(),
        llm_api_key: llmApiKey.trim(),
        llm_base_url: llmBaseUrl.trim(),
        llm_model: llmModel.trim(),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore — the button just goes back to normal
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Settings"
      >
        <div className="modal-header">
          <h2>⚙ Settings</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <form onSubmit={handleSave}>
          {/* ── Embedding Model ──────────────────────────── */}
          <fieldset className="settings-fieldset">
            <legend>Embedding Model</legend>
            <label className="settings-label">
              Local model path (folder)
              <input
                type="text"
                className="settings-input"
                placeholder="Leave empty to auto-detect"
                value={embeddingModelPath}
                onChange={(e) => setEmbeddingModelPath(e.target.value)}
              />
            </label>
            <p className="settings-hint">
              e.g. C:\models\all-MiniLM-L6-v2<br />
              Must contain config_sentence_transformers.json and modules.json.
              Leave blank to use the built-in model.
            </p>
          </fieldset>

          {/* ── LLM ─────────────────────────────────────── */}
          <fieldset className="settings-fieldset">
            <legend>LLM (OpenAI-compatible API)</legend>

            <label className="settings-label">
              API Key
              <input
                type="password"
                className="settings-input"
                placeholder="sk-... (leave empty for Ollama)"
                value={llmApiKey}
                onChange={(e) => setLlmApiKey(e.target.value)}
              />
            </label>

            <label className="settings-label">
              API Base URL
              <input
                type="text"
                className="settings-input"
                placeholder="https://openrouter.ai/api/v1"
                value={llmBaseUrl}
                onChange={(e) => setLlmBaseUrl(e.target.value)}
              />
            </label>
            <p className="settings-hint">
              OpenRouter: https://openrouter.ai/api/v1<br />
              Ollama: http://localhost:11434/v1<br />
              LM Studio: http://localhost:1234/v1
            </p>

            <label className="settings-label">
              Model name
              <input
                type="text"
                className="settings-input"
                placeholder="google/gemma-4-26b-a4b-it:free"
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
              />
            </label>
            <p className="settings-hint">
              OpenRouter model ID (e.g. google/gemma-4-26b-a4b-it:free)
              or Ollama model (e.g. qwen2.5:7b, llama3.1:8b).
            </p>
          </fieldset>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={saving}
          >
            {saving ? "Saving…" : saved ? "✅ Saved!" : "Save Settings"}
          </button>
        </form>
      </div>
    </div>
  );
}
