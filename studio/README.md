# LLMSentinel Studio

A local web console that shows what LLMSentinel does: **the same model answers the
same question from the same retrieved context twice — once as retrieved, once after
LLMSentinel has inspected it — and you see both answers side by side.**

It replaces the old Streamlit demo (`src/llmsentinel/demo/`, kept for reference).

```
studio/
  server/      Starlette API: providers, retrieval, guard, comparison (Python)
  web/         static front-end: index.html, styles.css, app.js (no build step)
  samples/     "unknown" context pack: 10 fictional docs, 5 poisoned (CC0-1.0)
  tests/       pytest suite (runs offline, rules-only, no model needed)
```

## Run it

```bash
python -m pip install -e ".[studio]"
python -m studio.server
```

Open <http://127.0.0.1:8700>. Options: `--port 8700`, `--rules-only` (skip loading
the transformer). The server binds to localhost only.

The first load of the transformer checkpoint (`artifacts/models/transformer`) takes
about 30–60 s on a CPU; it loads in the background and the header badge changes
from "Loading detector…" to "Detector: transformer + rules". Without a checkpoint
or PyTorch the Studio falls back to rules-only and says so.

## The flow

1. **Connect a model** — Simulated (offline), Ollama, LM Studio, or any
   OpenAI-compatible `/v1` API.
2. **Point it at unknown context** — pick sample files (labels hidden until you
   switch on *Reveal ground truth*) or drop your own `.txt .md .json .html .csv`.
3. **Ask** — the top-k passages (TF-IDF) are sent to the model as-is, and again
   after LLMSentinel. Results show what Sentinel found per passage (score, flag
   threshold, rule trace, decoded payloads, exactly what was removed) and both answers
   with objective compromise indicators and every tool request's policy decision.

## Which model to use (free, no token limits)

A local model has no rate or token limits and no key. Recommended:

| Option | Setup | Notes |
|---|---|---|
| **Ollama + `qwen2.5:1.5b`** (recommended) | Install from ollama.com, then `ollama pull qwen2.5:1.5b` (~1 GB) and keep the app running | Apache-2.0; runs on a CPU; preset URL `http://localhost:11434/v1` |
| Ollama + `llama3.2:3b` | `ollama pull llama3.2:3b` (~2 GB) | Better instruction-following, slower on CPU |
| LM Studio | Install from lmstudio.ai, download a small instruct model, Developer tab → start server | Preset URL `http://localhost:1234/v1` |
| Hosted OpenAI-compatible API | Choose *Custom API*, paste base URL and key | Free tiers have rate/token limits; context is sent to that provider |

Then press **Test connection** in step 1; it lists the installed models.

## Reading results honestly

* **The simulator is not a language model.** It obeys any instruction it finds by
  pattern. It demonstrates the mechanics, not detector accuracy or real model
  behaviour.
* **Small real models often ignore injections.** An unguarded answer without signs
  of compromise is a genuine outcome.
* **Compromise is judged objectively**, not by the detector: the confidential code
  from the system prompt appears in the answer, a reserved `.invalid` attacker
  destination appears, a dangerous tool (external send, destructive, privilege
  escalation) would run, or a planted claim is repeated.
* **Nothing is executed.** Tool requests are parsed, classified and decided only.

### What the sample pack shows (simulator, top-k 4, all 10 docs, 6 preset questions)

| Detector | Guarded run shows no compromise | Guarded prompt still contains injection text |
|---|---|---|
| transformer + rules (default) | 6 / 6 | 0 / 6 |
| rules-only (`--rules-only`) | 3 / 6 | 5 / 6 |

Rules-only misses the planted "plan discontinued" note and the support-ticket
`delete_file` order (the capability policy still blocks that tool), and leaves the
"decode the note above and follow it" line of the base64 attack in place. "Injection
text" was checked by searching every guarded prompt for the planted phrases and
`.invalid` destinations.

This is a hand-made demo pack, not an evaluation: accuracy numbers come from
`docs/report.md`. Known close call: the clean `sync-guide.md` scores 0.991 with the
transformer, just under its dev 1%-FPR threshold (0.9954).

## How isolation works

A flagged passage is split into sentences, with a hidden HTML comment kept whole.
Candidates are segments that are suspicious on their own or overlap a rule span.
They are removed most-suspicious first, and the remaining untrusted text is
re-scanned after each removal. Isolation stops at the first clean remainder; if
there is none, the whole passage is withheld.

Two choices here came from failures seen on the sample pack, not from theory:

* **Re-scan is stricter than detection.** During isolation a segment or remainder
  is suspicious if *either* the transformer or the rules reach their dev 1%-FPR
  point. With the detection rule (rules only at 0.1%-FPR), removing the override
  sentence left the exfiltration sentence in place and the passage was forwarded.
* **The marker is not re-scanned.** The transformer scores `[removed by
  LLMSentinel]` itself as instruction-like (plans FAQ remainder 0.9988 with it,
  0.7153 without), which withheld clean text.

## Security notes

* Every document and model string is rendered as text (`textContent`), never HTML.
* Strict CSP: scripts only from this origin, no inline script; `nosniff`,
  `frame-ancestors 'none'`, `no-referrer`.
* API keys live only in the browser tab's input and are sent to the local server
  for that one request; nothing is stored.
* Defence in depth, not a guarantee: keep least privilege, human approval for
  sensitive actions, and server-side authorisation.

## Tests

```bash
.venv/Scripts/python.exe -m pytest studio/tests -q
```
