"""LLMSentinel: provenance-aware detection and capability gating for indirect prompt injection.

The package is layered so that every stage can be used, tested and evaluated alone:

``llmsentinel.schema``      unified corpus record definition and JSONL I/O
``llmsentinel.normalize``   provenance-preserving normalisation of text and JSON
``llmsentinel.rules``       high-precision linguistic rule engine
``llmsentinel.models``      baselines, optional transformer, calibrated fusion
``llmsentinel.evaluation``  metrics, harness, robustness, ablation, reporting
``llmsentinel.policy``      deterministic capability gate over proposed tool actions
``llmsentinel.detector``    the end-to-end guard that produces a :class:`Verdict`

Only the ``llmsentinel.models.transformer`` module needs PyTorch; everything else
runs on numpy and scikit-learn.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
