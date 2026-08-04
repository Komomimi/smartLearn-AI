export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const FRIENDLY = {
  400: "The file could not be processed. Please check your PDF and try again.",
  404: "No PDF uploaded yet. Please upload a PDF before asking questions.",
  422: "No readable text found in this PDF — scanned images or OCR-only files are not supported.",
  502: "AI service is temporarily unavailable. Please wait a moment and try again.",
};

async function readJSON(response) {
  if (response.ok) return response.json();

  const body = await response.json().catch(() => ({}));
  const detail = FRIENDLY[response.status] || body.detail || `Request failed (${response.status})`;

  // Flatten Pydantic array errors into a single readable line
  if (Array.isArray(detail)) {
    const messages = detail.map((e) => e.msg || JSON.stringify(e)).join("; ");
    throw new Error(messages);
  }
  throw new Error(detail);
}

// ── Sessions ───────────────────────────────────────────────

export async function listSessions() {
  const response = await fetch(`${API}/sessions`);
  return readJSON(response);
}

export async function getSessionMessages(chatId) {
  const response = await fetch(`${API}/sessions/${encodeURIComponent(chatId)}/messages`);
  return readJSON(response);
}

export async function deleteSession(chatId) {
  const response = await fetch(`${API}/sessions/${encodeURIComponent(chatId)}`, { method: "DELETE" });
  return readJSON(response);
}

export async function restoreSession(chatId) {
  const response = await fetch(`${API}/sessions/${encodeURIComponent(chatId)}/restore`, { method: "POST" });
  return readJSON(response);
}

// ── Upload & Chat ──────────────────────────────────────────

export async function uploadPDF(chatId, file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(
    `${API}/upload?chat_id=${encodeURIComponent(chatId)}`,
    { method: "POST", body: formData },
  );
  return readJSON(response);
}

export async function askQuestion(chatId, message) {
  const response = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, chat_id: chatId }),
  });
  return readJSON(response);
}
