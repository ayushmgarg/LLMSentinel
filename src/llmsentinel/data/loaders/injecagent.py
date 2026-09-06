"""InjecAgent loader (tool-response channel).

Expected layout (after cloning into ``data/raw/injecagent``)::

    data/raw/injecagent/
        data/
            test_cases_dh_base.json     # direct-harm cases
            test_cases_ds_base.json     # data-stealing cases
            attacker_cases_*.json
            tools.json

Each case carries a *user* instruction, an *attacker* instruction, and a tool
response template into which the attacker instruction is spliced.  That template
is exactly what our guard sees at run time, so the loader materialises it: the
benign record is the template with the placeholder removed, and the positive
record is the template with the attacker instruction in place.

If a release stops exposing the response template, the loader reports it as
unavailable instead of inventing text -- the checklist explicitly allows
documenting that extraction is impractical, but not fabricating tool output.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...paths import RAW_DIR
from ...schema import AttackType, Channel, CorpusRecord, Label, Span, make_record_id
from ._io import first_present, iter_records, read_any, walk_data_files
from .base import Loader, SourceSpec

__all__ = ["InjecAgentLoader"]

_SOURCE = "injecagent"

_PLACEHOLDER_RE = re.compile(r"<(?:Attacker\s*Instruction|attacker_instruction)>", re.IGNORECASE)

_TEMPLATE_KEYS = (
    "Tool Response Template",
    "tool_response_template",
    "Tool Response",
    "tool_response",
    "Attacker Tool Response Template",
)


class InjecAgentLoader(Loader):
    spec = SourceSpec(
        name="InjecAgent",
        homepage="https://github.com/uiuc-kang-lab/InjecAgent",
        license="See the repository LICENSE; verify before redistributing any excerpt.",
        citation=(
            "Zhan et al., InjecAgent: Benchmarking Indirect Prompt Injections in "
            "Tool-Integrated Large Language Model Agents."
        ),
        acquisition=(
            "git clone https://github.com/uiuc-kang-lab/InjecAgent into "
            "data/raw/injecagent (the loader reads its data/ directory)."
        ),
        notes=(
            "Only the tool-response text is extracted. The benchmark's agent "
            "execution harness is out of scope for this project."
        ),
    )

    def __init__(self, root: Path | None = None, *, max_records: int = 4000) -> None:
        super().__init__(root or (RAW_DIR / "injecagent"))
        self.max_records = max_records

    # ------------------------------------------------------------ availability
    def available(self) -> bool:
        return bool(self._cases())

    def _cases(self) -> list[dict[str, Any]]:
        if self.root is None or not self.root.is_dir():
            return []
        cases: list[dict[str, Any]] = []
        for path in walk_data_files(self.root):
            if "tool" in path.stem.lower() and "case" not in path.stem.lower():
                continue  # tools.json is the tool registry, not test cases
            try:
                payload = read_any(path)
            except (ValueError, UnicodeDecodeError):
                continue
            for record in iter_records(payload):
                template = first_present(record, *_TEMPLATE_KEYS)
                attacker = first_present(
                    record, "Attacker Instruction", "attacker_instruction", "attack_instruction"
                )
                if isinstance(template, str) and isinstance(attacker, str):
                    record["__file"] = path.stem
                    cases.append(record)
        return cases

    def unavailable_reason(self) -> str:
        if self.root is not None and self.root.is_dir():
            return (
                "InjecAgent: files found but no case exposed both a tool-response "
                "template and an attacker instruction. Inspect the release schema "
                "and update _TEMPLATE_KEYS, or document the source as not usable."
            )
        return super().unavailable_reason()

    # -------------------------------------------------------------------- load
    def load(self) -> Iterator[CorpusRecord]:
        emitted = 0
        for case in self._cases():
            if emitted >= self.max_records:
                return
            template = str(first_present(case, *_TEMPLATE_KEYS) or "")
            attacker = str(
                first_present(
                    case, "Attacker Instruction", "attacker_instruction", "attack_instruction"
                )
                or ""
            ).strip()
            user_task = first_present(case, "User Instruction", "user_instruction", "user_task")
            tool_name = str(
                first_present(case, "User Tool", "user_tool", "Attacker Tools", "attacker_tools")
                or "unknown_tool"
            )
            if isinstance(tool_name, list):
                tool_name = ",".join(str(item) for item in tool_name)

            group = _case_group(case, template)
            benign_text = _PLACEHOLDER_RE.sub("", template).strip()
            if len(benign_text) >= 40:
                yield CorpusRecord(
                    record_id=make_record_id(_SOURCE, f"clean/{group}"),
                    source_dataset=_SOURCE,
                    source_document_id=group,
                    source_license=self.spec.license,
                    raw_text=benign_text,
                    label=Label.BENIGN,
                    channel=Channel.TOOL_RESPONSE,
                    host_task=str(user_task) if user_task else None,
                    json_path="$.tool_response",
                    group_id=f"host:{group}",
                    extra={
                        "host_group": f"host:{group}",
                        "tool_name": tool_name,
                        "variant": "clean_host",
                        "file": case.get("__file", ""),
                    },
                )
                emitted += 1

            if not attacker:
                continue
            if _PLACEHOLDER_RE.search(template):
                composed = _PLACEHOLDER_RE.sub(attacker, template)
                index = composed.find(attacker)
            else:
                composed = f"{template.strip()}\n{attacker}"
                index = len(template.strip()) + 1

            spans = (
                [Span(index, index + len(attacker), field="raw_text", note="attacker_instruction")]
                if index >= 0
                else []
            )
            yield CorpusRecord(
                record_id=make_record_id(_SOURCE, f"mix/{group}"),
                source_dataset=_SOURCE,
                source_document_id=group,
                source_license=self.spec.license,
                raw_text=composed,
                label=Label.INJECTION,
                channel=Channel.TOOL_RESPONSE,
                attack_type=_attack_type(case),
                injected_spans=spans,
                host_task=str(user_task) if user_task else None,
                json_path="$.tool_response",
                group_id=f"family:{_attack_family(case, attacker)}",
                extra={
                    "host_group": f"host:{group}",
                    "tool_name": tool_name,
                    "variant": "composed",
                    "file": case.get("__file", ""),
                },
            )
            emitted += 1


def _attack_type(case: dict[str, Any]) -> AttackType:
    marker = f"{case.get('__file', '')} {first_present(case, 'Attacker Tools', 'attack_type') or ''}"
    lowered = str(marker).lower()
    if "_ds" in lowered or "steal" in lowered or "data" in lowered:
        return AttackType.EXFILTRATION
    if "_dh" in lowered or "harm" in lowered:
        return AttackType.ACTION_HIJACK
    return AttackType.UNKNOWN


def _attack_family(case: dict[str, Any], attacker: str) -> str:
    """Group by the attacker's *intent*, not by its surface form.

    InjecAgent reuses one attacker instruction across many user tasks, so
    grouping on the instruction text is what prevents the same payload from
    appearing in both train and test.
    """

    explicit = first_present(case, "Attacker Tools", "attacker_tools", "attack_type")
    if explicit:
        if isinstance(explicit, list):
            explicit = "+".join(str(item) for item in explicit)
        return str(explicit).lower().replace(" ", "_")
    return "instr_" + hashlib.sha1(attacker.lower().encode()).hexdigest()[:10]


def _case_group(case: dict[str, Any], template: str) -> str:
    user_tool = first_present(case, "User Tool", "user_tool") or "tool"
    return f"{user_tool}/{hashlib.sha1(template[:200].encode()).hexdigest()[:10]}"
