"""Project paths.

Every command resolves its inputs and outputs through this module so that a run
started from any working directory writes to the same place, and so that the
experiment log can record a single ``data_version`` rather than a set of ad-hoc
paths.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "ARTIFACTS_DIR",
    "CORPUS_PATH",
    "DATA_DIR",
    "DOCS_DIR",
    "FIGURES_DIR",
    "MODELS_DIR",
    "PROCESSED_DIR",
    "PROJECT_ROOT",
    "RAW_DIR",
    "RESULTS_DIR",
    "SEED_DIR",
    "SPLIT_MANIFEST_PATH",
    "ensure_dirs",
    "relative",
]


def _find_root() -> Path:
    """Locate the project root: the ``LLMSENTINEL_ROOT`` override, or the
    nearest ancestor of this file that contains ``pyproject.toml``."""

    override = os.environ.get("LLMSENTINEL_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return here.parents[2]


PROJECT_ROOT = _find_root()

DATA_DIR = PROJECT_ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
MODELS_DIR = ARTIFACTS_DIR / "models"
RESULTS_DIR = ARTIFACTS_DIR / "results"
FIGURES_DIR = ARTIFACTS_DIR / "figures"

DOCS_DIR = PROJECT_ROOT / "docs"

CORPUS_PATH = PROCESSED_DIR / "corpus.jsonl"
SPLIT_MANIFEST_PATH = PROCESSED_DIR / "split_manifest.json"
CORPUS_CARD_PATH = DOCS_DIR / "corpus_card.md"
EXPERIMENT_LOG_PATH = DOCS_DIR / "EXPERIMENTS.md"


def ensure_dirs() -> None:
    """Create every output directory.  Safe to call repeatedly."""

    for path in (
        RAW_DIR,
        INTERIM_DIR,
        PROCESSED_DIR,
        MODELS_DIR,
        RESULTS_DIR,
        FIGURES_DIR,
        DOCS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def relative(path: Path | str) -> str:
    """Path relative to the project root, for readable log entries."""

    path = Path(path)
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)
