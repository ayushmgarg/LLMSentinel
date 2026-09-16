"""Fine-tuned encoder detector.

PyTorch and transformers are an *optional* extra: importing this module without
them raises a clear error, and the harness skips the system rather than failing
the run.  Everything else in the project works without them.

Decisions worth stating, because they change the numbers:

**Backbone.**  ``distilroberta-base`` -- six layers, byte-level BPE.  Byte-level
tokenisation matters here: the attacks include spaced-out and homoglyph text
that a WordPiece vocabulary shreds into unknowns.  ``BACKBONE_FALLBACK`` is a
smaller model for machines where the primary one does not fit or is too slow;
the choice is recorded in ``describe()`` so a result is never ambiguous about
which model produced it.

**Windowing.**  Retrieved documents are longer than the encoder's context.  A
document is split into overlapping windows and scored as the **maximum** over
windows, because one malicious sentence in an otherwise clean page must not be
averaged away.  The cost is that a long benign document has more chances to
produce a false positive, which is visible in the per-channel numbers.

**Imbalance.**  The corpus is roughly 30% positive, and the operating points
that matter live at very low false-positive rates.  The loss is class-weighted
by inverse frequency, which is the documented alternative to resampling and
keeps every training record in play.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..constants import DEFAULT_SEED
from ..paths import MODELS_DIR
from ..schema import CorpusRecord
from .base import Scorer
from .dataset import build_examples, make_dataloader

__all__ = [
    "BACKBONE_FALLBACK",
    "BACKBONE_PRIMARY",
    "TransformerConfig",
    "TransformerScorer",
    "WindowScore",
    "torch_available",
]


@dataclass(slots=True)
class WindowScore:
    """A record's risk plus the evidence of which window produced it."""

    risk: float
    top_window_index: int
    windows_scored: int
    windows_total: int
    truncated: bool
    top_window_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

BACKBONE_PRIMARY = "distilroberta-base"
BACKBONE_FALLBACK = "distilbert-base-uncased"


def torch_available() -> bool:
    """True when the optional transformer extra is installed."""

    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _require_torch() -> tuple[Any, Any]:
    try:
        import torch
        import transformers
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "The transformer detector needs the optional extra. Install it with:\n"
            "  python -m pip install -r requirements-transformer.txt "
            "--index-url https://download.pytorch.org/whl/cpu"
        ) from exc
    return torch, transformers


@dataclass(slots=True)
class TransformerConfig:
    """Training and inference settings; serialised next to every checkpoint."""

    backbone: str = BACKBONE_PRIMARY
    max_length: int = 256
    #: Overlap between windows, in tokens.  Half the window keeps any sentence
    #: whole in at least one window.
    stride: int = 128
    #: Windows scored per document.  Bounds the cost of a hostile 1 MB input.
    max_windows: int = 8
    epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    seed: int = DEFAULT_SEED
    #: "auto" uses CUDA when available and falls back to CPU; "cpu"/"cuda" force
    #: a device. The resolved device is recorded in describe() so a result says
    #: what it ran on. Kept "auto" by default so a GPU machine is used without a
    #: flag -- an earlier "cpu" default wasted a CUDA GPU on the training run.
    device: str = "auto"
    class_weighted_loss: bool = True
    #: Expand each training record into the same overlapping windows inference
    #: scores.  Disabling it truncates to ``max_length`` instead, which is the
    #: cheaper and noisier option; the two are compared in docs/EXPERIMENTS.md.
    window_training: bool = True
    #: Label a positive record's windows 1 only where the injected span lands,
    #: instead of inheriting the document label on every window.  Records without
    #: spans fall back to the document label.  See docs/EXPERIMENTS.md for which
    #: checkpoints were trained with this on.
    span_aware_labels: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TransformerScorer(Scorer):
    """Sequence-classification head over a small pretrained encoder."""

    name = "transformer"

    def __init__(self, config: TransformerConfig | None = None) -> None:
        self.config = config or TransformerConfig()
        self._tokenizer: Any = None
        self._model: Any = None
        self._trained = False
        self._device: str | None = None

    # ------------------------------------------------------------------ setup
    def _resolve_device(self) -> str:
        """Turn the configured device into a concrete one: 'auto' -> CUDA if
        present, else CPU. A forced 'cuda'/'cpu' is honoured as given."""

        torch, _ = _require_torch()
        want = (self.config.device or "auto").lower()
        if want in ("auto", ""):
            return "cuda" if torch.cuda.is_available() else "cpu"
        return want

    def _seed_everything(self) -> None:
        torch, _ = _require_torch()
        random.seed(self.config.seed)
        np.random.seed(self.config.seed)
        torch.manual_seed(self.config.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(self.config.seed)

    def _load_backbone(self, name: str | None = None) -> None:
        _, transformers = _require_torch()
        target = name or self.config.backbone
        self._device = self._resolve_device()
        self._tokenizer = transformers.AutoTokenizer.from_pretrained(target)
        self._model = transformers.AutoModelForSequenceClassification.from_pretrained(
            target, num_labels=2
        )
        self._model.to(self._device)
        self.config.backbone = target

    # --------------------------------------------------------------- training
    def fit(self, records: Sequence[CorpusRecord]) -> TransformerScorer:
        torch, _ = _require_torch()
        if not records:
            raise ValueError("cannot fit on an empty training split")

        self._seed_everything()
        if self._model is None:
            self._load_backbone()

        # Train on the same windows inference scores.  With span-aware labelling
        # a positive record's windows are labelled 1 only where the injected span
        # lands, so a clean window of a long positive is not taught as an
        # injection; records without spans fall back to the document label.
        examples = build_examples(
            records,
            windower=self._windows,
            window_training=self.config.window_training,
            span_aware_labels=self.config.span_aware_labels,
        )
        labels = np.asarray([example.label for example in examples], dtype=np.int64)
        weights = self._class_weights(labels)

        optimiser = torch.optim.AdamW(
            self._model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        steps_per_epoch = math.ceil(len(examples) / self.config.batch_size)
        total_steps = max(1, steps_per_epoch * self.config.epochs)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            optimiser,
            max_lr=self.config.learning_rate,
            total_steps=total_steps,
            pct_start=self.config.warmup_ratio,
            anneal_strategy="linear",
        )
        loss_fn = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(weights, dtype=torch.float, device=self._device)
            if self.config.class_weighted_loss
            else None
        )

        loader = make_dataloader(
            examples,
            self._tokenizer,
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
            seed=self.config.seed,
        )

        self._model.train()
        for _epoch in range(self.config.epochs):
            for batch in loader:
                batch = {key: value.to(self._device) for key, value in batch.items()}
                targets = batch.pop("labels")

                optimiser.zero_grad(set_to_none=True)
                logits = self._model(**batch).logits
                loss = loss_fn(logits, targets)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
                optimiser.step()
                scheduler.step()

        self._model.eval()
        self._trained = True
        return self

    @staticmethod
    def _class_weights(labels: np.ndarray) -> list[float]:
        """Inverse-frequency weights, normalised to mean 1."""

        counts = np.bincount(labels, minlength=2).astype(float)
        counts[counts == 0] = 1.0
        weights = counts.sum() / (2.0 * counts)
        return (weights / weights.mean()).tolist()

    # -------------------------------------------------------------- inference
    def score(self, records: Sequence[CorpusRecord]) -> np.ndarray:
        return np.asarray([detail.risk for detail in self.score_details(records)], dtype=float)

    def score_details(self, records: Sequence[CorpusRecord]) -> list[WindowScore]:
        """Score each record and preserve which window carried the risk.

        The highest-risk window's index and text are retained (the V2 checkbox
        "preserve highest-risk window position/evidence"), and truncation is
        reported rather than silent: when a document needs more than
        ``max_windows`` windows, the overflow is counted so a clipped input is
        visible, not ignored.
        """

        torch, _ = _require_torch()
        if self._model is None:
            raise RuntimeError("transformer must be fitted or loaded before scoring")
        details: list[WindowScore] = []
        if not records:
            return details

        self._model.eval()
        with torch.no_grad():
            for record in records:
                windows, total = self._window_plan(record.text)
                encoded = self._tokenizer(
                    windows,
                    truncation=True,
                    max_length=self.config.max_length,
                    padding=True,
                    return_tensors="pt",
                ).to(self._device)
                probabilities = torch.softmax(self._model(**encoded).logits, dim=-1)[:, 1]
                # Max over windows: one malicious sentence must not be averaged
                # away by the clean remainder of a long document.
                top = int(torch.argmax(probabilities).item())
                details.append(
                    WindowScore(
                        risk=float(probabilities[top].item()),
                        top_window_index=top,
                        windows_scored=len(windows),
                        windows_total=total,
                        truncated=total > len(windows),
                        top_window_text=windows[top][:200],
                    )
                )
        return details

    def _window_plan(self, text: str) -> tuple[list[str], int]:
        """Overlapping windows (capped at ``max_windows``) and the total count.

        Returns the windows actually scored together with how many windows the
        text would have produced before the cap, so the caller can tell when a
        long input was clipped.
        """

        ids = self._tokenizer(text, add_special_tokens=False)["input_ids"]
        budget = self.config.max_length - 2  # room for the special tokens
        if len(ids) <= budget:
            return [text], 1
        step = max(1, budget - self.config.stride)
        starts = list(range(0, len(ids), step))
        windows = [self._tokenizer.decode(ids[start : start + budget]) for start in starts]
        capped = windows[: self.config.max_windows] or [text]
        return capped, len(starts)

    def _windows(self, text: str) -> list[str]:
        """Windows used for training; the scored subset of :meth:`_window_plan`."""

        return self._window_plan(text)[0]

    # ------------------------------------------------------------------- I/O
    def save(self, path: str | Path | None = None) -> Path:
        if self._model is None:
            raise RuntimeError("nothing to save: the model has not been built")
        target = Path(path) if path else MODELS_DIR / "transformer"
        target.mkdir(parents=True, exist_ok=True)
        self._model.save_pretrained(target)
        self._tokenizer.save_pretrained(target)
        (target / "llmsentinel_config.json").write_text(
            json.dumps(self.config.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return target

    @classmethod
    def load(cls, path: str | Path | None = None) -> TransformerScorer:
        """Reload a checkpoint in a clean process, config included."""

        source = Path(path) if path else MODELS_DIR / "transformer"
        config_path = source / "llmsentinel_config.json"
        config = TransformerConfig(
            **json.loads(config_path.read_text(encoding="utf-8"))
            if config_path.is_file()
            else {}
        )
        scorer = cls(config)
        scorer._load_backbone(str(source))
        scorer._model.eval()
        scorer._trained = True
        return scorer

    # ------------------------------------------------------------------ misc
    def describe(self) -> dict[str, Any]:
        parameters = (
            sum(p.numel() for p in self._model.parameters()) if self._model is not None else 0
        )
        return {
            **super().describe(),
            **self.config.to_dict(),
            "resolved_device": self._device or "not-loaded",
            "parameters": parameters,
            "trained": self._trained,
        }
