"""RAG helpers — text cleaning, PDF extraction, JSON persistence, and preview."""

from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Union

from pypdf import PdfReader

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Normalise one extracted page of PDF text.

    Removes null bytes, soft hyphens, repeated whitespace, and noisy
    line breaks so downstream chunking / embedding receives clean input.
    """
    if not text:
        return ""

    # Remove null bytes (sometimes appear in malformed PDF streams)
    text = text.replace("\x00", "")

    # Remove soft hyphens (U+00AD) — invisible hyphenation inserted by
    # word processors that becomes junk when extracted as plain text.
    text = text.replace("­", "")

    # Replace non-breaking space (U+00A0) with a regular space.
    text = text.replace(" ", " ")

    # Collapse runs of horizontal whitespace (spaces, tabs) into a single space.
    text = re.sub(r"[ \t]+", " ", text)

    # Collapse 3+ consecutive newlines into at most 2 (preserve at most one
    # blank line as a paragraph separator).
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip trailing whitespace on each line.
    text = re.sub(r"[ \t]+\n", "\n", text)

    # Strip leading whitespace on each line.
    text = re.sub(r"\n[ \t]+", "\n", text)

    return text.strip()


# ---------------------------------------------------------------------------
# PDF extraction (RAG-specific — no hard page limit)
# ---------------------------------------------------------------------------


def extract_pages_for_rag(source: Union[str, Path, bytes]) -> list[dict[str, object]]:
    """Read a PDF page-by-page and return *only* readable ``{page, text}`` records.

    - *source* may be raw PDF bytes, a ``str`` path, or a ``pathlib.Path``.
    - Page numbers are the original 1-based PDF page numbers.
    - Pages whose extracted text is empty after :func:`clean_text` are dropped.
    - No artificial page limit is enforced.
    """
    if isinstance(source, (str, Path)):
        pdf_bytes = Path(source).read_bytes()
    else:
        pdf_bytes = source
    reader = PdfReader(BytesIO(pdf_bytes))
    records: list[dict[str, object]] = []

    for page_number, page in enumerate(reader.pages, start=1):
        raw = page.extract_text()
        if raw is None:
            continue
        cleaned = clean_text(raw)
        if not cleaned:
            continue
        records.append({"page": page_number, "text": cleaned})

    return records


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------


def save_json(obj: Any, file_path: Union[str, Path]) -> None:
    """Save *obj* as a UTF-8 JSON file, creating parent folders when needed."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def load_json(file_path: Union[str, Path]) -> Any:
    """Read a saved JSON artifact and return the deserialised Python object."""
    with open(Path(file_path), "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Quick inspection
# ---------------------------------------------------------------------------


def preview_records(
    records: list[dict[str, object]],
    columns: list[str] | None = None,
    max_rows: int = 20,
) -> None:
    """Print a compact table of *records* so you can inspect page / chunk
    artifacts quickly in a notebook or terminal.

    Parameters
    ----------
    records:
        List of dicts (e.g. the return value of :func:`extract_pages_for_rag`).
    columns:
        Which keys to display.  Defaults to all keys of the first record.
    max_rows:
        Maximum number of rows to print before truncating.
    """
    if not records:
        print("(empty)")
        return

    if columns is None:
        columns = list(records[0].keys())

    # ── column widths ──────────────────────────────────────────────
    col_widths: dict[str, int] = {}
    for col in columns:
        header_w = len(str(col))
        data_w = max(
            (len(str(r.get(col, ""))) for r in records[:max_rows]),
            default=0,
        )
        col_widths[col] = max(header_w, data_w, 4) + 2  # 2-char gutter

    # ── header ─────────────────────────────────────────────────────
    header = "".join(f"{col:<{col_widths[col]}}" for col in columns)
    rule = "".join("-" * col_widths[col] for col in columns)
    print(header)
    print(rule)

    # ── body ───────────────────────────────────────────────────────
    for record in records[:max_rows]:
        row = "".join(
            f"{str(record.get(col, '')):<{col_widths[col]}}" for col in columns
        )
        print(row)

    if len(records) > max_rows:
        print(f"... ({len(records) - max_rows} more rows)")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# Natural split points in descending order of preference.
_NATURAL_BREAKS = [
    re.compile(r"\n(?=[^\n])"),   # single newline (soft break within paragraph)
    re.compile(r"\.(?=\s)"),      # sentence boundary
    re.compile(r"[。；](?=\S)"),   # CJK sentence / clause boundary
    re.compile(r"\s"),             # any whitespace (word boundary)
]


def slice_long_text(text: str, chunk_size: int) -> list[str]:
    """Split a single oversized text block into smaller pieces ≤ *chunk_size*.

    Prefers natural boundaries (newlines, sentence ends, whitespace) so that
    splits never land mid-word when a reasonable break exists.  Only falls
    back to a hard character cut when no natural boundary is found.
    """
    pieces: list[str] = []
    remaining = text

    while len(remaining) > chunk_size:
        # Try each natural-break pattern inside the allowed window.
        # Search *backwards* from chunk_size so we maximise content per piece.
        window = remaining[:chunk_size]
        split_at = -1

        for pattern in _NATURAL_BREAKS:
            # Find the last match inside the window.
            matches = list(pattern.finditer(window))
            if matches:
                # Take the rightmost match.
                split_at = matches[-1].end()
                break

        # Hard cut if no natural boundary found.
        if split_at <= 0:
            split_at = chunk_size

        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()

    if remaining:
        pieces.append(remaining.strip())

    return pieces


def chunk_by_paragraph(
    records: list[dict[str, object]],
    chunk_size: int,
    chunk_mode: str = "paragraph",
) -> list[dict[str, object]]:
    """Convert paragraph-level records into chunks, preserving page numbers
    and paragraph order.

    Paragraphs are separated by blank lines.  When a single paragraph exceeds
    *chunk_size* it is split via :func:`slice_long_text`.
    """
    chunks: list[dict[str, object]] = []
    chunk_id = 0

    for record in records:
        page = record["page"]
        text = str(record["text"])
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        for para in paragraphs:
            if len(para) <= chunk_size:
                chunk_id += 1
                chunks.append({
                    "chunk_id": f"c{chunk_id:04d}",
                    "page": page,
                    "text": para,
                    "chunk_mode": chunk_mode,
                })
            else:
                for piece in slice_long_text(para, chunk_size):
                    chunk_id += 1
                    chunks.append({
                        "chunk_id": f"c{chunk_id:04d}",
                        "page": page,
                        "text": piece,
                        "chunk_mode": chunk_mode,
                    })

    return chunks


def chunk_by_characters(
    records: list[dict[str, object]],
    chunk_size: int,
    overlap: int = 0,
    chunk_mode: str = "character",
) -> list[dict[str, object]]:
    """Create fixed-size sliding-window chunks, with optional *overlap*.

    When *overlap* is 0 each character appears in exactly one chunk (plain
    non-overlapping windows).  When *overlap* > 0 consecutive chunks share
    *overlap* characters of context; the chunk dict includes an ``overlap``
    field recording the overlap amount.
    """
    chunks: list[dict[str, object]] = []
    chunk_id = 0
    step = max(1, chunk_size - overlap)

    for record in records:
        page = record["page"]
        text = str(record["text"])
        start = 0

        while start < len(text):
            window = text[start : start + chunk_size]
            if not window:
                break
            chunk_id += 1
            entry: dict[str, object] = {
                "chunk_id": f"c{chunk_id:04d}",
                "page": page,
                "text": window,
                "chunk_mode": chunk_mode,
            }
            if overlap > 0:
                entry["overlap"] = overlap
            chunks.append(entry)

            if start + chunk_size >= len(text):
                break
            start += step

    return chunks


def build_chunks(
    records: list[dict[str, object]],
    chunk_mode: str = "paragraph",
    chunk_size: int = 500,
    overlap: int = 0,
) -> list[dict[str, object]]:
    """Select a chunking strategy and return a uniform list of chunk dicts.

    Parameters
    ----------
    records:
        Page records from :func:`extract_pages_for_rag`  (``[{page, text}, ...]``).
    chunk_mode:
        ``"paragraph"`` — split on paragraph boundaries with word-aware
        overflow handling.
        ``"character"`` — plain fixed-size windows, no overlap.
        ``"character_overlap"`` — fixed-size windows with *overlap* > 0.
    chunk_size:
        Maximum characters per chunk (all modes).
    overlap:
        Character overlap between consecutive windows  (only used by
        ``"character_overlap"`` mode).

    Returns
    -------
    list[dict]
        Each chunk has ``chunk_id``, ``page``, ``text``, and ``chunk_mode``.
    """
    if chunk_mode == "paragraph":
        return chunk_by_paragraph(records, chunk_size, chunk_mode=chunk_mode)

    if chunk_mode == "character":
        return chunk_by_characters(records, chunk_size, overlap=0, chunk_mode=chunk_mode)

    if chunk_mode == "character_overlap":
        if overlap <= 0:
            raise ValueError("character_overlap mode requires overlap > 0")
        return chunk_by_characters(records, chunk_size, overlap=overlap, chunk_mode=chunk_mode)

    raise ValueError(
        f"Unknown chunk_mode {chunk_mode!r}. "
        "Expected one of: paragraph, character, character_overlap."
    )


# ---------------------------------------------------------------------------
# Embedding pipeline
# ---------------------------------------------------------------------------


def model_tag(model_name: str) -> str:
    """Turn a model name into a safe filename suffix.

    ``"BAAI/bge-small-zh-v1.5"`` → ``"BAAI_bge-small-zh-v1.5"``.
    """
    return model_name.replace("/", "_").replace("\\", "_")


def resolve_model_source(
    model_name: str,
    artifact_root: str | Path = "artifacts",
    extra_search_dir: str | Path | None = None,
) -> str:
    """Prefer a local cached model folder when it already exists.

    1. If *model_name* itself is a path on disk that exists, return its
       resolved absolute path immediately.
    2. Derive a folder name via :func:`model_tag` and search these locations
       (in order):

       * ``<artifact_root>/hf_models/<tagged_name>/``
       * ``artifacts/rag/hf_models/<tagged_name>/``
       * ``<extra_search_dir>/<tagged_name>/`` (keyword argument)
       * ``<RAG_HF_MODELS_DIR>/<tagged_name>/`` (environment variable)

    3. If a folder is found *and* it contains both ``modules.json`` and
       ``config_sentence_transformers.json``, return its path.
    4. Otherwise return *model_name* unchanged.
    """
    import os as _os

    # 1. model_name itself is a local path.
    candidate = Path(model_name)
    if candidate.exists():
        return str(candidate.resolve())

    tagged = model_tag(model_name)
    # ModelScope downloads use only the base name (no org prefix).
    base_name = model_name.rsplit("/", 1)[-1]
    required_files = ("modules.json", "config_sentence_transformers.json")

    # 2. Build candidate full-paths.
    search_roots: list[Path] = []
    search_roots.append(Path(artifact_root) / "hf_models")
    search_roots.append(Path("artifacts") / "rag" / "hf_models")

    if extra_search_dir is not None:
        search_roots.append(Path(extra_search_dir))

    env_dir = _os.getenv("RAG_HF_MODELS_DIR")
    if env_dir:
        search_roots.append(Path(env_dir))

    for root in search_roots:
        # Try both the full tagged name and the bare base name.
        for candidate_name in (tagged, base_name):
            full = root / candidate_name
            if all((full / f).exists() for f in required_files):
                return str(full.resolve())

    return model_name


def get_device() -> str:
    """Choose ``"cuda"`` if a GPU is available, otherwise ``"cpu"``."""
    try:
        import torch  # type: ignore[import-untyped]
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model(model_name: str, device: str | None = None):
    """Create or reuse one sentence-transformer model instance.

    Parameters
    ----------
    model_name:
        HuggingFace model id or local path.
    device:
        ``"cpu"``, ``"cuda"``, or ``None`` (auto-detect via :func:`get_device`).
    """
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    if device is None:
        device = get_device()
    return SentenceTransformer(model_name, device=device)


def embed_texts(model, texts: list[str], batch_size: int = 32):
    """Encode a list of texts into normalised ``float32`` vectors.

    Parameters
    ----------
    model:
        A loaded sentence-transformer instance.
    texts:
        Strings to encode.
    batch_size:
        Number of texts to encode in each forward pass.
    """
    import numpy as np  # type: ignore[import-untyped]

    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return embeddings.astype(np.float32)


def artifact_paths_for(
    document_id: str,
    chunk_mode: str,
    model_name: str,
    chunk_size: int,
    artifact_root: str | Path = "artifacts",
) -> dict[str, Path]:
    """Decide file-system paths for all saved artifacts of one configuration.

    Returns a dict with keys ``root``, ``raw_pages``, ``chunks``,
    ``embeddings``, ``index``, and ``manifest``.
    """
    root = Path(artifact_root)
    tag = model_tag(model_name)
    stem = f"{document_id}_{chunk_mode}_c{chunk_size:04d}_m{tag}"

    return {
        "root": root,
        "raw_pages": root / f"{document_id}_raw_pages.json",
        "chunks": root / f"{stem}.json",
        "embeddings": root / f"{stem}.npy",
        "index": root / f"{stem}.faiss",
        "manifest": root / "manifest.json",
    }


def ensure_artifacts(
    document_id: str,
    pdf_name: str,
    pages: list[dict[str, object]],
    chunk_mode: str,
    model_name: str,
    chunk_size: int = 500,
    overlap: int = 0,
    batch_size: int = 32,
    artifact_root: str | Path = "artifacts",
) -> dict[str, object]:
    """Build or reuse the full pages → chunks → embeddings → manifest bundle.

    When a matching manifest entry already exists and every referenced file is
    present on disk the cached artifacts are returned immediately (with
    ``"reused": True``).  Otherwise the pipeline runs from scratch and
    overwrites the saved outputs.

    Returns a dict with keys ``pages``, ``chunks``, ``embeddings``,
    ``manifest``, ``paths``, and ``reused``.
    """
    import numpy as np  # type: ignore[import-untyped]

    paths = artifact_paths_for(
        document_id, chunk_mode, model_name, chunk_size, artifact_root
    )

    # ── config signature (deterministic JSON key) ───────────────────
    signature = {
        "document_id": document_id,
        "pdf_name": pdf_name,
        "chunk_mode": chunk_mode,
        "model_name": model_name,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "batch_size": batch_size,
    }
    config_key = json.dumps(signature, ensure_ascii=False, sort_keys=True)

    # ── try cache ───────────────────────────────────────────────────
    if paths["manifest"].exists():
        all_manifests = load_json(paths["manifest"])
        if config_key in all_manifests:
            entry = all_manifests[config_key]
            chunk_path = Path(entry["chunk_path"])
            emb_path = Path(entry["embedding_path"])
            pages_path = Path(entry["raw_pages_path"])
            if chunk_path.exists() and emb_path.exists() and pages_path.exists():
                chunks = load_json(chunk_path)
                embeddings = np.load(emb_path)
                return {
                    "pages": pages,
                    "chunks": chunks,
                    "embeddings": embeddings,
                    "manifest": entry,
                    "paths": paths,
                    "reused": True,
                }

    # ── build from scratch ──────────────────────────────────────────
    save_json(pages, paths["raw_pages"])

    chunks = build_chunks(
        pages, chunk_mode=chunk_mode, chunk_size=chunk_size, overlap=overlap
    )
    save_json(chunks, paths["chunks"])

    model = load_model(resolve_model_source(model_name, artifact_root=artifact_root))
    texts = [str(c["text"]) for c in chunks]
    embeddings = embed_texts(model, texts, batch_size=batch_size)
    np.save(paths["embeddings"], embeddings)

    # ── manifest entry ──────────────────────────────────────────────
    entry: dict[str, object] = {
        "document_id": document_id,
        "pdf_name": pdf_name,
        "num_pages": len(pages),
        "chunk_mode": chunk_mode,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "model_name": model_name,
        "num_chunks": len(chunks),
        "embedding_dim": int(embeddings.shape[1]),
        "device": get_device(),
        "chunk_path": str(paths["chunks"]),
        "embedding_path": str(paths["embeddings"]),
        "raw_pages_path": str(paths["raw_pages"]),
    }

    # Merge into existing manifest to avoid clobbering other configs.
    all_manifests = {}
    if paths["manifest"].exists():
        all_manifests = load_json(paths["manifest"])
    all_manifests[config_key] = entry
    save_json(all_manifests, paths["manifest"])

    return {
        "pages": pages,
        "chunks": chunks,
        "embeddings": embeddings,
        "manifest": entry,
        "paths": paths,
        "reused": False,
    }
