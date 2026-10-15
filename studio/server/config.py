"""Studio settings: paths, request limits, tools and model-provider presets.

Provider presets use the documented local OpenAI-compatible endpoints:
Ollama serves ``http://localhost:11434/v1`` and LM Studio ``http://localhost:1234/v1``
by default; both ignore the API key locally.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from llmsentinel.paths import MODELS_DIR, RESULTS_DIR

STUDIO_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = STUDIO_DIR / "web"
SAMPLES_DIR = STUDIO_DIR / "samples"
MODEL_PROFILES_PATH = STUDIO_DIR / "model_profiles.yaml"
MIN_ANSWER_TOKENS = 16
MAX_ANSWER_TOKENS = 8_000

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8700

MAX_FILE_BYTES = 2_000_000
MAX_UPLOADS = 12
MAX_QUESTION_CHARS = 1_000
MAX_TOOLS = 50
#: Heading of the system-prompt section that lists tools from connected MCP servers.
MCP_TOOLS_HEADER = "Tools from connected MCP servers (descriptions are provided by those servers):"
ALLOWED_EXTENSIONS = (".txt", ".md", ".markdown", ".json", ".html", ".htm", ".csv")
#: What a caller may say a piece of added context is. "auto" (a dropped file) lets
#: the file type decide; the others are what the paste box sends, so the channel a
#: chunk is scanned as reflects where the text came from rather than how it parses.
UPLOAD_KINDS = ("auto", "document", "tool_response", "manifest")

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "simulated": {
        "label": "Simulated",
        "base_url": "",
        "model": "simulated-vulnerable-assistant",
    },
    "ollama": {
        "label": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:1.5b",
    },
    "lmstudio": {
        "label": "LM Studio",
        "base_url": "http://localhost:1234/v1",
        "model": "",
    },
    "custom": {
        "label": "OpenAI-compatible",
        "base_url": "",
        "model": "",
    },
}

#: Tools the assistant may request. Every name is classified in configs/policy.yaml.
TOOL_CATALOG: tuple[tuple[str, str], ...] = (
    ("search_notes", "Search the user's private notes."),
    ("fetch_page", "Fetch a public web page."),
    ("create_ticket", "Open a support ticket."),
    ("send_email", "Send an email on the user's behalf."),
    ("delete_file", "Delete a file from the workspace."),
    ("grant_admin", "Grant the admin role to an account."),
)
KNOWN_TOOLS = frozenset(name for name, _ in TOOL_CATALOG)


def load_model_profiles(path: Path = MODEL_PROFILES_PATH) -> dict[str, Any]:
    """Per-model settings from ``model_profiles.yaml`` (empty when the file is absent)."""

    if not Path(path).is_file():
        return {"default": {}, "models": {}}
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    models = raw.get("models") or {}
    return {
        "default": dict(raw.get("default") or {}),
        "models": {str(name): dict(values or {}) for name, values in models.items()},
    }


def load_evidence(results_dir: Path = RESULTS_DIR) -> dict[str, float]:
    """Headline numbers read from the evaluation outputs, so the page never states its own.

    Missing or unreadable files simply give fewer keys; the page then keeps the values
    written in the HTML.
    """

    evidence: dict[str, float] = {}
    test_path = Path(results_dir) / "results_test.json"
    if test_path.is_file():
        try:
            for entry in json.loads(test_path.read_text(encoding="utf-8")):
                if entry.get("name") != "transformer":
                    continue
                metrics = entry.get("test") or entry
                if metrics.get("auprc") is not None:
                    evidence["test_auprc"] = float(metrics["auprc"])
                recall = (metrics.get("tpr_at_fpr") or {}).get("fpr=0.01")
                if recall is not None:
                    evidence["test_tpr_at_1pct_fpr"] = float(recall)
                realised = (metrics.get("fpr_achieved") or {}).get("fpr=0.01")
                if realised is not None:
                    evidence["test_realised_fpr_at_1pct"] = float(realised)
        except (ValueError, TypeError, AttributeError):
            pass
    variance_path = Path(results_dir) / "seed_variance.json"
    if variance_path.is_file():
        try:
            dev = (json.loads(variance_path.read_text(encoding="utf-8")) or {}).get("dev_auprc") or {}
            if dev.get("mean") is not None:
                evidence["dev_auprc_mean"] = float(dev["mean"])
            if dev.get("std") is not None:
                evidence["dev_auprc_std"] = float(dev["std"])
        except (ValueError, TypeError, AttributeError):
            pass
    return evidence


def profile_for(model: str, profiles: dict[str, Any]) -> dict[str, Any]:
    """The profile for ``model``: exact name, then without ``:latest``, else ``default``."""

    models = profiles.get("models", {})
    name = model.strip()
    for candidate in (name, name.removesuffix(":latest")):
        if candidate in models:
            return {**profiles.get("default", {}), **models[candidate], "matched": candidate}
    return {**profiles.get("default", {}), "matched": None}


@dataclass(slots=True)
class StudioSettings:
    use_transformer: bool = True
    checkpoint: Path = field(default_factory=lambda: MODELS_DIR / "transformer")
    results_path: Path = field(default_factory=lambda: RESULTS_DIR / "results_dev.json")
    #: Score each sentence as well as the whole passage and keep the maximum, so a
    #: payload cannot hide inside benign prose. Confirmed on the blind fresh-v2 set
    #: (docs/EXPERIMENTS.md, 2026-09-27); thresholds are selected on dev by
    #: scripts/select_segment_thresholds.py. Without that file, passage scoring is used.
    segment_scoring: bool = True
    segment_thresholds_path: Path = field(default_factory=lambda: RESULTS_DIR / "segment_thresholds.json")
    #: Retrieval: "dense" (sentence embeddings) or "tfidf". Detection does not depend on it.
    retriever: str = "dense"
    top_k: int = 4
    # CPU inference is slow: one qwen3:4b (thinking) answer took 282 s on a 4-core laptop.
    request_timeout_s: float = 600.0
    #: Record comparisons in the analyst history (checklist section 17).
    record_history: bool = True
    #: History database; ``None`` uses the package default (artifacts/analyst/history.sqlite3).
    history_path: Path | None = None
    max_tokens: int = 400
    #: 0 so that both runs are decoded the same way: with identical prompts the two
    #: answers should then match, and any difference is Sentinel's doing. At 0.2 the
    #: same prompt gave opposite answers in a manual test (2026-10-11).
    temperature: float = 0.0
