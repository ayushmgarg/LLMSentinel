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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..schema import CorpusRecord

__all__ = ["WindowExample", "build_examples", "make_dataloader"]


@dataclass(frozen=True, slots=True)
class WindowExample:
    """One training item: a window of text plus the label of its record.

    ``record_id`` is carried so a training item can always be traced back to the
    record it came from -- the label is inherited, and for a long positive some
    windows may contain no payload at all.
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
) -> list[WindowExample]:
    """Expand records into the windows the model will be trained on.

    ``windower`` is a callable taking text and returning a list of windows --
    in practice ``TransformerScorer._windows``, so training and inference split
    text with exactly the same code rather than two implementations that can
    drift apart.
    """

    examples: list[WindowExample] = []
    for record in records:
        windows = windower(record.text) if window_training else [record.text]
        for index, window in enumerate(windows):
            examples.append(
                WindowExample(
                    text=window,
                    label=record.y,
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
