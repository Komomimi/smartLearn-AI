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


def extract_pages_for_rag(source: Union[str, Path, bytes], page_limit: int | None = None) -> list[dict[str, object]]:
    """Read a PDF page-by-page and return *only* readable ``{page, text}`` records.

    - *source* may be raw PDF bytes, a ``str`` path, or a ``pathlib.Path``.
    - Page numbers are the original 1-based PDF page numbers.
    - Pages whose extracted text is empty after :func:`clean_text` are dropped.
    - When *page_limit* is set, extraction stops after that many non‑empty
      pages have been collected.  ``None`` means no limit.
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
        if page_limit is not None and len(records) >= page_limit:
            break

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
# Path helpers
# ---------------------------------------------------------------------------


def relative_path_str(path: str | Path, base: str | Path) -> str:
    """Return *path* relative to *base* as a forward-slash string.

    When *path* is not under *base* the resolved absolute path is returned
    instead (so callers always get a usable string).
    """
    try:
        rel = Path(path).resolve().relative_to(Path(base).resolve())
    except ValueError:
        return str(Path(path).resolve()).replace("\\", "/")
    return str(rel).replace("\\", "/")


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

    if chunk_mode == "langchain_recursive":
        return chunk_with_langchain_recursive(records, chunk_size=chunk_size, chunk_overlap=overlap)

    raise ValueError(
        f"Unknown chunk_mode {chunk_mode!r}. "
        "Expected one of: paragraph, character, character_overlap, langchain_recursive."
    )


# ---------------------------------------------------------------------------
# LangChain-based recursive chunking (optional, cleaner splits for messy PDFs)
# ---------------------------------------------------------------------------


def chunk_with_langchain_recursive(
    records: list[dict[str, object]],
    chunk_size: int = 700,
    chunk_overlap: int = 120,
    separators: list[str] | None = None,
) -> list[dict[str, object]]:
    """Split pages into chunks with LangChain's RecursiveCharacterTextSplitter.

    This helper is designed for **messy PDF text** where paragraph boundaries
    are unreliable — e.g. hard line-breaks mid-sentence, missing blank lines
    between logical sections, or inconsistent whitespace.

    The splitter tries separators in priority order until a split succeeds
    within the allowed window, which naturally respects semantic structure
    better than a character-level slide when paragraph hints are weak.

    Parameters
    ----------
    records:
        Page records from :func:`extract_pages_for_rag`  (``[{page, text}, ...]``).
    chunk_size:
        Maximum characters per chunk (passed to LangChain as ``chunk_size``).
    chunk_overlap:
        Number of characters to overlap between consecutive chunks.
    separators:
        Optional override for the separator priority list.  Defaults to::

            ["\n\n", "\n", " ", ""]

        which means: prefer double-newline (paragraph boundary), then single
        newline, then space (word boundary), and finally character-level
        (hard cut when no other breaks exist).

    Returns
    -------
    list[dict]
        Chunks in the standard rag.py record format:
        ``{chunk_id, page, text, chunk_mode}`` (and ``chunk_size``,
        ``chunk_overlap`` for traceability).
    """
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        raise ImportError(
            "langchain-text-splitters is not installed. "
            "Install it with:  pip install langchain-text-splitters"
        )

    if separators is None:
        separators = ["\n\n", "\n" , " ", ""]

    splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )

    chunks: list[dict[str, object]] = []
    chunk_id = 0

    for record in records:
        page = record["page"]
        text = str(record["text"])

        # LangChain's split_text returns the raw chunk strings.
        raw_chunks = splitter.split_text(text)

        for raw in raw_chunks:
            trimmed = raw.strip()
            if not trimmed:
                continue
            chunk_id += 1
            chunks.append({
                "chunk_id": f"c{chunk_id:04d}",
                "page": page,
                "text": trimmed,
                "chunk_mode": "langchain_recursive",
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            })

    return chunks


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


# ---------------------------------------------------------------------------
# FAISS index helpers
# ---------------------------------------------------------------------------


def build_faiss_index(embeddings: "np.ndarray") -> "faiss.Index":
    """Build a FAISS ``IndexIDMap`` wrapping an ``IndexFlatIP`` for inner-product
    similarity search over pre-normalised embedding vectors.

    Parameters
    ----------
    embeddings:
        2‑D float32 array of shape ``(num_vectors, dim)``, already L2‑normalised
        (as produced by :func:`embed_texts`).

    Returns
    -------
    faiss.Index
        A train‑free FAISS index ready for :meth:`~faiss.Index.search`.

    Notes
    -----
    - Inner‑product (``IndexFlatIP``) is equivalent to cosine similarity when
      embeddings are L2‑normalised.
    - An ``IndexIDMap`` wrapper lets callers assign custom ids via
      :meth:`~faiss.IndexIDMap.add_with_ids` so that chunk‑level mapping
      stays straightforward.
    """
    import faiss  # type: ignore[import-untyped]

    dim = int(embeddings.shape[1])
    index = faiss.IndexIDMap(faiss.IndexFlatIP(dim))
    return index


def save_faiss_index(index: "faiss.Index", index_path: str | Path) -> None:
    """Write a FAISS index to disk as a binary ``.faiss`` file.

    The parent directory is created if it does not exist.  A companion
    ``.faiss_meta.json`` sidecar recording the total number of vectors and the
    index dimension is saved alongside the binary file.
    """
    import faiss  # type: ignore[import-untyped]

    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write main binary index
    faiss.write_index(index, str(path))

    # Write lightweight metadata sidecar
    meta = {
        "ntotal": int(index.ntotal),
        "d": int(index.d),
        "index_type": str(type(index)),
    }
    meta_path = path.with_suffix(".faiss_meta.json")
    save_json(meta, meta_path)


def load_faiss_index(index_path: str | Path) -> "faiss.Index":
    """Read a previously saved ``.faiss`` file back into memory.

    Parameters
    ----------
    index_path:
        Path to the ``.faiss`` file written by :func:`save_faiss_index`.

    Returns
    -------
    faiss.Index
        The deserialised FAISS index, ready for search.
    """
    import faiss  # type: ignore[import-untyped]

    return faiss.read_index(str(Path(index_path)))


# ---------------------------------------------------------------------------
# Higher-level document preparation & index pipeline
# ---------------------------------------------------------------------------


def prepare_rag_document(
    document_id: str,
    filename: str,
    pages: list[dict[str, object]],
    chunk_mode: str = "character_overlap",
    chunk_size: int = 700,
    overlap: int = 120,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 32,
    artifact_root: str | Path | None = None,
) -> dict[str, object]:
    """Prepare a document for RAG: chunk, embed, build FAISS index, save artifacts.

    When *artifact_root* is ``None`` it defaults to ``Day3/artifacts`` relative
    to the project root detected from ``rag.py``'s own file location.

    Parameters
    ----------
    document_id:
        Short unique id used in generated filenames, e.g. ``"pdf1"``.
    filename:
        Human-readable filename recorded in the manifest, e.g. ``"pdf1.pdf"``.
    pages:
        Page records from :func:`extract_pages_for_rag`.
    chunk_mode / chunk_size / overlap:
        Passed through to :func:`build_chunks`.
    model_name / batch_size:
        Passed through to the embedding pipeline.
    artifact_root:
        Directory under which artifacts are stored.  ``None`` auto‑detects
        ``<project_root>/Day3/artifacts``.

    Returns
    -------
    dict
        A document record with keys ``pages``, ``chunks``, ``chunk_size``
        (number of chunks), ``embedding_dim``, ``model_name``, ``model_source``,
        ``artifacts`` (nested dict with paths to ``index``, ``chunks``,
        ``embeddings``), and ``history`` (empty list).
    """
    import numpy as np  # type: ignore[import-untyped]
    import faiss  # type: ignore[import-untyped]

    # ── resolve artifact_root ──────────────────────────────────────────
    if artifact_root is None:
        rag_dir = Path(__file__).resolve().parent          # services/
        backend_dir = rag_dir.parent                        # smartlearn-backend/
        project_root = backend_dir.parent                   # smartLearn-AI/
        artifact_root = str(project_root.parent / "Day3" / "artifacts")

    paths = artifact_paths_for(
        document_id, chunk_mode, model_name, chunk_size, artifact_root
    )

    # ── build / reuse via ensure_artifacts ─────────────────────────────
    bundle = ensure_artifacts(
        document_id=document_id,
        pdf_name=filename,
        pages=pages,
        chunk_mode=chunk_mode,
        model_name=model_name,
        chunk_size=chunk_size,
        overlap=overlap,
        batch_size=batch_size,
        artifact_root=artifact_root,
    )

    chunks = bundle["chunks"]
    embeddings = bundle["embeddings"]

    # ── build or load FAISS index ──────────────────────────────────────
    index_path = paths["index"]
    if index_path.exists():
        index = load_faiss_index(index_path)
    else:
        index = build_faiss_index(embeddings)
        ids = np.arange(len(chunks), dtype=np.int64)
        index.add_with_ids(embeddings, ids)
        save_faiss_index(index, index_path)

    # ── resolve model_source ───────────────────────────────────────────
    model_source = resolve_model_source(model_name, artifact_root=artifact_root)

    # ── return the notebook-friendly structure ─────────────────────────
    return {
        "pages": pages,
        "chunks": chunks,
        "chunk_size": len(chunks),
        "embedding_dim": int(embeddings.shape[1]),
        "model_name": model_name,
        "model_source": model_source,
        "artifacts": {
            "index": str(paths["index"]),
            "chunks": str(paths["chunks"]),
            "embeddings": str(paths["embeddings"]),
        },
        "history": [],
    }


def ensure_index(
    document_id: str,
    pdf_name: str,
    pages: list[dict[str, object]] | None = None,
    pdf_path: str | Path | None = None,
    chunk_mode: str = "character_overlap",
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    chunk_size: int = 700,
    overlap: int = 120,
    batch_size: int = 32,
    artifact_root: str | Path | None = None,
) -> dict[str, object]:
    """Build or reuse the complete pages → chunks → embeddings → FAISS index pipeline.

    This is the single entry point callers should use when they need a
    searchable FAISS index at the end.  All intermediate artifacts (raw
    pages, chunks JSON, embeddings ``.npy``, FAISS ``.faiss``, and manifest)
    are saved under *artifact_root* and reused when the config signature
    matches.

    Parameters
    ----------
    document_id:
        Short unique id used in artifact filenames, e.g. ``"pdf1"``.
    pdf_name:
        Human-readable filename recorded in the manifest, e.g. ``"pdf1.pdf"``.
    pages:
        Pre‑extracted page records from :func:`extract_pages_for_rag`.  When
        ``None``, *pdf_path* is used to extract pages automatically.
    pdf_path:
        Path to a PDF file on disk.  Only used when *pages* is ``None``.
    chunk_mode / chunk_size / overlap:
        Passed through to :func:`build_chunks`.
    model_name / batch_size:
        Passed through to the embedding pipeline.
    artifact_root:
        Directory under which artifacts are stored.  ``None`` auto‑detects
        ``<project_root>/Day3/artifacts`` (see :func:`prepare_rag_document`).

    Returns
    -------
    dict
        A bundle with keys ``pages``, ``chunks``, ``embeddings``, ``index``
        (the loaded FAISS index), ``manifest``, ``paths``, and ``reused``.
    """
    import faiss  # type: ignore[import-untyped]

    # Resolve pages
    if pages is None:
        if pdf_path is None:
            raise ValueError("Either 'pages' or 'pdf_path' must be provided.")
        pages = extract_pages_for_rag(pdf_path)

    # Resolve artifact_root
    if artifact_root is None:
        rag_dir = Path(__file__).resolve().parent
        backend_dir = rag_dir.parent
        project_root = backend_dir.parent
        artifact_root = str(project_root.parent / "Day3" / "artifacts")

    paths = artifact_paths_for(
        document_id, chunk_mode, model_name, chunk_size, artifact_root
    )

    # ── config signature ──────────────────────────────────────────────
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

    # ── try full cache ─────────────────────────────────────────────────
    if paths["manifest"].exists():
        all_manifests = load_json(paths["manifest"])
        if config_key in all_manifests:
            entry = all_manifests[config_key]
            chunk_path = Path(entry["chunk_path"])
            emb_path = Path(entry["embedding_path"])
            pages_path = Path(entry["raw_pages_path"])
            index_path = paths["index"]
            if (
                chunk_path.exists()
                and emb_path.exists()
                and pages_path.exists()
                and index_path.exists()
            ):
                import numpy as np  # type: ignore[import-untyped]
                chunks = load_json(chunk_path)
                embeddings = np.load(emb_path)
                index = load_faiss_index(index_path)
                return {
                    "pages": pages,
                    "chunks": chunks,
                    "embeddings": embeddings,
                    "index": index,
                    "manifest": entry,
                    "paths": paths,
                    "reused": True,
                }

    # ── build from scratch ─────────────────────────────────────────────
    import numpy as np  # type: ignore[import-untyped]

    save_json(pages, paths["raw_pages"])

    chunks = build_chunks(
        pages, chunk_mode=chunk_mode, chunk_size=chunk_size, overlap=overlap
    )
    save_json(chunks, paths["chunks"])

    model = load_model(resolve_model_source(model_name, artifact_root=artifact_root))
    texts = [str(c["text"]) for c in chunks]
    embeddings = embed_texts(model, texts, batch_size=batch_size)
    np.save(paths["embeddings"], embeddings)

    # Build and populate FAISS index with custom ids
    index = build_faiss_index(embeddings)
    ids = np.arange(len(chunks), dtype=np.int64)
    index.add_with_ids(embeddings, ids)
    save_faiss_index(index, paths["index"])

    # ── manifest entry ─────────────────────────────────────────────────
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
        "index_path": str(paths["index"]),
        "raw_pages_path": str(paths["raw_pages"]),
    }

    all_manifests = {}
    if paths["manifest"].exists():
        all_manifests = load_json(paths["manifest"])
    all_manifests[config_key] = entry
    save_json(all_manifests, paths["manifest"])

    return {
        "pages": pages,
        "chunks": chunks,
        "embeddings": embeddings,
        "index": index,
        "manifest": entry,
        "paths": paths,
        "reused": False,
    }


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------


def keyword_set(text: str) -> set[str]:
    """Extract a lightweight set of lowercase tokens for lexical re‑ranking.

    Splits on whitespace, strips punctuation at word boundaries, and keeps
    only tokens that are ≥ 2 characters and not purely numeric.
    """
    tokens: set[str] = set()
    for token in text.lower().split():
        token = token.strip(".,;:!?\"'()[]{}<>，。；：！？""''（）【】《》")
        if len(token) >= 2 and not token.isdigit():
            tokens.add(token)
    return tokens


def search_bundle(
    question: str,
    bundle: dict[str, object],
    top_k: int = 3,
    candidate_pool: int = 60,
    batch_size: int = 1,
    history: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Search an in‑memory index bundle and return top‑*k* hits.

    Parameters
    ----------
    question:
        Natural‑language query text.
    bundle:
        In‑memory bundle from :func:`ensure_index` or :func:`ensure_artifacts`,
        containing at least ``index`` (FAISS), ``chunks`` (list of dicts with
        ``chunk_id``, ``page``, ``text``), and ``model_name``.
    top_k:
        Number of hits to return after re‑ranking.
    candidate_pool:
        How many nearest neighbours to request from FAISS before re‑ranking.
    batch_size:
        Batch size passed to ``embed_texts`` (1 is fine for a single query).
    history:
        Ignored; kept for API compatibility.
    """
    import numpy as np  # type: ignore[import-untyped]

    index = bundle["index"]
    chunks = bundle["chunks"]
    model_name = str(bundle.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"))
    # Always resolve to local cached model — HuggingFace is unreachable here.
    model_source = str(bundle.get("model_source", resolve_model_source(model_name)))

    # ── embed the question ───────────────────────────────────────────
    model = load_model(model_source)
    q_vec = embed_texts(model, [question], batch_size=batch_size)  # (1, dim)

    # ── FAISS search (inner product, larger than desired so we can rerank) ─
    k_search = min(candidate_pool, len(chunks))
    scores, ids = index.search(q_vec, k_search)  # type: ignore[call-overload]
    scores = scores[0]
    ids = ids[0]

    # ── build candidate hit list ──────────────────────────────────────
    q_tokens = keyword_set(question)

    candidates: list[dict[str, object]] = []
    for idx, score in zip(ids, scores):
        if idx < 0 or idx >= len(chunks):
            continue
        chunk = chunks[idx]
        candidates.append({
            "chunk_id": str(chunk["chunk_id"]),
            "page": int(chunk["page"]),
            "text": str(chunk["text"]),
            "score": float(score),
            "lexical_bonus": 0.0,
        })

    # ── lightweight lexical re‑rank ───────────────────────────────────
    for c in candidates:
        chunk_tokens = keyword_set(str(c["text"]))
        overlap = len(q_tokens & chunk_tokens)
        c["lexical_bonus"] = round(overlap * 0.02, 4)
        c["score"] = round(c["score"] + c["lexical_bonus"], 6)

    # Sort by composite score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # Trim to top_k
    hits = candidates[:top_k]

    # Add rank
    for rank, hit in enumerate(hits, start=1):
        hit["rank"] = rank

    return hits


def search_document(
    question: str,
    document: dict[str, object],
    top_k: int = 3,
    candidate_pool: int = 60,
    history: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Load the saved FAISS index from a prepared document and run retrieval.

    Parameters
    ----------
    question:
        Natural‑language query text.
    document:
        Document record returned by :func:`prepare_rag_document`.  Must
        contain ``artifacts["index"]`` and ``chunks``.
    top_k:
        Number of hits to return.
    candidate_pool:
        How many neighbours to fetch from FAISS before re‑ranking.
    history:
        Ignored; kept for API compatibility.
    """
    index_path = Path(str(document["artifacts"]["index"]))
    if not index_path.exists():
        raise FileNotFoundError(
            f"FAISS index not found at {index_path}. "
            "Run prepare_rag_document first."
        )

    index = load_faiss_index(index_path)
    chunks = document["chunks"]
    model_name = str(document.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"))
    # Prefer the pre‑resolved model_source from prepare_rag_document, fall back
    # to resolve_model_source so we never hit HuggingFace directly.
    model_source = str(document.get("model_source", resolve_model_source(model_name)))

    bundle: dict[str, object] = {
        "index": index,
        "chunks": chunks,
        "model_name": model_name,
        "model_source": model_source,
    }
    return search_bundle(
        question, bundle,
        top_k=top_k,
        candidate_pool=candidate_pool,
        history=history,
    )


def split_sentences(text: str) -> list[str]:
    """Split *text* into candidate answer sentences.

    Uses regex to split on English sentence endings (``.``, ``!``, ``?``
    followed by whitespace or end-of-string) and Chinese sentence endings
    (``。``, ``！``, ``？``).  Returns only non‑empty trimmed sentences.
    """
    # Split on sentence boundaries: English .!? followed by space; Chinese 。！？
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])|(?<=[。！？])(?=\S)", text)
    return [s.strip() for s in parts if s.strip()]


def best_sentence_answer(question: str, hits: list[dict[str, object]]) -> str:
    """Pick the best single answer sentence from the top retrieval hits.

    Strategy:
    1. Collect all sentences from all hits, tagged with their source page.
    2. Score each sentence by lexical overlap with the question (keyword
       intersection) plus a small boost for sentences from higher‑ranked hits.
    3. Return the highest‑scoring sentence with a ``[Page X]`` tag appended,
       or a fallback message when nothing maps.

    Parameters
    ----------
    question:
        Natural‑language query.
    hits:
        List of retrieval hits from :func:`search_bundle` or
        :func:`search_document`.
    """
    q_tokens = keyword_set(question)

    candidates: list[dict[str, object]] = []
    for hit in hits:
        page = int(hit["page"])
        rank = int(hit.get("rank", 99))
        sentences = split_sentences(str(hit["text"]))
        for sent in sentences:
            sent_tokens = keyword_set(sent)
            overlap = len(q_tokens & sent_tokens)
            # Boost higher‑ranked hits slightly
            rank_bonus = max(0.0, 0.1 / max(1, rank))
            score = overlap + rank_bonus
            candidates.append({
                "sentence": sent,
                "page": page,
                "score": score,
            })

    if not candidates:
        return "No relevant sentence found in the retrieved chunks."

    candidates.sort(key=lambda c: c["score"], reverse=True)
    best = candidates[0]
    return f"{best['sentence']} [Page {best['page']}]"


# ---------------------------------------------------------------------------
# Project-facing helpers  (answer / citations / sources / history)
# ---------------------------------------------------------------------------


def extract_citations(
    answer: str,
    hits: list[dict[str, object]] | None = None,
) -> list[int]:
    """Extract numeric PDF page citations from an answer string.

    Looks for ``[Page N]`` markers in *answer* and, when *hits* are also
    provided, falls back to collecting unique page numbers from the hits.
    Returns a sorted list of unique integer page numbers.
    """
    pages: set[int] = set()

    # Parse [Page N] markers
    for m in re.finditer(r"\[Page\s+(\d+)\]", answer):
        pages.add(int(m.group(1)))

    # Fallback: use page numbers from hits
    if not pages and hits:
        for h in hits:
            pages.add(int(h["page"]))

    return sorted(pages)


def build_sources(hits: list[dict[str, object]]) -> list[dict[str, object]]:
    """Convert retrieval hits into frontend-friendly source objects.

    Each source has ``page``, ``chunk_id``, ``score``, and ``preview`` (first
    120 characters of the chunk text) so the frontend can render clickable
    page references.
    """
    return [
        {
            "page": int(h["page"]),
            "chunk_id": str(h["chunk_id"]),
            "score": float(h["score"]),
            "preview": str(h["text"])[:120],
        }
        for h in hits
    ]


def answer_document(
    document: dict[str, object],
    question: str,
    top_k: int = 3,
    candidate_pool: int = 60,
    answer_model: str = "tencent/hy3:free",
) -> dict[str, object]:
    """Answer a question from a prepared document using retrieval + optional LLM.

    Parameters
    ----------
    document:
        Document record from :func:`prepare_rag_document`.
    question:
        Natural-language query.
    top_k:
        How many chunks to retrieve before answering.
    candidate_pool:
        FAISS candidate pool size.
    answer_model:
        OpenRouter model id used when ``OPENROUTER_API_KEY`` is available.

    Returns
    -------
    dict
        ``answer`` (str), ``citations`` (list[int]), ``sources`` (list[dict]).
    """
    # ── retrieval ────────────────────────────────────────────────────
    hits = search_document(
        question, document,
        top_k=top_k,
        candidate_pool=candidate_pool,
    )

    # ── try LLM answering ─────────────────────────────────────────────
    api_key = None
    try:
        import os as _os
        api_key = _os.getenv("OPENROUTER_API_KEY")
    except Exception:
        pass

    if api_key:
        try:
            # Build prompt from retrieved chunks
            context_parts = []
            for h in hits:
                context_parts.append(
                    f"### [Page {h['page']}] (chunk {h['chunk_id']})\n{h['text']}"
                )
            context = "\n\n".join(context_parts)

            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "http://localhost:5173",
                    "X-Title": "SmartLearn AI",
                },
            )
            response = client.chat.completions.create(
                model=answer_model,
                temperature=0.0,
                max_tokens=2000,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你只根据提供的检索结果回答问题。"
                            "引用事实时使用 [Page X] 标注页码。"
                            "如果没有相关信息，直接说'文档未提供足够信息'。"
                            "绝不编造页码。"
                            "始终使用中文回答，专业术语可保留原文并附带中文解释。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"检索结果：\n{context}\n\n问题：{question}",
                    },
                ],
            )
            answer = response.choices[0].message.content or ""
        except Exception:
            answer = best_sentence_answer(question, hits)
    else:
        # No API key — fall back to local sentence extraction
        answer = best_sentence_answer(question, hits)

    citations = extract_citations(answer, hits)
    sources = build_sources(hits)

    return {
        "answer": answer,
        "citations": citations,
        "sources": sources,
    }


def append_history(
    document: dict[str, object],
    question: str,
    result: dict[str, object],
) -> list[dict[str, object]]:
    """Record a Q&A turn in the document's in‑memory history list.

    Parameters
    ----------
    document:
        Document record from :func:`prepare_rag_document` (mutated in place).
    question:
        The user's question.
    result:
        The answer dict returned by :func:`answer_document`.

    Returns
    -------
    list[dict]
        The updated history list (same object as ``document["history"]``).
    """
    turn = {
        "question": question,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "timestamp": None,  # set by caller if needed
    }
    document["history"].append(turn)
    return document["history"]


# ---------------------------------------------------------------------------
# Simple retrieval evaluation
# ---------------------------------------------------------------------------


def normalize_for_match(text: str) -> str:
    """Normalise *text* for simple string‑based answer matching.

    - Lowercase
    - Collapse all whitespace runs to single spaces
    - Strip leading / trailing punctuation and whitespace

    This makes substring checks robust to minor formatting differences
    (capitalisation, extra spaces, line breaks) without requiring fuzzy
    matching libraries.
    """
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:!?\"'()[]{}<>，。；：！？""''（）【】《》\n\r\t")


def contains_any_answer(text: str, answers: list[str]) -> bool:
    """Check whether *text* contains any of the gold *answers* after normalisation.

    Parameters
    ----------
    text:
        The generated answer or retrieved chunk text to check.
    answers:
        List of acceptable gold answer strings, e.g. ``["knowledge graph", "graph-based"]``.

    Returns
    -------
    bool
        ``True`` when at least one normalised answer appears as a substring
        of the normalised *text*.
    """
    norm_text = normalize_for_match(text)
    for answer in answers:
        if normalize_for_match(answer) in norm_text:
            return True
    return False


def evaluate_questions(
    eval_set: list[dict[str, object]],
    documents_by_name: dict[str, dict[str, object]],
    top_k: int = 3,
    candidate_pool: int = 60,
) -> "pd.DataFrame":
    """Run a simple retrieval evaluation and return a table of results.

    For each question record in *eval_set* the function:

    1. Looks up the prepared document by ``pdf_name``.
    2. Calls :func:`search_document` to retrieve top‑*k* chunks.
    3. Generates a local answer via :func:`best_sentence_answer`.
    4. Compares the retrieval pages and the answer text against the gold
       ``acceptable_answers`` and ``answer_pages`` fields.

    Parameters
    ----------
    eval_set:
        List of question dicts.  Each must have at least ``question``,
        ``pdf_name``, ``acceptable_answers`` (list[str]), and
        ``answer_pages`` (list[int]).
    documents_by_name:
        Mapping from ``pdf_name`` to the prepared document record (the dict
        returned by :func:`prepare_rag_document`).
    top_k:
        Number of chunks to retrieve per question.
    candidate_pool:
        FAISS candidate pool size passed to :func:`search_document`.

    Returns
    -------
    pandas.DataFrame
        One row per question with columns:
        ``question``, ``pdf_name``, ``local_answer``, ``retrieved_pages``,
        ``retrieval_hit``, ``answer_hit``.
    """
    import pandas as pd  # type: ignore[import-untyped]

    rows: list[dict[str, object]] = []

    for record in eval_set:
        question = str(record["question"])
        pdf_name = str(record["pdf_name"])
        gold_pages = set(int(p) for p in record.get("answer_pages", []))  # type: ignore[arg-type]
        gold_answers = [str(a) for a in record.get("acceptable_answers", [])]  # type: ignore[union-attr]

        # Look up document
        document = documents_by_name.get(pdf_name)
        if document is None:
            rows.append({
                "question": question,
                "pdf_name": pdf_name,
                "local_answer": "(document not found)",
                "retrieved_pages": [],
                "retrieval_hit": False,
                "answer_hit": False,
            })
            continue

        # Retrieve
        hits = search_document(
            question, document,
            top_k=top_k,
            candidate_pool=candidate_pool,
        )

        # Generate answer
        answer = best_sentence_answer(question, hits)

        # Evaluate
        retrieved_pages = sorted(set(int(h["page"]) for h in hits))
        retrieval_hit = bool(gold_pages and set(retrieved_pages) & gold_pages)
        answer_hit = contains_any_answer(answer, gold_answers)

        rows.append({
            "question": question,
            "pdf_name": pdf_name,
            "local_answer": answer,
            "retrieved_pages": retrieved_pages,
            "retrieval_hit": retrieval_hit,
            "answer_hit": answer_hit,
        })

    return pd.DataFrame(rows)
