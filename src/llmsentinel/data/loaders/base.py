"""Loader interface.

Every source dataset is wrapped in a loader that answers three questions:

* **Is it here?** (:meth:`Loader.available`) -- external benchmarks require a
  download, so the build must degrade to the sources that are actually present
  instead of failing.
* **What is it?** (:attr:`Loader.spec`) -- name, homepage, licence and citation,
  recorded in the corpus card for every record it produced.
* **What does it contain?** (:meth:`Loader.load`) -- an iterator of validated
  :class:`~llmsentinel.schema.CorpusRecord` objects.

A loader never writes files, never shuffles, and never assigns splits: the build
command owns all three so that the split seed applies to the whole corpus at
once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ...schema import CorpusRecord

__all__ = ["Loader", "SourceSpec"]


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Provenance for one data source, reproduced verbatim in the corpus card."""

    name: str
    homepage: str
    license: str
    citation: str
    #: What has to be present on disk for the loader to run, described for humans.
    acquisition: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "homepage": self.homepage,
            "license": self.license,
            "citation": self.citation,
            "acquisition": self.acquisition,
            "notes": self.notes,
        }


class Loader(ABC):
    """Base class for corpus loaders."""

    spec: SourceSpec

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else None

    @abstractmethod
    def available(self) -> bool:
        """True when this loader can run right now."""

    @abstractmethod
    def load(self) -> Iterator[CorpusRecord]:
        """Yield validated records.  Must not assign splits."""

    # ------------------------------------------------------------------ misc
    def unavailable_reason(self) -> str:
        """Human-readable explanation shown when the source is skipped."""

        return f"{self.spec.name}: not found. {self.spec.acquisition}".strip()

    def __repr__(self) -> str:  # pragma: no cover - display helper
        return f"<{type(self).__name__} source={self.spec.name!r} available={self.available()}>"
