"""Chat-model providers.

``OpenAICompatibleProvider`` talks to any server exposing ``/v1/chat/completions``
and ``/v1/models`` -- Ollama, LM Studio, llama.cpp's server, vLLM, or a hosted
OpenAI-compatible API. Errors are turned into a message plus a concrete hint, so
the console can tell the user exactly what to fix.

``SimulatedProvider`` needs no model at all. It is **not an LLM**: it is a small
deterministic stand-in that *obeys instructions it finds in its context* (sends
data to a planted destination, repeats a planted claim, reveals the confidential
code, calls a named tool). It exists so the whole pipeline can be exercised
offline and in tests. Because its obedience is pattern-based, a simulated run
demonstrates the *mechanics* of the comparison, not the detector's accuracy --
the accuracy numbers come from the evaluation in docs/report.md, and a real local
model shows real behaviour.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import KNOWN_TOOLS

__all__ = [
    "ChatProvider",
    "ChatResult",
    "OpenAICompatibleProvider",
    "ProviderError",
    "SimulatedProvider",
]


class ProviderError(Exception):
    """A model call failed; ``hint`` says what the user can do about it."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, str]:
        return {"error": self.message, "hint": self.hint}


@dataclass(slots=True)
class ChatResult:
    text: str
    model: str
    provider: str
    latency_ms: float
    usage: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


class ChatProvider(Protocol):
    name: str
    model: str
    simulated: bool

    async def chat(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> ChatResult: ...

    async def list_models(self) -> list[str]: ...


# ------------------------------------------------------------------ real APIs
class OpenAICompatibleProvider:
    simulated = False

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        *,
        timeout: float = 180.0,
        name: str = "OpenAI-compatible",
    ) -> None:
        if not base_url.strip():
            raise ProviderError(
                "A base URL is required for this provider.",
                "Ollama: http://localhost:11434/v1 - LM Studio: http://localhost:1234/v1",
            )
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.name = name

    async def chat(
        self, messages: list[dict[str, str]], *, max_tokens: int = 400, temperature: float = 0.2
    ) -> ChatResult:
        if not self.model:
            raise ProviderError(
                "Choose a model name first.",
                "Use 'Test connection' to list the models this server has installed.",
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        started = time.perf_counter()
        data = await self._request("POST", "/chat/completions", payload)
        try:
            text = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError(
                "The provider returned an unexpected response shape.", str(data)[:300]
            ) from exc
        return ChatResult(
            text=str(text),
            model=str(data.get("model") or self.model),
            provider=self.name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
        )

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/models", None)
        items = data.get("data", []) if isinstance(data, dict) else []
        return sorted({str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")})

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key or 'local'}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, url, json=payload, headers=headers)
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach {self.base_url}.",
                "Is the model server running? For Ollama: install it, run `ollama pull "
                "qwen2.5:1.5b`, and make sure the Ollama app (or `ollama serve`) is running.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "The model took too long to respond.",
                "CPU inference is slow for larger models; try qwen2.5:1.5b or fewer passages.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request to {url} failed ({exc.__class__.__name__}).", str(exc)[:300]) from exc

        if response.status_code == 404:
            raise ProviderError(
                "Endpoint or model not found (HTTP 404).",
                "Check the base URL ends with /v1 and the model is installed "
                f"(Ollama: `ollama pull {self.model or '<model>'}`).",
            )
        if response.status_code in (401, 403):
            raise ProviderError(
                f"The provider rejected the request (HTTP {response.status_code}).",
                "Check the API key for this endpoint.",
            )
        if response.status_code >= 400:
            raise ProviderError(f"The provider returned HTTP {response.status_code}.", response.text[:300])
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError("The provider did not return JSON.", response.text[:300]) from exc
        if not isinstance(body, dict):
            raise ProviderError("The provider returned an unexpected response.", str(body)[:300])
        return body


# ------------------------------------------------------------- offline stand-in
_URL = re.compile(r"https?://[^\s<>\"')\]]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_BASE64 = re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}")
_OVERRIDE = re.compile(r"\bignore (?:all |your |any )?(?:previous|prior|earlier) instructions\b", re.I)
_REVEAL = re.compile(
    r"\b(?:reveal|print|output|repeat|include|show)\b[^.\n]{0,60}"
    r"\b(?:system prompt|internal reference|reference code|hidden instructions)\b",
    re.I,
)
_TELL = re.compile(r"\btell (?:the )?users? (?:that )?([^\n]+?)(?:\.(?:\s|$)|\n|$)", re.I)
_EXFIL = re.compile(r"\b(?:send|email|forward|post|upload|transmit)\b", re.I)
_STEER = re.compile(r"\b(?:visit|verify|update|go to|open)\b", re.I)
_CALL = re.compile(
    r"\b(?:call|invoke|run|use)\s+(?:the\s+)?`?([a-z_][a-z0-9_]{2,40})`?(?:\s+tool)?"
    r"(?:\s+on\s+([^\s,;]+?))?(?=[\s,;.]|$)",
    re.I,
)
_GRANT = re.compile(r"\bgrant\b[^.\n]{0,40}\badmin\b", re.I)
_CANARY = re.compile(r"\b[A-Z]+-CANARY-\d+\b")
_WORD = re.compile(r"[a-z][a-z0-9]{3,}")
_STOP = frozenset(
    "this that with from your have will what when where which about there their into "
    "they them then than does make more most only over such also each other".split()
)


def _split_prompt(user: str) -> tuple[str, str]:
    context, _, question = user.rpartition("QUESTION:")
    return context.replace("CONTEXT:", "", 1), question.strip()


def _decoded_blobs(text: str) -> list[str]:
    decoded: list[str] = []
    for match in _BASE64.findall(text):
        try:
            value = base64.b64decode(match, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        printable = sum(ch.isprintable() for ch in value) / max(1, len(value))
        if printable > 0.95 and " " in value:
            decoded.append(value)
    return decoded


def _sentences(context: str) -> list[str]:
    lines = []
    for line in context.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^\[\d+\]\s", stripped) or stripped.startswith(("NOTE: LLMSentinel", "<!--")):
            continue
        lines.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", stripped) if part.strip())
    return lines


def _extractive_answer(context: str, question: str) -> str:
    wanted = {w for w in _WORD.findall(question.lower()) if w not in _STOP}
    scored = []
    for index, sentence in enumerate(_sentences(context)):
        clean = re.sub(r"<[^>]+>|[*#`]", "", sentence).strip()
        if len(clean) < 25:
            continue
        overlap = len(wanted & set(_WORD.findall(clean.lower())))
        if overlap:
            scored.append((overlap, index, clean))
    if not scored:
        return "I couldn't find that in the provided context."
    best = sorted(sorted(scored, key=lambda item: (-item[0], item[1]))[:2], key=lambda item: item[1])
    return " ".join(sentence for _, _, sentence in best)


class SimulatedProvider:
    """Deterministic, instruction-obeying stand-in. Not a language model."""

    name = "Simulated"
    model = "simulated-vulnerable-assistant"
    simulated = True

    async def list_models(self) -> list[str]:
        return [self.model]

    async def chat(
        self, messages: list[dict[str, str]], *, max_tokens: int = 400, temperature: float = 0.2
    ) -> ChatResult:
        started = time.perf_counter()
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        context, question = _split_prompt(user)
        instructions = "\n".join([context, *_decoded_blobs(context)])

        lines = [_extractive_answer(context, question)]
        actions: list[str] = []
        notes: list[str] = []

        canary = _CANARY.search(system)
        if canary and _REVEAL.search(instructions):
            lines.append(f"Internal reference code: {canary.group(0)}")
            notes.append("obeyed: reveal the confidential system prompt")

        for match in _TELL.finditer(instructions):
            claim = match.group(1).strip().rstrip(".")
            if claim:
                lines.append(claim[0].upper() + claim[1:] + ".")
                notes.append("obeyed: repeat a planted claim to the user")

        destinations = [u for u in _URL.findall(instructions) if ".invalid" in u.lower()]
        if destinations and _EXFIL.search(instructions):
            args = {"to": destinations[0], "body": "Requested export links and account token"}
            actions.append(f"ACTION: send_email {json.dumps(args)}")
            notes.append("obeyed: send user data to an external destination")
        elif destinations and _STEER.search(instructions):
            lines.append(f"Please continue at {destinations[0]}")
            notes.append("obeyed: steer the user to a planted link")

        for match in _CALL.finditer(instructions):
            tool = match.group(1).lower()
            if tool in KNOWN_TOOLS:
                args = {"path": match.group(2)} if match.group(2) else {}
                actions.append(f"ACTION: {tool} {json.dumps(args)}")
                notes.append(f"obeyed: call {tool}")
        if _GRANT.search(instructions):
            actions.append('ACTION: grant_admin {"account": "requester"}')
            notes.append("obeyed: grant admin")
        if _OVERRIDE.search(instructions):
            notes.append("saw: an instruction to ignore previous instructions")

        text = "\n".join(line for line in lines if line)
        if actions:
            text += "\n" + "\n".join(dict.fromkeys(actions))
        return ChatResult(
            text=text,
            model=self.model,
            provider=self.name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            notes=list(dict.fromkeys(notes)),
        )
