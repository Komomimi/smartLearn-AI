# SmartLearn AI 📚🤖

<div align="center">

**AI-powered learning assistant that parses PDF lecture slides and answers your course-related questions using RAG (Retrieval-Augmented Generation).**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-blue.svg)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-7-purple.svg)](https://vitejs.dev/)
[![FAISS](https://img.shields.io/badge/FAISS-semantic%20search-orange.svg)](https://github.com/facebookresearch/faiss)

</div>

---

## 🎯 What It Does

Upload your lecture PDFs and ask questions in natural language. SmartLearn retrieves the most relevant sections from the document and generates grounded, page-cited answers — no more searching through dozens of slides.

| Upload a PDF | Ask questions | Get cited answers |
|---|---|---|

## ✨ Features

- **📄 Smart PDF Processing** — Upload lecture slides and get text extracted, chunked, and embedded automatically with real-time progress updates.
- **🔍 RAG-Powered Answers** — Uses FAISS vector search with hybrid retrieval (semantic similarity + lexical re-ranking) to find the most relevant content.
- **🤖 Flexible LLM Backend** — Works with any OpenAI-compatible API: OpenRouter (free models), Ollama (local models), LM Studio, or your own deployment.
- **🧩 Four Chunking Strategies** — Paragraph-based, character-window, sliding-window with overlap, and LangChain recursive splitting — pick what works best for your documents.
- **📑 Multi-Session Management** — Work with multiple PDFs simultaneously; each session keeps independent chat history.
- **💬 Multi-Turn Conversations** — Full chat history with citations that link back to specific PDF pages.
- **🎯 Page-Level Citations** — Every answer includes clickable page references that jump the PDF preview to the exact source.
- **⚙️ User-Configurable Settings** — Switch models, API keys, and embedding paths from the UI without touching config files.
- **💾 Persistent Storage** — Sessions, messages, and settings are saved in SQLite — your work survives restarts.
- **🌙 Dark UI** — Clean, modern dark-themed interface.

## 🏗️ Architecture

```
smartLearn-AI/
├── smartlearn-backend/          # Python FastAPI server
│   ├── main.py                  # API routes (upload, chat, sessions, settings)
│   ├── services/
│   │   ├── rag.py               # RAG pipeline — PDF extraction, chunking,
│   │   │                        #   embedding, FAISS index, retrieval, answering
│   │   ├── llm.py               # OpenRouter LLM client (legacy)
│   │   ├── database.py          # SQLite persistence layer
│   │   ├── config_loader.py     # DB → env → default config resolution
│   │   └── pdf.py               # PDF text extraction
│   ├── data/                    # SQLite database
│   ├── uploads/                 # Uploaded PDFs
│   └── artifacts/               # Cached chunks, embeddings, FAISS indexes
│
├── smartlearn-frontend/         # React + Vite SPA
│   └── src/
│       ├── App.jsx              # Root component, layout, session orchestration
│       ├── PdfUploader.jsx      # PDF upload with async progress polling
│       ├── PdfPreview.jsx       # PDF viewer with page-jump support
│       ├── ChatPanel.jsx        # Multi-turn chat with citations & sources
│       ├── SessionTabs.jsx      # Multi-session tab bar
│       ├── SettingsPanel.jsx    # Settings modal (LLM, embedding model)
│       ├── api.js               # API client module
│       └── index.css            # Global styles (dark theme)
│
└── .env.example                 # Environment variable template
```

### Data Flow

```
PDF Upload → Text Extraction → Chunking → Sentence Embedding
                                                  ↓
User Question → Query Embedding → FAISS Search → Lexical Re-rank
                                                  ↓
                          Retrieved Chunks + History → LLM → Cited Answer
                                                  ↓
                                          Answer stored in SQLite
```

## 🚀 Getting Started

### Prerequisites

- **Python 3.10+** with `pip`
- **Node.js 18+** with `npm`
- (Optional) A local embedding model to avoid downloading from HuggingFace on first run

### 1. Clone & Setup Backend

```bash
cd smartLearn-AI

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r smartlearn-backend/requirements.txt
pip install sentence-transformers faiss-cpu numpy
```

> **Note:** `sentence-transformers` and `faiss-cpu` are needed for local embedding and vector search.

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
OPENROUTER_API_KEY=sk-or-v1-your_key_here   # Get from https://openrouter.ai/keys
ALLOWED_ORIGINS=http://localhost:5173
```

> You can skip the API key and configure everything later from the UI settings panel.

### 3. Start Backend

```bash
cd smartlearn-backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API docs available at http://localhost:8000/docs.

### 4. Setup & Start Frontend

```bash
cd smartlearn-frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

## 🔧 Using Different LLM Providers

SmartLearn supports any OpenAI-compatible API. Configure from the ⚙ Settings panel in the UI:

| Provider | Base URL | Example Model |
|---|---|---|
| **OpenRouter** | `https://openrouter.ai/api/v1` | `google/gemma-4-26b-a4b-it:free` |
| **Ollama (local)** | `http://localhost:11434/v1` | `llama3.1:8b` / `qwen2.5:7b` |
| **LM Studio (local)** | `http://localhost:1234/v1` | (auto-detected) |

For **Ollama**, leave the API key blank — it runs locally without authentication.

### First-Run Model Download

On the first run with a new embedding model, `sentence-transformers` will download it from HuggingFace (~100 MB for `all-MiniLM-L6-v2`). To use a pre-downloaded model, set the path in Settings.

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/upload?chat_id=...` | Upload a PDF (returns immediately, processes in background) |
| `GET` | `/upload/{chat_id}/status` | Poll processing progress |
| `POST` | `/chat` | Ask a question about the uploaded document |
| `GET` | `/sessions` | List all saved sessions |
| `GET` | `/sessions/{chat_id}/messages` | Load chat history for a session |
| `DELETE` | `/sessions/{chat_id}` | Delete a session |
| `POST` | `/sessions/{chat_id}/restore` | Restore a session into memory |
| `GET` | `/settings` | Get current settings |
| `PUT` | `/settings` | Update settings |
| `GET` | `/documents/{chat_id}/file` | Serve the uploaded PDF |
| `GET` | `/health` | Health check |

## 🧪 RAG Pipeline Details

### Chunking Modes

| Mode | Description | Best For |
|---|---|---|
| `paragraph` | Splits on blank lines; overflow uses natural word/sentence breaks | Well-structured lecture slides |
| `character` | Fixed-size windows, no overlap | Simple baseline |
| `character_overlap` | Sliding windows with configurable overlap (default 120 chars) | Dense technical content |
| `langchain_recursive` | Recursive split on `\n\n` → `\n` → ` ` → char | Messy PDFs with weak structure |

### Retrieval

- **Embedding**: Sentence-transformers (`all-MiniLM-L6-v2` by default, configurable)
- **Vector Search**: FAISS IndexFlatIP (inner product = cosine similarity on normalized vectors)
- **Re-ranking**: Lexical overlap bonus — keyword intersection boosts semantically similar chunks that share exact terminology
- **Candidate Pool**: Fetches top 60 from FAISS, re-ranks, returns top 3

## 📝 Tech Stack

### Backend
- **FastAPI** — REST API framework
- **PyPDF** — PDF text extraction
- **Sentence-Transformers** — Local embedding models
- **FAISS** — Facebook AI Similarity Search
- **OpenAI SDK** — LLM client (OpenRouter / Ollama / any compatible API)
- **SQLite** — Persistence (sessions, messages, settings)
- **LangChain Text Splitters** — Advanced recursive chunking

### Frontend
- **React 19** — UI framework
- **Vite 7** — Build tool
- **CSS Custom Properties** — Theming (no CSS framework dependency)

## 🤝 Contributing

Contributions are welcome! Please follow the project conventions:

- API keys stay in `.env` — never commit them
- Use virtual environments for Python dependencies
- Commit messages follow: `type: description` (`feat`, `fix`, `docs`, `refactor`)

## 📄 License

This project is for educational purposes.

---

<div align="center">

**Built with Python, React, and ❤️**

</div>
