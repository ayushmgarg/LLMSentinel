"""Similarity to confirmed attacks (R2.3, REMAINING_THINGS B13). Experimental, advisory.

The rule engine matches known wordings and the transformer learns the training
distribution; neither is built to say "this sentence *means* the same as an attack we
have already seen". This scorer keeps a bank of confirmed attack texts (embedded once)
and scores a record by its single closest sentence: the maximum cosine similarity between
any sentence of the record and any attack in the bank.

Where the bank comes from is the point. In deployment it is the analyst history's
human-confirmed injections; for evaluation, with no live history, it is the injected spans
of the **train** split's positives (``fit``), the same information the other detectors
learn from. Nothing from dev or any test set enters the bank. Like candidate rules, it is
advisory: it is reported beside the frozen systems, never folded into them unmeasured.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ..models.base import Scorer
from ..output_check import _SENTENCE, _prose
from ..schema import CorpusRecord
from .similarity import Embedder, SentenceTransformerEmbedder

__all__ = ["AttackSimilarityScorer", "record_sentences"]

#: Sentences shorter than this carry too little meaning to match on.
MIN_WORDS = 3


def record_sentences(text: str) -> list[str]:
    """Sentences of a record, JSON tool results read leaf by leaf."""

    out = [s.strip() for leaf in _prose(text) for s in _SENTENCE.split(leaf)]
    return [s for s in out if len(s.split()) >= MIN_WORDS] or [text]


class AttackSimilarityScorer(Scorer):
    """Max cosine between a record's sentences and a bank of confirmed attacks."""

    name = "attack-similarity"

    def __init__(self, embedder: Embedder | None = None, *, batch_size: int = 64) -> None:
        self.embedder = embedder or SentenceTransformerEmbedder()
        self.batch_size = batch_size
        self.bank_texts: list[str] = []
        self._bank: np.ndarray | None = None

    def fit(self, records: Sequence[CorpusRecord]) -> AttackSimilarityScorer:
        """Bank = the injected spans of the positives given (train only, by the caller)."""

        texts = []
        for record in records:
            if not record.y:
                continue
            for span in record.injected_spans:
                payload = (record.text_for_field(span.field) or "")[span.start : span.end].strip()
                if len(payload.split()) >= MIN_WORDS:
                    texts.append(payload)
        return self.fit_texts(texts)

    def fit_texts(self, texts: Sequence[str]) -> AttackSimilarityScorer:
        """Bank = these texts (e.g. human-confirmed injections from the analyst history)."""

        self.bank_texts = list(dict.fromkeys(t for t in texts if t.strip()))
        if not self.bank_texts:
            raise ValueError("the attack bank is empty")
        self._bank = self._encode(self.bank_texts)
        return self

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        parts = [self.embedder.encode(texts[i : i + self.batch_size]) for i in range(0, len(texts), self.batch_size)]
        vectors = np.vstack(parts).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1, norms)

    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        return self.score_texts([record.raw_text for record in records])

    def score_texts(self, texts: Sequence[str]) -> np.ndarray:
        if self._bank is None:
            raise RuntimeError("fit the attack bank before scoring")
        sentences = [record_sentences(text) for text in texts]
        flat = [s for group in sentences for s in group]
        if not flat:
            return np.zeros(len(texts))
        best = (self._encode(flat) @ self._bank.T).max(axis=1)
        out, i = [], 0
        for group in sentences:
            out.append(float(best[i : i + len(group)].max()))
            i += len(group)
        return np.asarray(out)
