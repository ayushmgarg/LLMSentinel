"""Demo scenarios: load the fixtures and describe what each one demonstrates.

This module owns the *data* side of the demo — loading `data/demo/*.yaml`,
building the retriever, and exposing the fixed scenarios (clean/poisoned RAG,
clean/poisoned tool response, benign/poisoned/changed-hash manifests) with the
expected guard-off and guard-on behaviour recorded alongside each. Keeping this
separate from the analysis (``pipeline.py``) and the UI (``app.py``) means the
headless runner and the Streamlit page show identical scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..paths import DATA_DIR
from .retriever import Document, Retriever

__all__ = [
    "ManifestScenario",
    "RagScenario",
    "ToolResponseScenario",
    "load_manifest_scenarios",
    "load_rag_scenarios",
    "load_tool_scenarios",
]

DEMO_DIR = DATA_DIR / "demo"


def _load_yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((DEMO_DIR / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------- RAG
@dataclass(slots=True)
class RagScenario:
    name: str
    query: str
    documents: list[Document]
    poisoned: bool
    proposed_action: str | None
    expected_guard_off: str
    expected_guard_on: str
    #: doc_id of the injected page, when poisoned.
    poisoned_doc_id: str | None = None

    def retriever(self) -> Retriever:
        return Retriever(self.documents)


@lru_cache(maxsize=1)
def load_rag_scenarios() -> dict[str, RagScenario]:
    raw = _load_yaml("rag_corpus.yaml")
    clean_docs = [
        Document(d["doc_id"], d["title"], d["text"].strip()) for d in raw["documents"]
    ]
    poisoned = raw["poisoned_document"]
    poisoned_doc = Document(poisoned["doc_id"], poisoned["title"], poisoned["text"].strip())
    queries = raw["queries"]

    return {
        "clean": RagScenario(
            name="RAG — clean query",
            query=queries["clean"]["text"],
            documents=clean_docs,
            poisoned=False,
            proposed_action=queries["clean"].get("proposed_action"),
            expected_guard_off=queries["clean"]["expected_guard_off"].strip(),
            expected_guard_on=queries["clean"]["expected_guard_on"].strip(),
        ),
        "poisoned": RagScenario(
            name="RAG — poisoned document",
            query=queries["poisoned"]["text"],
            # The poisoned page is added to the index only in this scenario.
            documents=[poisoned_doc, *clean_docs],
            poisoned=True,
            proposed_action=queries["poisoned"].get("proposed_action"),
            expected_guard_off=queries["poisoned"]["expected_guard_off"].strip(),
            expected_guard_on=queries["poisoned"]["expected_guard_on"].strip(),
            poisoned_doc_id=poisoned_doc.doc_id,
        ),
    }


# --------------------------------------------------------------- tool response
@dataclass(slots=True)
class ToolResponseScenario:
    name: str
    tool: str
    document: Any
    poisoned: bool
    proposed_action: str | None
    injected_json_path: str | None
    expected: str


@lru_cache(maxsize=1)
def load_tool_scenarios() -> dict[str, ToolResponseScenario]:
    raw = _load_yaml("mcp_fixtures.yaml")["tool_responses"]
    out: dict[str, ToolResponseScenario] = {}
    for key, entry in raw.items():
        out[key] = ToolResponseScenario(
            name=f"Tool response — {key}",
            tool=entry["tool"],
            document=entry["json"],
            poisoned=(key == "poisoned"),
            proposed_action=entry.get("proposed_action"),
            injected_json_path=entry.get("injected_json_path"),
            expected=entry.get("description", ""),
        )
    return out


# ------------------------------------------------------------------- manifests
@dataclass(slots=True)
class ManifestScenario:
    name: str
    tool: dict[str, Any]
    kind: str  # benign | poisoned | changed_hash
    injected_json_path: str | None
    #: For changed_hash: the manifest key whose approved digest this is compared to.
    pinned_from: str | None
    description: str
    proposed_actions: dict[str, dict[str, str]] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_manifest_scenarios() -> dict[str, ManifestScenario]:
    raw = _load_yaml("mcp_fixtures.yaml")
    manifests = raw["tool_manifests"]
    out: dict[str, ManifestScenario] = {}
    for key, entry in manifests.items():
        out[key] = ManifestScenario(
            name=f"Tool manifest — {key}",
            tool=entry["tool"],
            kind=key,
            injected_json_path=entry.get("injected_json_path"),
            pinned_from=entry.get("pinned_from"),
            description=entry.get("description", "").strip(),
        )
    return out


def proposed_actions() -> dict[str, dict[str, str]]:
    return _load_yaml("mcp_fixtures.yaml").get("proposed_actions", {})


def demo_data_dir() -> Path:
    return DEMO_DIR
