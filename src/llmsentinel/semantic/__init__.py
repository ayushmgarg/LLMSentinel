"""Semantic and context-aware detection (experimental).

These methods reason about whether an untrusted instruction belongs to the host
task and where it would send the result, rather than matching surface patterns.
They are reported alongside the frozen systems and are not part of the headline
hybrid until independently benchmarked.
"""

from __future__ import annotations

from .bundle import BundleChunk, BundleResult, ChunkFinding, score_bundle
from .features import (
    SEMANTIC_FEATURE_NAMES,
    SemanticFeatureExtractor,
    SemanticFeatures,
)
from .fixtures import (
    ContrastiveCase,
    MultiChunkCase,
    load_contrastive_cases,
    load_multichunk_cases,
)
from .representations import (
    ProposedAction,
    TaskContext,
    UntrustedInstruction,
    build_context,
    extract_actions,
)
from .review import REVIEW, review_reasons
from .scorer import SemanticScorer
from .similarity import (
    Embedder,
    LexicalEmbedder,
    SentenceTransformerEmbedder,
    cosine,
    default_embedder,
)

__all__ = [
    "REVIEW",
    "SEMANTIC_FEATURE_NAMES",
    "BundleChunk",
    "BundleResult",
    "ChunkFinding",
    "ContrastiveCase",
    "Embedder",
    "LexicalEmbedder",
    "MultiChunkCase",
    "ProposedAction",
    "SemanticFeatureExtractor",
    "SemanticFeatures",
    "SemanticScorer",
    "SentenceTransformerEmbedder",
    "TaskContext",
    "UntrustedInstruction",
    "build_context",
    "cosine",
    "default_embedder",
    "extract_actions",
    "load_contrastive_cases",
    "load_multichunk_cases",
    "review_reasons",
    "score_bundle",
]
