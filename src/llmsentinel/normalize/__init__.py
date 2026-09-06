"""Provenance-preserving normalisation of untrusted text and JSON."""

from __future__ import annotations

from .encoding import decode_embedded_payloads, looks_like_text
from .evidence import Evidence, EvidenceKind
from .json_leaves import JsonLeaf, extract_string_leaves, parse_json_safely
from .markup import decode_entities, detect_hidden_markup
from .offsets import OffsetMap
from .pipeline import NormalizationConfig, Normalizer
from .segment import segment_sentences
from .unicode_ops import detect_script_confusion, nfkc_normalise, strip_invisibles
from .units import DerivedSegment, NormalizedUnit, Sentence

__all__ = [
    "DerivedSegment",
    "Evidence",
    "EvidenceKind",
    "JsonLeaf",
    "NormalizationConfig",
    "NormalizedUnit",
    "Normalizer",
    "OffsetMap",
    "Sentence",
    "decode_embedded_payloads",
    "decode_entities",
    "detect_hidden_markup",
    "detect_script_confusion",
    "extract_string_leaves",
    "looks_like_text",
    "nfkc_normalise",
    "parse_json_safely",
    "segment_sentences",
    "strip_invisibles",
]
