"""Starlette application for LLMSentinel Studio.

Local-only by design: it binds 127.0.0.1 by default, serves a strict
Content-Security-Policy (scripts only from this origin, no inline script or style
attributes), and the front-end renders every model and document string as text,
never as HTML -- the documents being inspected are hostile by assumption.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from llmsentinel.analyst import LABELS, STATS_KEYS, ScanFilter, ScanStore, promote_to_fixture

from .agent import run_comparison
from .config import (
    MAX_ANSWER_TOKENS,
    MAX_QUESTION_CHARS,
    MAX_UPLOADS,
    MIN_ANSWER_TOKENS,
    PROVIDER_PRESETS,
    UPLOAD_KINDS,
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
from .retrieval import RETRIEVERS

__all__ = ["CSP", "create_app", "make_provider"]

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
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


_FILTER_KEYS = ("kind", "channel", "tool", "server", "source", "source_domain", "family", "action_class", "decision", "band", "since")


def _scan_filter(request: Request) -> ScanFilter:
    params = request.query_params
    values: dict[str, Any] = {key: params.get(key) or None for key in _FILTER_KEYS}
    for key in ("flagged", "reviewed"):
        value = params.get(key)
        values[key] = None if value in (None, "", "any") else value in ("1", "yes", "true")
    return ScanFilter(**values)


def _limit(request: Request, default: int = 100) -> int:
    try:
        return max(1, min(500, int(request.query_params.get("limit") or default)))
    except ValueError:
        return default


def _summary_row(record: Any) -> dict[str, Any]:
    data = record.to_dict()
    data.pop("text", None)  # lists carry the excerpt; the full text is served per scan
    return data


def create_app(settings: StudioSettings | None = None) -> Any:
    settings = settings or StudioSettings()
    samples, questions, pack = load_samples()
    manifest_samples = load_manifest_samples()
    profiles = load_model_profiles()
    state: dict[str, Any] = {}
    lock = asyncio.Lock()
    store = ScanStore(settings.history_path) if settings.record_history else None

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
                "limits": {
                    "max_uploads": MAX_UPLOADS,
                    "max_question_chars": MAX_QUESTION_CHARS,
                    "upload_kinds": list(UPLOAD_KINDS),
                },
                "retrieval": {"options": list(RETRIEVERS), "default": settings.retriever},
                "history": {"enabled": store is not None, "labels": list(LABELS), "stats_keys": sorted(STATS_KEYS)},
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
                kind = str(upload.get("kind") or "auto")
                if kind not in UPLOAD_KINDS:
                    return _bad(f"{name}: unknown kind {kind!r}.", f"Use one of: {', '.join(UPLOAD_KINDS)}.")
                # "auto" is what a dropped file gets: a JSON file with a top-level
                # "tools" list is an MCP manifest, anything else is a document.
                # Pasted text says what it is, so a tool result that happens to
                # carry a "tools" list is not mistaken for a manifest.
                if kind == "manifest" or (kind == "auto" and name.lower().endswith(".json") and is_manifest_json(content)):
                    if not is_manifest_json(content):
                        return _bad(f"{name}: this is not a tool manifest.", 'A manifest is a JSON object with a top-level "tools" list.')
                    manifests.append(manifest_from_upload(name, content))
                else:
                    channel = "tool_response" if kind == "tool_response" else None
                    documents.append(document_from_upload(name, content, channel))
        except ContextError as exc:
            return _bad(str(exc))
        if not documents and not manifests:
            return _bad("Select at least one document or tool manifest, or upload a file.")

        # Uploaded manifests carry no approved snapshot of their own. When an analyst has
        # approved that server, its pins are the snapshot, so drift is detected; either
        # way, the store raises alerts for unapproved or changed tools.
        manifest_alerts = []
        if store is not None:
            for index, manifest in enumerate(manifests):
                if manifest.origin != "upload":
                    continue
                pins = store.current_pins(manifest.server)
                if pins:
                    approved = tuple(pin["declaration"] for pin in pins.values() if pin["declaration"])
                    manifests[index] = replace(manifest, approved=approved)
                manifest_alerts += [alert.to_dict() for alert in store.check_manifest(manifest.server, list(manifest.tools))]

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

        retriever = str(body.get("retriever") or settings.retriever)
        if retriever not in RETRIEVERS:
            return _bad(f"Unknown retriever {retriever!r}.", f"Use one of: {', '.join(RETRIEVERS)}.")

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
                store=store,
                retriever=retriever,
            )
        except ContextError as exc:
            return _bad(str(exc))
        result["history"]["alerts"] = manifest_alerts
        return JSONResponse(result)

    # ------------------------------------------------------------ analyst
    def _history_off() -> JSONResponse:
        return _bad("History is disabled for this session.", "Start the Studio without --no-history.", status=404)

    async def analyst_summary(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        return JSONResponse({**store.summary(), "path": str(store.path.name)})

    async def analyst_scans(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        filters = _scan_filter(request)
        records = store.list(filters, limit=_limit(request))
        return JSONResponse({"items": [_summary_row(r) for r in records], "total": store.count(filters)})

    async def analyst_queue(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        return JSONResponse({"items": [_summary_row(r) for r in store.queue(_scan_filter(request), limit=_limit(request))]})

    async def analyst_scan(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        scan_id = request.path_params["scan_id"]
        record = store.get(scan_id)
        if record is None:
            return _bad("Scan not found.", status=404)
        return JSONResponse(
            {
                "scan": record.to_dict(),
                "overrides": [item.to_dict() for item in store.overrides(scan_id)],
                "effective_label": store.effective_label(scan_id),
                "detector_label": "injection" if record.flagged else "benign",
            }
        )

    async def analyst_override(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        body = await _json(request)
        try:
            item = store.override(
                request.path_params["scan_id"],
                label=str(body.get("label") or ""),
                reviewer=str(body.get("reviewer") or ""),
                rationale=str(body.get("rationale") or ""),
            )
        except KeyError:
            return _bad("Scan not found.", status=404)
        except ValueError as exc:
            return _bad(str(exc))
        return JSONResponse({"override": item.to_dict(), "effective_label": store.effective_label(item.scan_id)})

    async def analyst_promote(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        body = await _json(request)
        try:
            fixture = promote_to_fixture(store, request.path_params["scan_id"], promoted_by=str(body.get("by") or ""))
        except KeyError:
            return _bad("Scan not found.", status=404)
        except ValueError as exc:
            return _bad(str(exc))
        return JSONResponse({"fixture": {k: fixture[k] for k in ("id", "label", "rule_score", "sanitisation")}})

    async def analyst_stats(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        by = request.query_params.get("by") or "family"
        try:
            rows = store.stats(by, _scan_filter(request), limit=_limit(request, 50))
        except ValueError as exc:
            return _bad(str(exc))
        return JSONResponse({"by": by, "rows": rows})

    async def analyst_alerts(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        alerts = store.open_alerts(request.query_params.get("server") or None)
        return JSONResponse({"items": [{**a.to_dict(), "description": a.describe()} for a in alerts]})

    async def analyst_ack(request: Request) -> JSONResponse:
        if store is None:
            return _history_off()
        body = await _json(request)
        try:
            store.acknowledge(request.path_params["alert_id"], acknowledged_by=str(body.get("by") or ""), note=str(body.get("note") or ""))
        except KeyError:
            return _bad("Alert not found.", status=404)
        except ValueError as exc:
            return _bad(str(exc))
        return JSONResponse({"ok": True})

    async def analyst_approve(request: Request) -> JSONResponse:
        """Pin the tools seen in the latest comparison that included this server."""

        if store is None:
            return _history_off()
        server = request.path_params["server"]
        body = await _json(request)
        latest = store.list(ScanFilter(kind="manifest", server=server), limit=1)
        if not latest:
            return _bad("No manifest scans for this server yet.", "Run a comparison that includes it first.", status=404)
        batch = latest[0].versions.get("batch")
        records = [r for r in store.list(ScanFilter(kind="manifest", server=server), limit=500) if r.versions.get("batch") == batch]
        tools = [json.loads(r.text) for r in records if r.text]
        try:
            pinned = store.approve_manifest(server, tools, approved_by=str(body.get("by") or ""))
        except ValueError as exc:
            return _bad(str(exc))
        return JSONResponse({"server": server, "pinned": sorted(pinned)})

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
        Route("/api/analyst/summary", analyst_summary),
        Route("/api/analyst/scans", analyst_scans),
        Route("/api/analyst/queue", analyst_queue),
        Route("/api/analyst/scans/{scan_id}", analyst_scan),
        Route("/api/analyst/scans/{scan_id}/override", analyst_override, methods=["POST"]),
        Route("/api/analyst/scans/{scan_id}/promote", analyst_promote, methods=["POST"]),
        Route("/api/analyst/stats", analyst_stats),
        Route("/api/analyst/alerts", analyst_alerts),
        Route("/api/analyst/alerts/{alert_id}/ack", analyst_ack, methods=["POST"]),
        Route("/api/analyst/manifests/{server}/approve", analyst_approve, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(WEB_DIR), html=True), name="web"),
    ]
    return SecurityHeaders(Starlette(routes=routes, lifespan=lifespan))
