"""Retrievers for the Studio: dense (sentence embeddings) by default, TF-IDF as the option.

Retrieval decides which passages reach the model; it does not change detection, which
scores whatever it is handed. The dense retriever is the realistic choice -- deployed
RAG systems match meaning, not shared words -- and TF-IDF stays for reproducibility
and as the fallback when the embedding model cannot be loaded.

The embedding model is ``sentence-transformers/all-MiniLM-L6-v2`` (22M parameters,
CPU-friendly). It is loaded from the local Hugging Face cache first, so the Studio
keeps working offline once the model has been downloaded; if it cannot be loaded at
all, retrieval falls back to TF-IDF and says so in the result.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from .context import Chunk, ChunkRetriever, ContextError

__all__ = [
    "DENSE_MODEL",
    "RETRIEVERS",
    "DenseRetriever",
    "Retrieval",
    "Retriever",
    "TfidfRetriever",
    "make_retriever",
]

DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RETRIEVERS = ("dense", "tfidf")

#: TF-IDF retrieval is the existing ChunkRetriever, kept under its old name too.
TfidfRetriever = ChunkRetriever

_MODEL: dict[str, Any] = {}
_LOCK = threading.Lock()


class Retriever(Protocol):
    def retrieve(self, question: str, k: int) -> list[tuple[Chunk, float]]: ...


def _chunk_text(chunk: Chunk) -> str:
    return f"{chunk.source} {chunk.json_path or ''} {chunk.text}".strip()


def load_encoder(name: str = DENSE_MODEL) -> Any:
    """The sentence encoder, loaded once per process (local cache first)."""

    with _LOCK:
        if name not in _MODEL:
            from sentence_transformers import SentenceTransformer

            try:
                _MODEL[name] = SentenceTransformer(name, device="cpu", local_files_only=True)
            except Exception:  # not cached yet: allow one download
                _MODEL[name] = SentenceTransformer(name, device="cpu")
        return _MODEL[name]


class DenseRetriever:
    """Cosine similarity between normalised sentence embeddings."""

    def __init__(self, chunks: list[Chunk], *, encoder: Any | None = None) -> None:
        self.chunks = [c for c in chunks if c.text.strip()]
        if not self.chunks:
            raise ContextError("No readable text was found in the selected context.")
        self.encoder = encoder or load_encoder()
        self._matrix = np.asarray(
            self.encoder.encode([_chunk_text(c) for c in self.chunks], normalize_embeddings=True), dtype=float
        )

    def retrieve(self, question: str, k: int) -> list[tuple[Chunk, float]]:
        query = np.asarray(self.encoder.encode([question], normalize_embeddings=True), dtype=float)[0]
        scores = self._matrix @ query
        order = sorted(range(len(self.chunks)), key=lambda i: (-float(scores[i]), i))[: max(1, k)]
        return [(self.chunks[i], round(float(scores[i]), 4)) for i in order]


@dataclass(slots=True)
class Retrieval:
    method: str
    requested: str
    passages: list[tuple[Chunk, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "requested": self.requested, "notes": list(self.notes)}


def make_retriever(chunks: list[Chunk], kind: str) -> tuple[Retriever, str, list[str]]:
    """The requested retriever, or TF-IDF with a note saying why not."""

    if kind not in RETRIEVERS:
        raise ContextError(f"Unknown retriever {kind!r}; choose one of {', '.join(RETRIEVERS)}.")
    if kind == "dense":
        try:
            return DenseRetriever(chunks), "dense", []
        except ContextError:
            raise
        except Exception as exc:  # missing package, no cached model and no network, ...
            note = f"Dense retrieval unavailable ({type(exc).__name__}); used TF-IDF instead."
            return TfidfRetriever(chunks), "tfidf", [note]
    return TfidfRetriever(chunks), "tfidf", []


def retrieve(chunks: list[Chunk], question: str, k: int, kind: str) -> Retrieval:
    retriever, method, notes = make_retriever(chunks, kind)
    return Retrieval(method=method, requested=kind, passages=retriever.retrieve(question, k), notes=notes)
