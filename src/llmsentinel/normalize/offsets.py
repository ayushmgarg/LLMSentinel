"""Character-level offset mapping between successive text transformations.

Every normalisation step rewrites the text, but the demo has to highlight the
*original* bytes the user pasted.  An :class:`OffsetMap` records, for each
character of the output, which character of the input produced it, so a span
discovered on normalised text can always be projected back onto the raw text.

The map is deliberately char-level and explicit rather than a diff: it is easy
to compose, easy to test, and cheap at the document sizes this project handles.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["OffsetMap"]


@dataclass(frozen=True, slots=True)
class OffsetMap:
    """Maps output character positions back to input character positions.

    ``source_index[i]`` is the input offset that produced output character
    ``i``.  Deleted input characters simply never appear; inserted output
    characters point at the input position they were inserted before.
    """

    source_index: tuple[int, ...]
    source_length: int

    # ----------------------------------------------------------- constructors
    @classmethod
    def identity(cls, length: int) -> OffsetMap:
        return cls(tuple(range(length)), length)

    @classmethod
    def from_pairs(cls, indices: Sequence[int], source_length: int) -> OffsetMap:
        return cls(tuple(indices), source_length)

    # -------------------------------------------------------------- mapping
    def __len__(self) -> int:
        return len(self.source_index)

    def to_source(self, position: int) -> int:
        """Map a single output position (0..len) to an input position."""

        if position < 0:
            raise IndexError(f"negative position {position}")
        if position >= len(self.source_index):
            return self.source_length
        return self.source_index[position]

    def map_span(self, start: int, end: int) -> tuple[int, int]:
        """Project the half-open output span ``[start, end)`` onto the input.

        The result is the smallest input span covering every input character
        that contributed to the output span.  Empty output spans map to an
        empty input span at the corresponding position.
        """

        if end < start:
            raise ValueError(f"span end {end} before start {start}")
        if start == end:
            pos = self.to_source(start)
            return pos, pos
        clipped_end = min(end, len(self.source_index))
        if start >= len(self.source_index):
            return self.source_length, self.source_length
        contributing = self.source_index[start:clipped_end]
        if not contributing:
            pos = self.to_source(start)
            return pos, pos
        return min(contributing), max(contributing) + 1

    def compose(self, previous: OffsetMap) -> OffsetMap:
        """Compose ``self`` (mid -> out) after ``previous`` (src -> mid).

        ``self`` maps output positions to *previous output* positions;
        ``previous`` maps those to the original source.  The composition maps
        output positions straight to the original source.
        """

        if len(previous.source_index) != self.source_length:
            raise ValueError(
                "cannot compose: this map expects an input of length "
                f"{self.source_length}, previous produced {len(previous.source_index)}"
            )
        return OffsetMap(
            tuple(previous.to_source(i) for i in self.source_index),
            previous.source_length,
        )
