"""Starlette application for LLMSentinel Studio.

Local-only by design: it binds 127.0.0.1 by default, serves a strict
Content-Security-Policy (scripts only from this origin, no inline script or style
attributes), and the front-end renders every model and document string as text,
never as HTML -- the documents being inspected are hostile by assumption.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .agent import run_comparison
from .config import (
    MAX_ANSWER_TOKENS,
    MAX_QUESTION_CHARS,
    MAX_UPLOADS,
    MIN_ANSWER_TOKENS,
    PROVIDER_PRESETS,
    WEB_DIR,
    StudioSettings,
    load_evidence,
    load_model_profiles,
    profile_for,
)
from .context import Chunk, ContextError, document_from_upload, load_samples
from .guard import SentinelGuard
from .manifests import is_manifest_json, load_manifest_samples, manifest_from_upload
from .providers import OpenAICompatibleProvider, ProviderError, SimulatedProvider

__all__ = ["CSP", "create_app", "make_provider"]

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


class SecurityHeaders:
    """Pure ASGI middleware adding security headers to every HTTP response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"content-security-policy", CSP.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def make_provider(config: dict[str, Any], settings: StudioSettings) -> Any:
    kind = str(config.get("kind") or "simulated")
    if kind == "simulated":
        return SimulatedProvider()
    if kind not in PROVIDER_PRESETS:
        raise ProviderError(f"Unknown provider {kind!r}.")
    preset = PROVIDER_PRESETS[kind]
    return OpenAICompatibleProvider(
        str(config.get("base_url") or preset["base_url"]),
        str(config.get("model") or preset["model"]),
        str(config.get("api_key") or ""),
        timeout=settings.request_timeout_s,
        name=preset["label"],
    )


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _bad(message: str, hint: str = "", status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message, "hint": hint}, status_code=status)


def create_app(settings: StudioSettings | None = None) -> Any:
    settings = settings or StudioSettings()
    samples, questions, pack = load_samples()
    manifest_samples = load_manifest_samples()
    profiles = load_model_profiles()
    state: dict[str, Any] = {}
    lock = asyncio.Lock()

    async def guard() -> SentinelGuard:
        async with lock:
            if "guard" not in state:
                state["guard"] = await asyncio.to_thread(SentinelGuard, settings)
        return state["guard"]

    def start_loading() -> asyncio.Task[SentinelGuard]:
        # Loading the transformer takes tens of seconds on a CPU; do it in the
        # background so the page and the sample list are usable immediately.
        task = state.get("task")
        if task is None:
            task = state["task"] = asyncio.create_task(guard())
        return task

    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
        start_loading()
        yield

    def detector_status() -> dict[str, Any]:
        task = start_loading()
        if not task.done():
            return {
                "loading": True,
                "detector": "loading",
                "transformer_loaded": False,
                "notes": ["Loading the detector; the first transformer load can take about a minute on a CPU."],
            }
        if task.exception() is not None:
            state.pop("task", None)
            return {"loading": False, "error": f"The detector failed to load: {task.exception()}"}
        return {"loading": False, **task.result().status()}

    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "detector": detector_status(),
                "presets": PROVIDER_PRESETS,
                "model_profiles": profiles,
                "evidence": load_evidence(settings.results_path.parent),
                "default_max_tokens": settings.max_tokens,
                "questions": questions,
                "pack": pack,
                "limits": {"max_uploads": MAX_UPLOADS, "max_question_chars": MAX_QUESTION_CHARS},
            }
        )

    async def list_samples(request: Request) -> JSONResponse:
        reveal = request.query_params.get("reveal") in ("1", "true", "yes")
        items = []
        for info in samples.values():
            item: dict[str, Any] = {
                "doc_id": info.doc.doc_id,
                "name": info.doc.name,
                "kind": info.doc.kind,
                "chars": len(info.doc.text),
                "preview": " ".join(info.doc.text.split())[:150],
            }
            if reveal:
                item.update({"label": info.label, "attack": info.attack, "note": info.note})
            items.append(item)
        servers = []
        for sample in manifest_samples.values():
            manifest = sample.manifest
            server: dict[str, Any] = {
                "manifest_id": manifest.manifest_id,
                "name": manifest.name,
                "server": manifest.server,
                "tools": [str(tool["name"]) for tool in manifest.tools],
                "pinned": manifest.approved is not None,
            }
            if reveal:
                server.update({"label": sample.label, "attack": sample.attack, "note": sample.note})
            servers.append(server)
        return JSONResponse({"items": items, "manifests": servers, "revealed": reveal})

    async def get_sample(request: Request) -> JSONResponse:
        info = samples.get(request.path_params["doc_id"])
        if info is None:
            return _bad("Sample not found.", status=404)
        return JSONResponse({"doc_id": info.doc.doc_id, "name": info.doc.name, "kind": info.doc.kind, "text": info.doc.text})

    async def models(request: Request) -> JSONResponse:
        body = await _json(request)
        try:
            provider = make_provider(body, settings)
            names = await provider.list_models()
        except ProviderError as exc:
            return JSONResponse({"ok": False, **exc.to_dict()}, status_code=200)
        return JSONResponse({"ok": True, "models": names, "simulated": provider.simulated})

    async def compare(request: Request) -> JSONResponse:
        body = await _json(request)
        question = str(body.get("question") or "").strip()
        if not question:
            return _bad("Ask a question first.")
        if len(question) > MAX_QUESTION_CHARS:
            return _bad(f"Questions are limited to {MAX_QUESTION_CHARS} characters.")

        documents = []
        manifests = []
        canaries: list[str] = []
        for sample_id in body.get("sample_ids") or []:
            info = samples.get(str(sample_id))
            if info is not None:
                documents.append(info.doc)
                canaries.extend(info.canaries)
        for manifest_id in body.get("manifest_ids") or []:
            sample = manifest_samples.get(str(manifest_id))
            if sample is not None:
                manifests.append(sample.manifest)
        uploads = body.get("uploads") or []
        if not isinstance(uploads, list) or len(uploads) > MAX_UPLOADS:
            return _bad(f"Upload at most {MAX_UPLOADS} files.")
        try:
            for upload in uploads:
                if not isinstance(upload, dict):
                    continue
                name, content = str(upload.get("name") or "upload.txt"), str(upload.get("content") or "")
                # A JSON file with a top-level "tools" list is an MCP tool manifest.
                if name.lower().endswith(".json") and is_manifest_json(content):
                    manifests.append(manifest_from_upload(name, content))
                else:
                    documents.append(document_from_upload(name, content))
        except ContextError as exc:
            return _bad(str(exc))
        if not documents and not manifests:
            return _bad("Select at least one document or tool manifest, or upload a file.")

        provider_config = body.get("provider") or {}
        try:
            provider = make_provider(provider_config, settings)
        except ProviderError as exc:
            return _bad(exc.message, exc.hint)
        # Precedence: value sent by the UI, then the model's profile, then the server default.
        profile = profile_for(str(getattr(provider, "model", "") or ""), profiles)
        try:
            top_k = min(8, max(1, int(body.get("top_k") or profile.get("top_k") or settings.top_k)))
        except (TypeError, ValueError):
            top_k = settings.top_k
        try:
            requested = int(body.get("max_tokens") or profile.get("max_tokens") or settings.max_tokens)
            max_tokens = min(MAX_ANSWER_TOKENS, max(MIN_ANSWER_TOKENS, requested))
        except (TypeError, ValueError):
            max_tokens = settings.max_tokens

        sentinel = await guard()
        try:
            result = await run_comparison(
                question=question,
                documents=documents,
                provider=provider,
                guard=sentinel,
                settings=settings,
                top_k=top_k,
                max_tokens=max_tokens,
                canaries=canaries,
                manifests=manifests,
            )
        except ContextError as exc:
            return _bad(str(exc))
        return JSONResponse(result)

    async def scan(request: Request) -> JSONResponse:
        body = await _json(request)
        text = str(body.get("text") or "")
        if not text.strip():
            return _bad("Paste some text to scan.")
        channel = "tool_response" if body.get("channel") == "tool_response" else "rag_document"
        chunk = Chunk("scan#0", "scan", "pasted text", channel, None, text[:20_000], 0)
        sentinel = await guard()
        assessment = (await asyncio.to_thread(sentinel.assess, [(chunk, 1.0)], str(body.get("host_task") or "")))[0]
        return JSONResponse({"detector": sentinel.status(), "assessment": assessment.to_dict()})

    routes = [
        Route("/api/health", health),
        Route("/api/samples", list_samples),
        Route("/api/samples/{doc_id}", get_sample),
        Route("/api/models", models, methods=["POST"]),
        Route("/api/compare", compare, methods=["POST"]),
        Route("/api/scan", scan, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(WEB_DIR), html=True), name="web"),
    ]
    return SecurityHeaders(Starlette(routes=routes, lifespan=lifespan))
