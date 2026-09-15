"""Context for the Studio: uploaded or sample documents, chunking and retrieval.

Documents are split into retrieval chunks the way a RAG pipeline would: prose by
paragraphs (merged up to ~700 characters), JSON tool results by string leaf with
their JSON path kept as provenance. Retrieval is TF-IDF cosine -- deterministic
and offline, because the demo is about what happens *after* retrieval.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import ALLOWED_EXTENSIONS, MAX_FILE_BYTES, SAMPLES_DIR

__all__ = [
    "Chunk",
    "ChunkRetriever",
    "ContextError",
    "Document",
    "SampleInfo",
    "chunk_document",
    "document_from_upload",
    "load_samples",
]

_KIND = {
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".csv": "csv",
}
TARGET_CHARS = 700
MIN_LEAF_CHARS = 20


class ContextError(ValueError):
    """The provided context cannot be used; the message is shown to the user."""


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    name: str
    kind: str
    text: str
    origin: str  # "sample" | "upload"


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source: str
    channel: str  # "rag_document" | "tool_response"
    json_path: str | None
    text: str
    order: int

    @property
    def label(self) -> str:
        return f"{self.source} · {self.json_path}" if self.json_path else self.source


def document_from_upload(name: str, content: str) -> Document:
    ext = Path(name).suffix.lower()
    if ext not in _KIND:
        raise ContextError(f"{name}: unsupported file type (allowed: {', '.join(ALLOWED_EXTENSIONS)}).")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ContextError(f"{name}: larger than {MAX_FILE_BYTES // 1_000_000} MB.")
    if not content.strip():
        raise ContextError(f"{name}: the file is empty.")
    digest = hashlib.sha1(f"{name}\n{content}".encode()).hexdigest()[:10]
    return Document(doc_id=f"upload-{digest}", name=Path(name).name, kind=_KIND[ext], text=content, origin="upload")


def _json_leaves(node: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        if len(node.strip()) >= MIN_LEAF_CHARS:
            yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _json_leaves(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _json_leaves(value, f"{path}[{index}]")


def chunk_document(doc: Document) -> list[Chunk]:
    if doc.kind == "json":
        try:
            data = json.loads(doc.text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            leaves = list(_json_leaves(data))
            if leaves:
                return [
                    Chunk(f"{doc.doc_id}#{i}", doc.doc_id, doc.name, "tool_response", path, value, i)
                    for i, (path, value) in enumerate(leaves)
                ]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", doc.text) if p.strip()]
    merged: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if buffer and len(buffer) + len(paragraph) + 2 > TARGET_CHARS:
            merged.append(buffer)
            buffer = paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer:
        merged.append(buffer)
    return [
        Chunk(f"{doc.doc_id}#{i}", doc.doc_id, doc.name, "rag_document", None, text, i)
        for i, text in enumerate(merged)
    ]


class ChunkRetriever:
    """TF-IDF cosine retrieval over chunks (source name and JSON path included)."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = [c for c in chunks if c.text.strip()]
        if not self.chunks:
            raise ContextError("No readable text was found in the selected context.")
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        try:
            self._matrix = self._vectorizer.fit_transform(
                f"{c.source} {c.json_path or ''} {c.text}" for c in self.chunks
            )
        except ValueError as exc:  # empty vocabulary
            raise ContextError("The selected context has no searchable words.") from exc

    def retrieve(self, question: str, k: int) -> list[tuple[Chunk, float]]:
        scores = cosine_similarity(self._vectorizer.transform([question]), self._matrix)[0]
        order = sorted(range(len(self.chunks)), key=lambda i: (-float(scores[i]), i))[: max(1, k)]
        return [(self.chunks[i], round(float(scores[i]), 4)) for i in order]


@dataclass(frozen=True, slots=True)
class SampleInfo:
    doc: Document
    label: str
    attack: str
    note: str
    canaries: tuple[str, ...]


def load_samples(samples_dir: Path = SAMPLES_DIR) -> tuple[dict[str, SampleInfo], list[str], dict[str, str]]:
    manifest = yaml.safe_load((samples_dir / "manifest.yaml").read_text(encoding="utf-8"))
    samples: dict[str, SampleInfo] = {}
    for item in manifest.get("documents", []):
        path = samples_dir / item["file"]
        doc = Document(
            doc_id=str(item["id"]),
            name=path.name,
            kind=_KIND[path.suffix.lower()],
            text=path.read_text(encoding="utf-8"),
            origin="sample",
        )
        samples[doc.doc_id] = SampleInfo(
            doc=doc,
            label=str(item.get("label", "unknown")),
            attack=str(item.get("attack", "none")),
            note=str(item.get("note", "")).strip(),
            canaries=tuple(str(c) for c in item.get("canaries", []) or []),
        )
    meta = {"title": str(manifest.get("title", "")), "license": str(manifest.get("license", ""))}
    return samples, [str(q) for q in manifest.get("questions", [])], meta
