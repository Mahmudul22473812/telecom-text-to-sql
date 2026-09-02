"""Environment-selected AI model access for local and hosted runtimes."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import ollama
from dotenv import load_dotenv


SUPPORTED_PROVIDERS = {"ollama", "gemini"}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def active_provider() -> str:
    """Return the configured provider, defaulting to local Ollama."""

    provider = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise RuntimeError(
            f"Unsupported AI_PROVIDER {provider!r}. Choose one of: {choices}."
        )
    return provider


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is required when AI_PROVIDER={active_provider()}."
        )
    return value


@lru_cache(maxsize=2)
def _gemini_client(api_key: str):
    try:
        from google import genai
    except ImportError as error:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "Gemini support requires the google-genai package. "
            "Install the dependencies from requirements.txt."
        ) from error

    return genai.Client(api_key=api_key)


def _gemini_types():
    try:
        from google.genai import types
    except ImportError as error:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "Gemini support requires the google-genai package. "
            "Install the dependencies from requirements.txt."
        ) from error

    return types


def _message_text(messages: Sequence[dict[str, str]]) -> tuple[str, str]:
    system_parts = []
    conversation_parts = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            conversation_parts.append(f"{role.upper()}:\n{content}")

    return "\n\n".join(system_parts), "\n\n".join(conversation_parts)


def chat_json(
    messages: Sequence[dict[str, str]],
    *,
    local_model: str = "llama3.2",
) -> str:
    """Return a JSON response using the configured chat provider."""

    if active_provider() == "ollama":
        model = os.getenv("OLLAMA_CHAT_MODEL", local_model).strip()
        response = ollama.chat(
            model=model,
            messages=list(messages),
            format="json",
            options={"temperature": 0},
        )
        return response["message"]["content"]

    api_key = _required_environment("GEMINI_API_KEY")
    model = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.6-flash").strip()
    system_instruction, contents = _message_text(messages)
    types = _gemini_types()
    response = _gemini_client(api_key).models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    return text


@lru_cache(maxsize=32)
def embed_texts(
    texts: tuple[str, ...],
    *,
    local_model: str = "nomic-embed-text",
) -> tuple[tuple[float, ...], ...]:
    """Embed one or more texts in one provider request and cache the result."""

    if not texts:
        return ()

    if active_provider() == "ollama":
        model = os.getenv("OLLAMA_EMBEDDING_MODEL", local_model).strip()
        response = ollama.embed(model=model, input=list(texts))
        return tuple(
            tuple(float(value) for value in embedding)
            for embedding in response["embeddings"]
        )

    api_key = _required_environment("GEMINI_API_KEY")
    model = os.getenv(
        "GEMINI_EMBEDDING_MODEL",
        "gemini-embedding-001",
    ).strip()
    types = _gemini_types()
    contents = [
        types.Content(parts=[types.Part.from_text(text=text)])
        for text in texts
    ]
    response = _gemini_client(api_key).models.embed_content(
        model=model,
        contents=contents,
        config=types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=768,
        ),
    )
    embeddings = getattr(response, "embeddings", None)
    if not embeddings or len(embeddings) != len(texts):
        raise RuntimeError("Gemini returned an invalid embedding response.")

    def values(embedding: Any) -> tuple[float, ...]:
        raw_values = getattr(embedding, "values", None)
        if raw_values is None:
            raise RuntimeError("Gemini returned an embedding without values.")
        return tuple(float(value) for value in raw_values)

    return tuple(values(embedding) for embedding in embeddings)


def get_embedding(
    text: str,
    *,
    local_model: str = "nomic-embed-text",
) -> tuple[float, ...]:
    """Embed a single text through the shared batch implementation."""

    return embed_texts((text,), local_model=local_model)[0]
