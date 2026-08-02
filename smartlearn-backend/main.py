import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel, Field

from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from fastapi.middleware.cors import CORSMiddleware

from services.llm import answer_from_pages
from services.pdf import extract_pages

app = FastAPI(title="SmartLearn Lite API")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)

documents: dict[str, list[dict]] = {}


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

    pages = extract_pages(pdf_bytes)

    characters = sum(len(p["text"]) for p in pages)
    if characters == 0:
        raise HTTPException(422, "No readable text found — OCR is not supported")

    documents[chat_id] = pages

    return {
        "status": "ok",
        "filename": file.filename,
        "pages": len(pages),
        "characters": characters,
    }


@app.post("/chat")
def chat(body: ChatRequest):
    pages = documents.get(body.chat_id)
    if not pages:
        raise HTTPException(
            404,
            f"No PDF uploaded for chat_id={body.chat_id!r}. "
            "Please upload a PDF via POST /upload?chat_id=<id> first.",
        )

    try:
        answer = answer_from_pages(pages, body.message)
    except Exception:
        raise HTTPException(502, "AI service unavailable")

    valid_pages = {p["page"] for p in pages}
    citations = sorted(
        int(n) for n in set(re.findall(r"\[Page\s+(\d+)\]", answer))
        if int(n) in valid_pages
    )

    return {"answer": answer, "citations": citations}