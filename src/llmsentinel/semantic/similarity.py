"""A pluggable text-similarity backend.

The semantic features need one operation: how related are two short texts? That
is the only thing a sentence embedder buys us here, so it is isolated behind a
tiny interface with two implementations:

* :class:`LexicalEmbedder` — default. Character n-gram hashing with cosine. No
  model download, no network, fully deterministic, so tests and a fresh checkout
  behave identically. It is an *overlap* proxy, not true semantics, and is
  labelled as such wherever its numbers are reported.
* :class:`SentenceTransformerEmbedder` — optional. A real sentence-embedding
  model (``all-MiniLM-L6-v2`` by default) when the ``semantic`` extra is
  installed and the weights are cached locally. Same interface, stronger
  paraphrase sensitivity.

:func:`default_embedder` returns the neural backend when it is importable and the
environment opts in, otherwise the lexical one, so nothing breaks offline.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

__all__ = [
    "Embedder",
    "LexicalEmbedder",
    "SentenceTransformerEmbedder",
    "cosine",
    "default_embedder",
]


@runtime_checkable
class Embedder(Protocol):
    """Maps texts to L2-normalised row vectors; cosine is then a dot product."""

    name: str

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two already-or-not-normalised vectors, in [-1, 1]."""

    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


class LexicalEmbedder:
    """Deterministic char-n-gram hashing vectoriser; an offline overlap proxy."""

    name = "lexical-hash"

    def __init__(self, n_features: int = 2**16) -> None:
        self._vectoriser = HashingVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            n_features=n_features,
            alternate_sign=False,
            norm="l2",
        )

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        cleaned = [t if t.strip() else " " for t in texts]
        return self._vectoriser.transform(cleaned).toarray().astype(np.float32)


class SentenceTransformerEmbedder:
    """Real sentence embeddings, used only when the optional extra is present."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # lazy, optional

        self.name = f"st:{model_name}"
        self._model = SentenceTransformer(model_name)

    @staticmethod
    def available() -> bool:
        import importlib.util

        return importlib.util.find_spec("sentence_transformers") is not None

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)


def default_embedder() -> Embedder:
    """Neural backend when installed and ``LLMSENTINEL_EMBEDDER=st``; else lexical.

    The opt-in keeps evaluation reproducible: a run is lexical unless someone
    deliberately asks for the neural backend, so logged numbers are never
    silently produced by whichever model happened to be on the machine.
    """

    opted_in = os.environ.get("LLMSENTINEL_EMBEDDER", "lexical").lower().startswith("st")
    if opted_in and SentenceTransformerEmbedder.available():
        return SentenceTransformerEmbedder()
    return LexicalEmbedder()
