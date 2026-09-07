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

__all__ = ["BACKBONE_FALLBACK", "BACKBONE_PRIMARY", "TransformerConfig", "TransformerScorer", "torch_available"]

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
    device: str = "cpu"
    class_weighted_loss: bool = True
    #: Expand each training record into the same overlapping windows inference
    #: scores.  Disabling it truncates to ``max_length`` instead, which is the
    #: cheaper and noisier option; the two are compared in docs/EXPERIMENTS.md.
    window_training: bool = True

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

    # ------------------------------------------------------------------ setup
    def _seed_everything(self) -> None:
        torch, _ = _require_torch()
        random.seed(self.config.seed)
        np.random.seed(self.config.seed)
        torch.manual_seed(self.config.seed)

    def _load_backbone(self, name: str | None = None) -> None:
        _, transformers = _require_torch()
        target = name or self.config.backbone
        self._tokenizer = transformers.AutoTokenizer.from_pretrained(target)
        self._model = transformers.AutoModelForSequenceClassification.from_pretrained(
            target, num_labels=2
        )
        self._model.to(self.config.device)
        self.config.backbone = target

    # --------------------------------------------------------------- training
    def fit(self, records: Sequence[CorpusRecord]) -> TransformerScorer:
        torch, _ = _require_torch()
        if not records:
            raise ValueError("cannot fit on an empty training split")

        self._seed_everything()
        if self._model is None:
            self._load_backbone()

        # Train on the same windows inference scores.  Truncating training to
        # the first 256 tokens while inference takes the maximum over
        # overlapping windows means the model is never shown a payload that
        # sits in the middle or at the end of a long document -- exactly the
        # positions the corpus varies on purpose.  Each window inherits its
        # record's label, which is noisy for long positives (some windows hold
        # no payload) and is the accepted cost of multiple-instance training at
        # this scale.
        examples = build_examples(
            records, windower=self._windows, window_training=self.config.window_training
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
            weight=torch.tensor(weights, dtype=torch.float, device=self.config.device)
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
                batch = {key: value.to(self.config.device) for key, value in batch.items()}
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
        torch, _ = _require_torch()
        if self._model is None:
            raise RuntimeError("transformer must be fitted or loaded before scoring")
        if not records:
            return np.zeros(0, dtype=float)

        scores = np.zeros(len(records), dtype=float)
        self._model.eval()
        with torch.no_grad():
            for index, record in enumerate(records):
                windows = self._windows(record.text)
                encoded = self._tokenizer(
                    windows,
                    truncation=True,
                    max_length=self.config.max_length,
                    padding=True,
                    return_tensors="pt",
                ).to(self.config.device)
                probabilities = torch.softmax(self._model(**encoded).logits, dim=-1)[:, 1]
                # Max over windows: one malicious sentence must not be averaged
                # away by the clean remainder of a long document.
                scores[index] = float(probabilities.max().item())
        return scores

    def _windows(self, text: str) -> list[str]:
        """Split long text into overlapping windows of whole tokens."""

        ids = self._tokenizer(text, add_special_tokens=False)["input_ids"]
        budget = self.config.max_length - 2  # room for the special tokens
        if len(ids) <= budget:
            return [text]
        step = max(1, budget - self.config.stride)
        windows = [
            self._tokenizer.decode(ids[start : start + budget])
            for start in range(0, len(ids), step)
        ][: self.config.max_windows]
        return windows or [text]

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
            "parameters": parameters,
            "trained": self._trained,
        }
