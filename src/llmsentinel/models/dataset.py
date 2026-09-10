"""Training dataset and collation for the transformer detector.

Split out of the trainer for three reasons that matter to the protocol:

* **The windowing is testable on its own.** Expanding a record into overlapping
  windows is the step that decides what the model ever sees; it should be
  assertable without starting a 25-minute training run.
* **Batching is reproducible.** A ``DataLoader`` seeded from a generator gives
  the same batch order for the same seed, which is what makes the three-seed
  variance run meaningful -- the only thing varying between runs is the seed.
* **Padding happens per batch, not per corpus.** The collator pads to the
  longest sequence in the batch, so short tool-response leaves do not carry the
  cost of the longest document in the split.

Torch is imported lazily so that importing :mod:`llmsentinel.models` on a
machine without the optional extra still works.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..schema import CorpusRecord

__all__ = ["WindowExample", "build_examples", "make_dataloader"]

#: Characters of an injected span used to locate it inside a window. A short,
#: whitespace-normalised prefix is robust to the tokenizer's decode spacing.
_SPAN_PROBE_CHARS = 40


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _positive_window_labels(record: CorpusRecord, windows: Sequence[str]) -> list[int]:
    """Label each window of a positive record 1 only if it carries the payload.

    Uses the injected-span text (a normalised prefix) to decide which windows
    actually contain the instruction, so a clean window of a long positive is
    not taught as an injection. Falls back to the document label for the whole
    record when it has no spans, or when no window matches (a match failure must
    not silently turn a positive record into an all-negative one).
    """

    if not record.injected_spans:
        return [1] * len(windows)

    probes = []
    for span in record.injected_spans:
        raw = record.text_for_field(span.field) or record.raw_text
        probe = _norm(span.slice(raw))[:_SPAN_PROBE_CHARS]
        if probe:
            probes.append(probe)
    if not probes:
        return [1] * len(windows)

    labels = [1 if any(p in _norm(w) for p in probes) else 0 for w in windows]
    return labels if any(labels) else [1] * len(windows)


@dataclass(frozen=True, slots=True)
class WindowExample:
    """One training item: a window of text plus the label of its record.

    ``record_id`` is carried so a training item can always be traced back to the
    record it came from. With span-aware labelling the label is assigned per
    window (1 only where the injected span lands); without span information it
    falls back to the record's document label.
    """

    text: str
    label: int
    record_id: str
    window_index: int = 0
    window_count: int = 1

    @property
    def is_partial(self) -> bool:
        """True when the record was split, so this label may be noisy."""

        return self.window_count > 1


def build_examples(
    records: Sequence[CorpusRecord],
    *,
    windower: Any,
    window_training: bool = True,
    span_aware_labels: bool = True,
) -> list[WindowExample]:
    """Expand records into the windows the model will be trained on.

    ``windower`` is a callable taking text and returning a list of windows --
    in practice ``TransformerScorer._windows``, so training and inference split
    text with exactly the same code rather than two implementations that can
    drift apart.

    With ``span_aware_labels`` (default), a positive record's windows are
    labelled 1 only where the injected span actually lands, so a clean window of
    a long positive is not taught as an injection; records without spans keep the
    document label. Set it ``False`` to reproduce the older all-windows-inherit
    behaviour.
    """

    examples: list[WindowExample] = []
    for record in records:
        windows = windower(record.text) if window_training else [record.text]
        if record.y == 0:
            labels = [0] * len(windows)
        elif span_aware_labels:
            labels = _positive_window_labels(record, windows)
        else:
            labels = [1] * len(windows)
        for index, (window, label) in enumerate(zip(windows, labels, strict=True)):
            examples.append(
                WindowExample(
                    text=window,
                    label=label,
                    record_id=record.record_id,
                    window_index=index,
                    window_count=len(windows),
                )
            )
    return examples


def make_dataloader(
    examples: Sequence[WindowExample],
    tokenizer: Any,
    *,
    batch_size: int,
    max_length: int,
    seed: int,
    shuffle: bool = True,
) -> Any:
    """Build a seeded ``DataLoader`` that yields ready-to-use encoded batches."""

    import torch
    from torch.utils.data import DataLoader, Dataset

    class _WindowDataset(Dataset):
        """Indexable view over the expanded windows."""

        def __init__(self, items: Sequence[WindowExample]) -> None:
            self.items = list(items)

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, index: int) -> WindowExample:
            return self.items[index]

    def collate(batch: list[WindowExample]) -> dict[str, Any]:
        encoded = tokenizer(
            [item.text for item in batch],
            truncation=True,
            max_length=max_length,
            padding=True,
            return_tensors="pt",
        )
        encoded["labels"] = torch.tensor([item.label for item in batch], dtype=torch.long)
        return encoded

    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        _WindowDataset(examples),
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=collate,
        generator=generator if shuffle else None,
        # Single process: the corpus is small, and worker processes would add a
        # second source of non-determinism for no throughput gain on CPU.
        num_workers=0,
    )
