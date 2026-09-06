"""High-precision linguistic rules over normalised, provenance-tagged text."""

from __future__ import annotations

from .action import DestructiveActionRule, ToolInvocationRule
from .base import Rule, RuleError, RuleFamily, RuleHit, RuleReport
from .context import ContextIndex, Suppression
from .engine import RuleEngine, RuleEngineConfig, default_rules
from .exfiltration import ExfiltrationRule
from .meta_instruction import AssistantAddressRule, MetaInstructionRule, SecrecyRule
from .metadata import (
    ManifestDiff,
    ManifestPin,
    ToolMetadataRule,
    diff_manifest,
    manifest_hash,
    scan_tool_declaration,
)
from .obfuscation import ObfuscationRule
from .pattern_rule import PatternRule
from .task_conflict import TaskConflictRule, topical_overlap

__all__ = [
    "AssistantAddressRule",
    "ContextIndex",
    "DestructiveActionRule",
    "ExfiltrationRule",
    "ManifestDiff",
    "ManifestPin",
    "MetaInstructionRule",
    "ObfuscationRule",
    "PatternRule",
    "Rule",
    "RuleEngine",
    "RuleEngineConfig",
    "RuleError",
    "RuleFamily",
    "RuleHit",
    "RuleReport",
    "SecrecyRule",
    "Suppression",
    "TaskConflictRule",
    "ToolInvocationRule",
    "ToolMetadataRule",
    "default_rules",
    "diff_manifest",
    "manifest_hash",
    "scan_tool_declaration",
    "topical_overlap",
]
