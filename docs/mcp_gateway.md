# MCP gateway

`llmsentinel.gateway` is an MCP server that fronts your other MCP servers. Your
assistant (Claude Desktop, Claude Code, or any MCP client) is configured with the
gateway **only**; the gateway connects to the real servers and decides what reaches the
model and what the model may do.

```
assistant  ──►  LLMSentinel gateway  ──►  your MCP servers (docs, e-mail, files …)
                 │ on connect:  scan every tool manifest, check pins, quarantine
                 │ on a call:   refuse arguments carrying flagged addresses, then the policy
                 │ on a result: scan (JSON by leaf), withhold what is flagged
```

This is enforcement rather than advice: the model never sees a quarantined tool or an
unscanned tool result, so it does not have to cooperate. It is the MCP counterpart of the
OpenAI-compatible proxy (`llmsentinel.proxy`).

## What it does

| Step | Behaviour |
|---|---|
| Connect | Lists each upstream's tools, scans names, descriptions and parameter descriptions, and checks them against the pins in the analyst store. A flagged tool, or one that changed after approval, is **quarantined**: never listed, refused if called. |
| Tool names | Exposed as `<server>__<tool>`, so tools from different servers never collide. |
| Before a call | Arguments carrying a URL or address taken from text the guard flagged are **refused**. Then the capability policy decides from the tool's class and the riskiest result seen in the session: `allow`/`isolate` proceed, `block` is refused, and `confirm` is refused unless `--client-confirms` is set. |
| After a call | The result is scanned; a flagged result is **withheld** and replaced by a notice naming the flagged JSON paths. |
| Record | Scans and decisions go to the analyst history (`llmsentinel history …`), unless `--no-history`. |

`--client-confirms` lets `confirm` outcomes proceed on the grounds that the client asks
the user before each tool call, as Claude Desktop and Claude Code do by default. It is
off by default: if the user has told the client to always allow a tool, nobody is
confirming anything.

## Try it with the demo server

`examples/gateway/demo_upstream.py` is a small help-desk MCP server with a knowledge-base
search (one article carries an injection), an e-mail tool, and a tool whose own
description is poisoned. From the project folder:

```bash
.venv\Scripts\python.exe -m llmsentinel.gateway --config examples/gateway/gateway.json --detector rules
```

The gateway speaks MCP over stdin/stdout, so it waits for a client rather than printing
anything useful. Connect a client to it (below).

## Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and add the
gateway as the only server. Use **absolute paths**:

```json
{
  "mcpServers": {
    "llmsentinel": {
      "command": "C:/path/to/project/.venv/Scripts/python.exe",
      "args": [
        "-m", "llmsentinel.gateway",
        "--config", "C:/path/to/project/examples/gateway/gateway.json",
        "--client-confirms"
      ],
      "cwd": "C:/path/to/project"
    }
  }
}
```

and in `gateway.json` give each upstream server an absolute command and path as well.
Restart Claude Desktop; the tools appear as `helpdesk__kb_search` and
`helpdesk__send_email`, and `fast_mailer` does not appear at all.

## Claude Code

```bash
claude mcp add llmsentinel -- C:/path/to/project/.venv/Scripts/python.exe -m llmsentinel.gateway --config C:/path/to/project/examples/gateway/gateway.json
```

## Verified

- `tests/test_gateway.py` (7 tests) runs the gateway against an in-process upstream
  through the real MCP client and server code: quarantine of a poisoned description,
  withholding of a poisoned result, refusal of an external send after it, the policy
  block, both `confirm` modes, and a full client round-trip.
- A stdio run with the gateway and the demo server as separate processes (rules-only):
  the poisoned tool was not listed, the clean search passed unchanged, the poisoned
  search was withheld at `$.results[0].body`, and `send_email` to the address from that
  result was refused before it reached the upstream server.

## Limits

- **Demo-grade.** Local stdio only, no authentication, one user.
- **Only MCP traffic is covered.** Text the client fetches itself — built-in web search,
  files pasted into the chat — never passes through the gateway.
- **Detection limits apply.** The gateway inherits the detector's measured weaknesses
  (paraphrased and soft-claim injections, threshold transfer; see
  `docs/fresh_evaluation.md`). The policy and the argument check are what hold when
  detection misses.
- **The session context only rises.** Once a risky result has been seen, sensitive and
  external-send calls stay refused for the rest of the session; restart the client to
  reset it.
