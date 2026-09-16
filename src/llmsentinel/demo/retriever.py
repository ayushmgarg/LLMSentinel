"""A tiny deterministic retriever over the demo corpus.

The plan allows "a local retriever/index or deterministic retrieval simulation".
This is the former, kept deliberately small: TF-IDF cosine over the demo
documents, no external index, no network. It is deterministic given the corpus,
so the demo shows the *same* retrieval every run — which is what a
reproducible demo needs, and what a live vector DB would not give.

The point of the demo is not retrieval quality; it is that a poisoned page, once
retrieved, reaches the guard. So the retriever's only job is to surface the
relevant pages (including the poisoned one when it is in the index) for a query.
"""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

__all__ = ["Document", "RetrievedChunk", "Retriever"]


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    doc_id: str
    title: str
    text: str
    score: float


class Retriever:
    """TF-IDF cosine retriever. Fit once on a document set, then query."""

    def __init__(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("retriever needs at least one document")
        self.documents = documents
        self._vectorizer = TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), min_df=1, stop_words="english"
        )
        self._matrix = self._vectorizer.fit_transform(
            f"{doc.title}. {doc.text}" for doc in documents
        )

    def retrieve(self, query: str, k: int = 3) -> list[RetrievedChunk]:
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix)[0]
        order = scores.argsort()[::-1][:k]
        return [
            RetrievedChunk(
                doc_id=self.documents[i].doc_id,
                title=self.documents[i].title,
                text=self.documents[i].text,
                score=round(float(scores[i]), 4),
            )
            for i in order
            if scores[i] > 0.0
        ]
