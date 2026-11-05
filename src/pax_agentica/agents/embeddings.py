"""Embeddings: text as vectors, so that a search finds what a question means, not only its words.

`GeminiEmbedder` asks `gemini-embedding-001` for 768 numbers per text: the docs show 768 scoring
within 0.2 points of 3072 on MTEB, at a quarter of the storage and a faster index. The model
normalises only full-length vectors, so shorter ones are normalised here. Documents and questions
are embedded with different task types, which the model is trained to match to each other.

`WordHashEmbedder` is a fake for the tests: free, offline and deterministic, and texts that share
words get close vectors, so a search over it still finds things.
"""

import hashlib
import math
import re
from typing import Literal, Protocol

from google import genai
from google.genai.types import EmbedContentConfig

from pax_agentica.agents.budget import Budget

type Purpose = Literal["document", "query"]

DIMENSIONS = 768
EMBEDDING_MODEL = "gemini-embedding-001"
PRICE_PER_MILLION_TOKENS = 0.15  # paid tier, ai.google.dev/gemini-api/docs/pricing, 2026-11-05
BATCH = 100  # texts per request
_CHARACTERS_PER_TOKEN_AT_LEAST = 2  # errs on the safe side, as for the plans

_TASKS: dict[Purpose, str] = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]: ...


def _normalised(vector: list[float]) -> list[float]:
    size = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / size for x in vector]


class GeminiEmbedder:
    """Embeds with Gemini, within a budget: each batch is paid for before it is sent."""

    def __init__(self, client: genai.Client, budget: Budget, dimensions: int = DIMENSIONS) -> None:
        self._client = client
        self._budget = budget
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return f"{EMBEDDING_MODEL}@{self._dimensions}"

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            # The answer gives no token count, so the estimate is what is charged: on the safe side.
            tokens = sum(len(t) for t in batch) // _CHARACTERS_PER_TOKEN_AT_LEAST
            cost = tokens * PRICE_PER_MILLION_TOKENS / 1_000_000
            self._budget.reserve(cost)
            try:
                answer = self._client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=batch,  # with this model, one embedding per string
                    config=EmbedContentConfig(
                        task_type=_TASKS[purpose], output_dimensionality=self._dimensions
                    ),
                )
            finally:
                self._budget.settle(cost, cost)
            vectors.extend(_normalised(list(e.values or [])) for e in answer.embeddings or [])
        if len(vectors) != len(texts):
            raise ValueError(f"asked for {len(texts)} embeddings, got {len(vectors)}")
        return vectors


class WordHashEmbedder:
    """A fake: each word adds one to a dimension chosen by its hash. Free, offline, repeatable."""

    def __init__(self, dimensions: int = DIMENSIONS) -> None:
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return f"word-hash@{self._dimensions}"

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for word in re.findall(r"[a-z]{3,}", text.lower()):
            digest = hashlib.blake2b(word.encode(), digest_size=4).digest()
            vector[int.from_bytes(digest) % self._dimensions] += 1.0
        return _normalised(vector)
