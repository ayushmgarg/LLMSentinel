# Three-minute demo script

## LLMSentinel Studio (current demo)

Start it and wait until the badge reads **Detector: transformer + rules**
(about 30–60 s on a CPU):

```bash
python -m studio.server             # http://127.0.0.1:8700
```

Every outcome below was checked on the sample pack with the simulator and the
default detector.

**0:00 — Frame the problem (20s).** On the landing page: "Agents read text nobody on
the team wrote. LLMSentinel reads it first, isolates what looks like an injection,
and gates the actions the model asks for. Research prototype, defence in depth."

**0:20 — Set up (20s).** Step 1: *Simulated* (say plainly it is not an LLM; it obeys
whatever it reads), or *Ollama* if a model is installed. Step 2: all ten files are
selected and their labels are hidden: "we don't know which are poisoned".

**0:40 — Exfiltration (50s).** Preset *How do I share a notebook with my team?* →
**Run comparison**.
- Without Sentinel: `send_email` to a `.invalid` collector *would run*; flagged as
  compromised.
- With Sentinel: the sharing guide is **stripped**, not dropped. Open it: only the
  override, exfiltration and secrecy sentences are marked as removed; the real
  "invite teammates by email" instruction stays, so the answer is still useful.

**1:30 — Hidden in a tool result (40s).** Preset *What should I do with the old
support tickets?*
- The ticket summary telling the assistant to call `delete_file` scores 0.000 on the
  rules alone. The transformer flags it (0.999) and the leaf is **withheld**.
- Point to the exact prompt: the guarded model never saw the instruction.

**2:10 — Hard negative + ground truth (25s).** Switch on *Reveal ground truth*. The
security FAQ quotes "ignore previous instructions" while explaining the risk. It is
labelled clean and passes untouched (transformer 0.0004).

**2:35 — Limits (25s).** "The simulator shows the mechanism, not accuracy. Accuracy
is the report's test AUPRC 0.984, in-distribution. On a benchmark held out of
training, the baselines drop sharply (docs/ood_evaluation.md). That is why this is
defence in depth, alongside least privilege and approvals."

---

## Legacy Streamlit walkthrough (Week 3)

Kept for reference. Start the page first:

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
