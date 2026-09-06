"""Frozen protocol constants.

These values are part of the research protocol (see ``docs/threat_model.md``).
Changing one invalidates previously logged experiments, so every change must be
accompanied by a bump of :data:`CORPUS_SCHEMA_VERSION` or
:data:`NORMALISATION_VERSION` and a new experiment-log entry.
"""

from __future__ import annotations

from typing import Final

#: Bumped whenever the meaning or set of corpus fields changes.
CORPUS_SCHEMA_VERSION: Final[str] = "1.0"

#: Bumped whenever normalisation output for the same input could change.
NORMALISATION_VERSION: Final[str] = "1.0"

#: Single seed used for splits, model init and any sampling, unless overridden.
#:
#: Selection is auditable and was made on *corpus structure only*: candidate
#: seeds 20250906-20250917 were built and the first was kept that gives every
#: (split, channel) cell at least :data:`llmsentinel.data.build.MIN_POSITIVES_PER_CELL`
#: injection examples, with no records dropped for crossing a group boundary.
#: Seeds that leave a channel without positives in dev or test were rejected
#: because a channel with no positives cannot be calibrated and cannot support a
#: per-channel claim -- with the default 20250906, dev/tool_metadata had none.
#:
#: No model was trained, no score was computed and no metric was consulted while
#: choosing it, so the choice cannot have tuned results. The rejected seeds and
#: their coverage are recorded in docs/EXPERIMENTS.md.
DEFAULT_SEED: Final[int] = 20250909

#: Sentinel used for string-typed fields whose true value is not recoverable
#: from the source dataset. Optional scalar fields use ``None`` (JSON ``null``)
#: instead; see ``docs/corpus_schema.md``.
UNKNOWN: Final[str] = "unknown"

#: Operating points reported for every system, expressed as false-positive rates.
TARGET_FPRS: Final[tuple[float, ...]] = (0.01, 0.001)
