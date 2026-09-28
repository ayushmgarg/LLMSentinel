"""Retrieval: dense by default, TF-IDF as the option and the fallback."""

from __future__ import annotations

import numpy as np
import pytest

from studio.server import retrieval
from studio.server.context import Chunk, ContextError
from studio.server.retrieval import DenseRetriever, make_retriever, retrieve

CHUNKS = [
    Chunk("a#0", "a", "leave.md", "rag_document", None, "Annual leave is 24 days per year for full-time staff.", 0),
    Chunk("b#0", "b", "parking.md", "rag_document", None, "Visitors park on levels 2 and 3 of the north car park.", 0),
]


class _Encoder:
    """Maps texts to toy 'meaning' vectors: holidays vs cars, regardless of shared words."""

    def encode(self, texts, normalize_embeddings=True):
        rows = []
        for text in texts:
            lower = text.lower()
            holiday = any(w in lower for w in ("leave", "holiday", "time off", "vacation"))
            car = any(w in lower for w in ("park", "car", "vehicle"))
            vector = np.array([1.0 if holiday else 0.0, 1.0 if car else 0.0, 0.1])
            rows.append(vector / np.linalg.norm(vector))
        return np.vstack(rows)


def test_dense_retrieval_matches_meaning_not_shared_words():
    # "time off" shares no word with "annual leave"; a keyword retriever cannot link them.
    ranked = DenseRetriever(CHUNKS, encoder=_Encoder()).retrieve("How much time off do I get?", 1)
    assert ranked[0][0].doc_id == "a"


def test_unknown_retriever_is_refused():
    with pytest.raises(ContextError):
        make_retriever(CHUNKS, "bm42")


def test_dense_falls_back_to_tfidf_and_says_so(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("model not cached and no network")

    monkeypatch.setattr(retrieval, "load_encoder", broken)
    result = retrieve(CHUNKS, "How many days of annual leave?", 1, "dense")
    assert result.method == "tfidf" and result.requested == "dense"
    assert result.notes and "TF-IDF" in result.notes[0]
    assert result.passages[0][0].doc_id == "a"


def test_tfidf_is_available_explicitly():
    result = retrieve(CHUNKS, "Where do visitors park?", 1, "tfidf")
    assert result.method == "tfidf" and not result.notes
    assert result.passages[0][0].doc_id == "b"
