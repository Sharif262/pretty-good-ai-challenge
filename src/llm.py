from __future__ import annotations

from openai import OpenAI

from src.settings import get_settings


def get_client() -> OpenAI:
    settings = get_settings()
    kwargs = {"api_key": settings.llm_api_key}
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    return OpenAI(**kwargs)


def chat(messages: list[dict[str, str]], *, temperature: float = 0.7) -> str:
    settings = get_settings()
    client = get_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature,
    )
    return (response.choices[0].message.content or "").strip()
