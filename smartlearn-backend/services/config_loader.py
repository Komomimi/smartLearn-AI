"""Read LLM / embedding configuration from the database, falling back to
environment variables or sensible defaults.

Import ``get_llm_config()`` wherever the OpenAI client is created so that
frontend settings take effect immediately without a restart.
"""

from __future__ import annotations

import os as _os
from pathlib import Path as _Path

from dotenv import load_dotenv as _load_dotenv

# Load .env once so the caller's working directory doesn't matter.
_env_path = _Path(__file__).resolve().parent.parent.parent / ".env"
_load_dotenv(_env_path)


def get_llm_config() -> dict[str, str]:
    """Return ``{api_key, base_url, model}`` for the OpenAI client.

    Priority: database settings → environment variables → defaults.
    """
    try:
        from services.database import get_setting
    except ImportError:
        get_setting = None  # type: ignore[assignment]

    db = lambda k, d: get_setting(k, d) if get_setting else d  # noqa: E731

    api_key = db("llm_api_key", "") or _os.getenv("OPENROUTER_API_KEY", "")
    base_url = db("llm_base_url", "") or "https://openrouter.ai/api/v1"
    model = db("llm_model", "") or _os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")

    return {"api_key": api_key, "base_url": base_url, "model": model}


def get_embedding_model_source() -> str | None:
    """Return a user-configured embedding model path, or ``None`` if not set.

    ``None`` means *resolve_model_source* will use its normal search logic.
    """
    try:
        from services.database import get_setting
    except ImportError:
        return None
    path = get_setting("embedding_model_path", "")
    return path if path else None
