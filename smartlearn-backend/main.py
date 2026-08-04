import os
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel, Field

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from fastapi.middleware.cors import CORSMiddleware

from services.llm import answer_from_pages  # noqa: F401 — kept for Day 2 compatibility
from services.pdf import extract_pages  # noqa: F401 — kept for Day 2 compatibility
from services.rag import extract_pages_for_rag, prepare_rag_document, answer_chat_turn
from services import database
from services.config_loader import get_llm_config, get_embedding_model_source

app = FastAPI(title="SmartLearn Lite API")

# ── initialise SQLite ─────────────────────────────────────────────────
database.init_db()

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Accept"],
)

documents: dict[str, dict] = {}
processing_status: dict[str, dict] = {}   # chat_id → {step, error, filename, pages, characters}

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


class ChatRequest(BaseModel):
    chat_id: str = "day2-demo"
    message: str = Field(..., min_length=2, max_length=2000)


@app.get("/")
def root():
    return {"message": "SmartLearn Lite API is running"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/upload")
async def upload(
    chat_id: str = Query(...),
    file: UploadFile = File(...),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")
    if file.size is not None and file.size == 0:
        raise HTTPException(400, "File must not be empty")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "File must not be empty")

    # ── save PDF to disk (fast — done synchronously) ──────────────────
    saved_pdf_path = UPLOADS_DIR / f"{chat_id}.pdf"
    saved_pdf_path.write_bytes(pdf_bytes)
    filename = file.filename or "uploaded.pdf"

    # ── mark as processing and return immediately ─────────────────────
    processing_status[chat_id] = {"step": "extracting", "filename": filename}

    def _process_in_background():
        """Run the heavy RAG pipeline in a background thread."""
        try:
            # ── extract pages ────────────────────────────────────────
            processing_status[chat_id] = {"step": "extracting", "filename": filename}
            pages = extract_pages_for_rag(pdf_bytes)
            characters = sum(len(p["text"]) for p in pages)
            if characters == 0:
                processing_status[chat_id] = {"step": "error", "error": "No readable text found — OCR is not supported", "filename": filename}
                return

            processing_status[chat_id] = {"step": "chunking", "filename": filename, "pages": len(pages)}

            # ── build RAG bundle ─────────────────────────────────────
            processing_status[chat_id] = {"step": "embedding", "filename": filename, "pages": len(pages)}
            rag_bundle = prepare_rag_document(
                document_id=chat_id,
                filename=filename,
                pages=pages,
            )

            processing_status[chat_id] = {"step": "indexing", "filename": filename, "pages": len(pages)}

            # ── build in-memory record ───────────────────────────────
            record: dict[str, object] = {
                "saved_pdf_path": str(saved_pdf_path),
                "file_path": str(saved_pdf_path),
                "filename": filename,
                "pages": pages,
                "chunks": rag_bundle["chunks"],
                "history": [],
                "chat_id": chat_id,
                "artifacts": rag_bundle["artifacts"],
                "model_name": rag_bundle["model_name"],
                "model_source": rag_bundle.get("model_source", rag_bundle["model_name"]),
            }
            documents[chat_id] = record

            # ── persist to SQLite ────────────────────────────────────
            database.save_session(
                chat_id=chat_id,
                filename=filename,
                file_path=str(saved_pdf_path),
                pages=pages,
                characters=characters,
                model_name=str(rag_bundle["model_name"]),
                model_source=str(rag_bundle.get("model_source", rag_bundle["model_name"])),
                artifacts={k: str(v) for k, v in rag_bundle["artifacts"].items()},
            )

            processing_status[chat_id] = {
                "step": "ready",
                "filename": filename,
                "pages": len(pages),
                "characters": characters,
                "chat_id": chat_id,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            processing_status[chat_id] = {"step": "error", "error": str(e), "filename": filename}

    thread = threading.Thread(target=_process_in_background, daemon=True)
    thread.start()

    return {"status": "processing", "chat_id": chat_id, "filename": filename}


@app.get("/upload/{chat_id}/status")
def get_upload_status(chat_id: str):
    """Poll this endpoint to track background RAG pipeline progress.

    Returns ``{"step": "ready"}`` when the document is searchable,
    or ``{"step": "error", "error": "..."}`` on failure.
    Possible step values: extracting, chunking, embedding, indexing, ready, error.
    """
    info = processing_status.get(chat_id)
    if info is None:
        raise HTTPException(404, "Unknown upload — it may have been cleaned up")
    return info


@app.post("/chat")
def chat(body: ChatRequest):
    doc = documents.get(body.chat_id)
    if not doc:
        raise HTTPException(
            404,
            "No PDF uploaded yet. Please upload a PDF before asking questions.",
        )

    try:
        result = answer_chat_turn(document=doc, question=body.message)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(502, str(e))

    # ── persist message to SQLite ───────────────────────────────────────
    database.save_message(
        chat_id=body.chat_id,
        question=body.message,
        answer=result["answer"],
        citations=result.get("citations"),
        sources=result.get("sources"),
    )

    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "sources": result.get("sources", []),
    }


@app.get("/documents/{chat_id}/file")
def get_document_file(chat_id: str):
    """Serve the uploaded PDF so the frontend can show it in an iframe."""
    doc = documents.get(chat_id)
    if not doc:
        raise HTTPException(404, "No document found for this chat session.")

    file_path = Path(doc.get("saved_pdf_path", ""))
    if not file_path.exists():
        raise HTTPException(404, "Saved PDF file is missing.")

    return FileResponse(str(file_path), media_type="application/pdf")


# ── Session management routes ───────────────────────────────────────────


@app.get("/sessions")
def get_sessions():
    """List all saved sessions (newest first)."""
    return database.list_sessions()


@app.get("/sessions/{chat_id}/messages")
def get_session_messages(chat_id: str):
    """Load chat history for one session."""
    session = database.get_session(chat_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    return database.get_messages(chat_id)


@app.delete("/sessions/{chat_id}")
def delete_session(chat_id: str):
    """Delete a session and its messages."""
    if not database.delete_session(chat_id):
        raise HTTPException(404, "Session not found")
    # Also remove from in-memory store and disk files
    documents.pop(chat_id, None)
    for suffix in ("", ".faiss", ".faiss_meta.json", ".npy", ".json"):
        pass  # artifact cleanup is optional — don't block the response
    return {"ok": True}


@app.post("/sessions/{chat_id}/restore")
def restore_session(chat_id: str):
    """Restore a previously saved session back into in-memory documents."""
    session = database.get_session(chat_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    # Rebuild the in-memory document from SQLite, same shape as upload creates
    pages = session["pages"]
    artifacts = session["artifacts"]

    record: dict[str, object] = {
        "saved_pdf_path": session["file_path"],
        "file_path": session["file_path"],
        "filename": session["filename"],
        "pages": pages,
        "chunks": [],          # can't restore Python objects from JSON — will reload
        "history": [],
        "chat_id": chat_id,
        "artifacts": artifacts,
        "model_name": session.get("model_name", ""),
        "model_source": session.get("model_source", ""),
    }

    # Re-load chunks from disk (they were saved as JSON by prepare_rag_document)
    from services.rag import load_json, load_faiss_index
    chunks_path = artifacts.get("chunks")
    if chunks_path:
        record["chunks"] = load_json(chunks_path)

    documents[chat_id] = record
    database.get_messages(chat_id)  # warm — messages are served separately

    return {
        "chat_id": chat_id,
        "filename": session["filename"],
        "pages": len(pages),
        "characters": session["characters"],
    }


# ── Settings routes ──────────────────────────────────────────────────


@app.get("/settings")
def get_settings():
    """Return all user-configurable settings."""
    return {
        "embedding_model_path": database.get_setting("embedding_model_path", ""),
        "llm_api_key": database.get_setting("llm_api_key", ""),
        "llm_base_url": database.get_setting("llm_base_url", ""),
        "llm_model": database.get_setting("llm_model", ""),
    }


class SettingsRequest(BaseModel):
    embedding_model_path: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""


@app.put("/settings")
def update_settings(body: SettingsRequest):
    """Save user-configurable settings to the database."""
    database.set_setting("embedding_model_path", body.embedding_model_path)
    database.set_setting("llm_api_key", body.llm_api_key)
    database.set_setting("llm_base_url", body.llm_base_url)
    database.set_setting("llm_model", body.llm_model)
    return {"ok": True}