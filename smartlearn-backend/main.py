import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel, Field

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from fastapi.middleware.cors import CORSMiddleware

from services.llm import answer_from_pages
from services.pdf import extract_pages
from services.rag import extract_pages_for_rag, prepare_rag_document, answer_chat_turn
from services import database

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

    # ── save PDF to disk ──────────────────────────────────────────────
    saved_pdf_path = UPLOADS_DIR / f"{chat_id}.pdf"
    saved_pdf_path.write_bytes(pdf_bytes)

    # ── extract pages (no 30‑page limit, rag‑grade cleaning) ──────────
    try:
        pages = extract_pages_for_rag(pdf_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))

    characters = sum(len(p["text"]) for p in pages)
    if characters == 0:
        raise HTTPException(422, "No readable text found — OCR is not supported")

    # ── build the rich Day‑3 RAG record ───────────────────────────────
    filename = file.filename or "uploaded.pdf"
    try:
        rag_bundle = prepare_rag_document(
            document_id=chat_id,
            filename=filename,
            pages=pages,
        )
    except Exception:
        raise HTTPException(500, "Failed to prepare the document for RAG. Please try again.")

    # Shape expected by the rag.py retrieval functions (search_document, answer_document):
    #   document["artifacts"] = {"index": ..., "chunks": ..., "embeddings": ...}
    #   document["model_name"] = ...
    #   document["model_source"] = ...
    # Also keep the keys that Lab C notebook and the frontend need:
    #   saved_pdf_path, file_path, filename, pages, chunks, history, chat_id
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

    # ── persist to SQLite ───────────────────────────────────────────────
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

    return {
        "status": "ok",
        "chat_id": chat_id,
        "filename": filename,
        "pages": len(pages),
        "characters": characters,
    }


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