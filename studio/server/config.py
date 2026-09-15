"""Studio settings: paths, request limits, tools and model-provider presets.

Provider presets use the documented local OpenAI-compatible endpoints:
Ollama serves ``http://localhost:11434/v1`` and LM Studio ``http://localhost:1234/v1``
by default; both ignore the API key locally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from llmsentinel.paths import MODELS_DIR, RESULTS_DIR

STUDIO_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = STUDIO_DIR / "web"
SAMPLES_DIR = STUDIO_DIR / "samples"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8700

MAX_FILE_BYTES = 2_000_000
MAX_UPLOADS = 12
MAX_QUESTION_CHARS = 1_000
ALLOWED_EXTENSIONS = (".txt", ".md", ".markdown", ".json", ".html", ".htm", ".csv")

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


@dataclass(slots=True)
class StudioSettings:
    use_transformer: bool = True
    checkpoint: Path = field(default_factory=lambda: MODELS_DIR / "transformer")
    results_path: Path = field(default_factory=lambda: RESULTS_DIR / "results_dev.json")
    top_k: int = 4
    request_timeout_s: float = 180.0
    max_tokens: int = 400
    temperature: float = 0.2
