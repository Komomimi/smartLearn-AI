import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent.parent.parent / ".env")

SYSTEM_PROMPT = (
    "你只根据提供的PDF文本来回答问题。"
    "引用事实时请使用 [Page X] 标注页码。"
    "如果PDF中没有相关信息，直接说'文档未提供足够信息'。"
    "绝不编造页码。"
    "始终使用中文回答，专业术语可保留原文并附带中文解释。"
)


def answer_from_pages(pages: list[dict], message: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    document_text = "\n\n".join(
        f"### [Page {page['page']}]\n{page['text']}"
        for page in pages
        if page["text"]
    )

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "SmartLearn AI",
        },
    )

    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free"),
            temperature=0.0,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"PDF text:\n{document_text}\n\nquestion: {message}",
                },
            ],
        )
    except Exception as e:
        raise RuntimeError(f"AI service request failed: {e}")

    if not response or not hasattr(response, "choices") or not response.choices:
        raise RuntimeError(
            "AI service returned an empty response — "
            "the free model may be rate-limited or temporarily unavailable. "
            "Please wait a moment and try again."
        )

    content = response.choices[0].message.content
    if not content:
        finish = getattr(response.choices[0], "finish_reason", "unknown")
        if finish == "length":
            raise RuntimeError("The answer was too long and was cut off. Please try a shorter question.")
        raise RuntimeError(
            "AI service returned an empty answer — "
            "the free model may be rate-limited or temporarily unavailable. "
            "Please wait a moment and try again."
        )

    return content