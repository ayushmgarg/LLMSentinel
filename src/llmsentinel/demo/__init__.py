"""Offline, credential-free demonstration of the guard end to end."""

from __future__ import annotations

from .pipeline import (
    DemoResult,
    UnitFinding,
    analyse_manifest,
    analyse_rag,
    analyse_rag_text,
    analyse_tool_response,
)
from .retriever import Document, RetrievedChunk, Retriever
from .scenarios import (
    ManifestScenario,
    RagScenario,
    ToolResponseScenario,
    load_manifest_scenarios,
    load_rag_scenarios,
    load_tool_scenarios,
    proposed_actions,
)

__all__ = [
    "DemoResult",
    "Document",
    "ManifestScenario",
    "RagScenario",
    "RetrievedChunk",
    "Retriever",
    "ToolResponseScenario",
    "UnitFinding",
    "analyse_manifest",
    "analyse_rag",
    "analyse_rag_text",
    "analyse_tool_response",
    "load_manifest_scenarios",
    "load_rag_scenarios",
    "load_tool_scenarios",
    "proposed_actions",
]
