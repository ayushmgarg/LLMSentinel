"""Multi-chunk (retrieval-bundle) scoring.

A RAG answer is built from several retrieved chunks, each with its own source.
Scoring them independently is necessary but not sufficient: an attacker can split
one instruction across two chunks so that neither looks like an injection alone,
and the model reassembles it when it reads them in order.

:func:`score_bundle` therefore does two passes and keeps both:

* a **per-chunk** pass, preserving each chunk's source and position, so a finding
  can always be traced to the document it came from;
* an **assembled** pass over the ordered concatenation, so a payload split across
  chunks is caught by the view the model actually sees.

When the assembled risk materially exceeds the best per-chunk risk, that gap is
itself the signal, and the bundle is marked for review. This is an experimental
layer; it does not replace per-unit scoring or the policy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from ..models.base import Scorer
from ..schema import Channel, CorpusRecord, Label
from .review import review_reasons

__all__ = ["BundleChunk", "BundleResult", "ChunkFinding", "score_bundle"]


@dataclass(frozen=True, slots=True)
class BundleChunk:
    """One retrieved chunk with the provenance that makes it untrusted."""

    text: str
    source: str
    channel: Channel = Channel.RAG_DOCUMENT


@dataclass(frozen=True, slots=True)
class ChunkFinding:
    """A per-chunk result, with order and source preserved."""

    order: int
    source: str
    channel: Channel
    risk: float


@dataclass(slots=True)
class BundleResult:
    """The outcome of scoring a retrieval bundle."""

    findings: list[ChunkFinding] = field(default_factory=list)
    assembled_risk: float = 0.0
    review: list[str] = field(default_factory=list)

    @property
    def max_chunk_risk(self) -> float:
        return max((f.risk for f in self.findings), default=0.0)

    @property
    def assembled_gain(self) -> float:
        """How much more the concatenation scores than the best single chunk."""

        return self.assembled_risk - self.max_chunk_risk

    @property
    def top(self) -> ChunkFinding | None:
        return max(self.findings, key=lambda f: f.risk, default=None)

    @property
    def needs_review(self) -> bool:
        return bool(self.review)


def _record(text: str, source: str, channel: Channel, host_task: str | None, order: int) -> CorpusRecord:
    # tool_metadata requires a json path; a bundle chunk is document-like, so map
    # metadata chunks onto a generic description path rather than inventing one.
    json_path = "$.description" if channel is Channel.TOOL_METADATA else None
    # Id includes a text digest: a cache keyed on record_id must not collide
    # across bundles that reuse the same chunk positions.
    digest = hashlib.sha1(f"{order}:{text}".encode()).hexdigest()[:12]
    return CorpusRecord(
        record_id=f"bundle-{order}-{digest}",
        source_dataset="bundle",
        source_document_id=source,
        source_license="n/a",
        raw_text=text,
        label=Label.BENIGN,  # label is unused; we read the score
        channel=channel,
        host_task=host_task,
        json_path=json_path,
    )


def score_bundle(
    chunks: Sequence[BundleChunk],
    scorer: Scorer,
    *,
    host_task: str | None = None,
    thresholds: dict[str, float] | None = None,
    separator: str = "\n\n",
) -> BundleResult:
    """Score a retrieval bundle per-chunk and as an ordered concatenation."""

    if not chunks:
        return BundleResult()

    records = [
        _record(chunk.text, chunk.source, chunk.channel, host_task, order)
        for order, chunk in enumerate(chunks)
    ]
    per_chunk = np.asarray(scorer.score(records), dtype=float)
    findings = [
        ChunkFinding(order=order, source=chunk.source, channel=chunk.channel, risk=float(per_chunk[order]))
        for order, chunk in enumerate(chunks)
    ]

    assembled_text = separator.join(chunk.text for chunk in chunks)
    assembled_channel = chunks[0].channel
    assembled_risk = float(
        scorer.score([_record(assembled_text, "assembled", assembled_channel, host_task, -1)])[0]
    )

    result = BundleResult(findings=findings, assembled_risk=assembled_risk)
    thresholds = dict(thresholds or {})
    result.review = review_reasons(
        risk=max(result.max_chunk_risk, assembled_risk),
        thresholds=thresholds,
        assembled_gain=result.assembled_gain,
    )
    # The sharpest split-payload signal: the concatenation crosses the elevated
    # threshold that no single chunk reaches. Reported even when the numeric gain
    # is modest, because crossing the operating point is what changes the outcome.
    loose = thresholds.get("fpr=0.01")
    if loose is not None and assembled_risk >= loose > result.max_chunk_risk:
        reason = (
            f"assembled risk {assembled_risk:.3f} crosses the elevated threshold "
            f"{loose:.3f} that no single chunk reaches (max chunk {result.max_chunk_risk:.3f})"
        )
        if reason not in result.review:
            result.review.append(reason)
    return result
