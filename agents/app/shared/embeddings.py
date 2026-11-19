"""Text embeddings for library search (owner: Will).

    from app.shared.embeddings import get_embedder
    emb = get_embedder()            # None when no key -> search falls back to keyword only
    vecs = emb.embed_documents([("Unit 3 notes", "Photosynthesis turns light into sugar...")])
    q = emb.embed_query("how do plants make food")

Provider: Gemini `gemini-embedding-2` (config.yaml -> agents.filing.embeddings).  It does not
take a task_type, so the role goes in the text itself, as Google recommends:
    documents  "title: {title} | text: {text}"
    queries    "task: search result | query: {query}"
We call the google-genai SDK directly because LangChain's wrapper always sends a task_type.

Tests set AGENTICTA_EMBEDDINGS=fake: a deterministic hashing embedder (no network, NOT
semantic) so the plumbing can be tested offline.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache
from typing import Protocol, Sequence

from langsmith import traceable

from . import quota
from .settings import agent_config, provider_key

BATCH = 50          # texts per API request
MAX_CHARS = 20_000  # well under the 8,192-token input limit


class Embedder(Protocol):
    model: str
    dims: int

    def embed_documents(self, items: Sequence[tuple[str, str]]) -> list[list[float]]: ...
    def embed_query(self, query: str) -> list[float]: ...


def _normalize(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class GeminiEmbedder:
    def __init__(self, model: str, dims: int, api_key: str):
        from google import genai

        self.model, self.dims = model, dims
        self._client = genai.Client(api_key=api_key)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            # One Content per text: gemini-embedding-2 merges parts of a single Content into one vector.
            contents = [types.Content(parts=[types.Part(text=t[:MAX_CHARS])]) for t in batch]
            for attempt in range(4):
                try:
                    resp = self._client.models.embed_content(
                        model=self.model, contents=contents,
                        config=types.EmbedContentConfig(output_dimensionality=self.dims),
                    )
                    break
                except Exception as e:
                    kind, delay = quota.classify(e)
                    if kind == "daily" or kind == "other" or attempt == 3:
                        raise
                    quota.wait(delay if kind == "minute" else 5 * (attempt + 1))  # free tier: 100/min
            out.extend(_normalize(e.values) for e in resp.embeddings)
        return out

    @traceable(name="embed_documents", run_type="embedding")
    def embed_documents(self, items: Sequence[tuple[str, str]]) -> list[list[float]]:
        return self._embed([f"title: {title or 'none'} | text: {text}" for title, text in items])

    @traceable(name="embed_query", run_type="embedding")
    def embed_query(self, query: str) -> list[float]:
        return self._embed([f"task: search result | query: {query}"])[0]


class FakeEmbedder:
    """Hashing bag-of-words.  Deterministic, offline, only for tests."""

    def __init__(self, dims: int):
        self.model, self.dims = "fake-hash", dims

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dims
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            v[h % self.dims] += 1.0 if (h >> 8) % 2 else -1.0
        return _normalize(v)

    def embed_documents(self, items: Sequence[tuple[str, str]]) -> list[list[float]]:
        return [self._vec(f"{title} {text}") for title, text in items]

    def embed_query(self, query: str) -> list[float]:
        return self._vec(query)


def embedding_spec() -> dict:
    return agent_config("filing")["embeddings"]


@lru_cache
def get_embedder() -> Embedder | None:
    spec = embedding_spec()
    if os.getenv("AGENTICTA_EMBEDDINGS") == "fake":
        return FakeEmbedder(spec["dims"])
    key = provider_key("filing", spec["provider"])  # filing agent's .env, then the project .env
    if spec["provider"] == "google_genai" and key:
        return GeminiEmbedder(spec["model"], spec["dims"], key)
    return None
