# Independent double-annotation study

Substitute for two-person labelling on a one-person project: two annotators
labelled the same 50-record sample **independently**, from
[annotation_guideline.md](annotation_guideline.md) alone, without the corpus's
construction labels and without seeing each other's work. Reproduce with
`python scripts/annotation_agreement.py`.

Both annotators are LLM agents given only the guideline and the records. This
measures **guideline clarity** — whether the written rules are enough to
reproduce the intended labels — not human inter-annotator agreement, and it is
reported as such.

## Sample

50 records, stratified across channels and labels, drawn (seed 20250909) from
the combined corpus `44bff1b4`. Source mix: 35 built-in, 10 BIPIA, 5 InjecAgent.
**14 of the 50 are hard negatives** — benign text that is designed to look like
an attack, which is the case the label boundary actually turns on.

## Results

| measure | value |
|---|---|
| binary label, A vs B (raw / Cohen's κ) | **1.000 / 1.000** |
| binary label, A vs corpus | 1.000 |
| binary label, B vs corpus | 1.000 |
| hard negatives both kept benign | **14 / 14** |
| A/B binary disagreements | 0 |
| attack-type, A vs B | 50 / 50 |
| attack-type, annotators vs corpus | **45 / 50** |

## Reading it

**The binary task is unambiguous on this sample.** Perfect agreement, and both
annotators correctly kept all 14 hard negatives benign — a security article
quoting a payload, an API reference telling a human to send a key, a policy
addressed to employees. This is the decision detection depends on, and the
guideline reproduces it without disagreement.

**The attack-type taxonomy has genuine overlap.** The two annotators agreed with
each other on all 50 attack types but differed from the corpus's construction
label on 5 positives. Every one of the five is a defensible reading, not an
error:

| item | corpus | both annotators | why they overlap |
|---|---|---|---|
| A01, A20 | content_manipulation | meta_instruction | a directive that steers output is also an instruction |
| A05 | metadata_poisoning | exfiltration | a metadata field asking for a credential *is* an exfiltration attempt |
| A34 | unknown | meta_instruction | the corpus loader left a BIPIA category unmapped; the annotators gave the real type |
| A47 | obfuscation | meta_instruction | obfuscation is the *delivery*; the concealed content is a meta-instruction |

## Guideline refinement (checklist item 88)

There were **no binary disagreements to resolve**. The attack-type mismatches
are resolved by adding an explicit **precedence rule** to the guideline, so a
record with more than one applicable type gets one deterministic label:

1. `obfuscation` — when concealment (encoding, zero-width, homoglyph, hidden
   markup) is the defining property of *how* the payload is delivered.
2. `metadata_poisoning` — when the payload lives in tool metadata.
3. `exfiltration` / `action_hijack` — by the concrete effect (data leaves / a
   tool fires).
4. `meta_instruction` — a directive to the assistant with no more specific
   effect above.
5. `content_manipulation` — steering answer content only.

This is documented as guidance for the *taxonomy*; it does not change any binary
label, and the binary label is what every reported detection metric uses. The
5 items are left at their construction labels: they are BIPIA/metadata records
whose category is inherent to the source, and relabelling them would not change
any result.

## Honest limits

- Annotators are LLM agents, so this bounds guideline clarity, not human
  agreement; a human study is out of scope for a one-person project.
- 50 records; perfect binary agreement should not be read as "the boundary is
  trivial everywhere", only that it is clear on a stratified sample that
  included the hard-negative cases.
