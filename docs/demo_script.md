# Three-minute demo script

For a live walkthrough or a recorded run. Start the page first:

```bash
python scripts/run_demo.py          # http://localhost:8601
# fallback if the UI can't run: python scripts/demo_run.py  (deterministic text)
```

Keep the sidebar visible; each step is one selector change plus **Run analysis**.

## 0:00 — Frame the problem (20s)

> "Agents read untrusted text — web pages, tool results, tool manifests. An
> attacker can hide instructions in that text to make the agent leak data or act.
> LLMSentinel flags those instructions and gates the risky action. It never
> executes anything, and on clean input it stays quiet."

## 0:20 — Clean RAG: the guard is quiet (25s)

- Source **RAG document**, sample **clean**, **Run analysis**.
- Point out: every retrieved passage is **LOW**, nothing flagged, the read-only
  follow-up is **allowed**. "No tax on normal use."

## 0:45 — Poisoned RAG: catch + explain + gate (45s)

- Sample **poisoned**, **Run analysis**.
- Show: the injected paragraph is **highlighted** in the raw text; risk band
  **ELEVATED/HIGH**; the **why** expander lists the rule signals
  (meta-instruction + exfiltration).
- Scroll to the policy panel: **Guard OFF** would call `send_email` unchecked;
  **Guard ON** returns **BLOCK** — "an external send in a high-risk context is
  never allowed, and the user's real question can still be answered from the
  clean passages."

## 1:30 — Poisoned tool response: named JSON path (30s)

- Source **Tool response (JSON)**, sample **poisoned**, **Run analysis**.
- Show the flagged leaf at **`$.results[1].content`** — "we keep the JSON path,
  so a finding points at exactly where in the payload it lives" — and the
  blocked action.

## 2:00 — Manifest drift: the change *is* the signal (35s)

- Source **Tool manifest**, sample **changed_hash**, **Run analysis**.
- The new description reads harmless, but the demo reports **manifest drift**
  against the approved digest and the policy **BLOCKS** using the tool.
  "A silent change to an approved tool is itself the alarm, regardless of the new
  wording."

## 2:35 — Close: honest scope (25s)

- Read the disclaimer: "research prototype, defence in depth, not a guarantee;
  this demo is rules-only for a zero-dependency start, so its numbers are not the
  headline model results — those (transformer 0.958, hybrid 0.950 test AUPRC) are
  in the report. Detector advises; a deterministic policy decides; nothing runs."

## If asked

- **False positives?** Tuned to a low FPR; isolation strips only the flagged
  span; blocking gates the *action*, not the answer. See `docs/robustness.md`.
- **Is it a real model?** Fine-tuned distilroberta plus the rule engine; results
  and reproduction in `docs/report.md` and `docs/EXPERIMENTS.md`.
- **Limitations?** Source/channel confound, single seed, calibration not
  validated — all stated in the report.
