"""FastAPI application entrypoint.

Tier 2 of the six-tier architecture (docs/01) — a control plane, not a
compute plane: research jobs run in a separate worker (docs/06, D-16), never
inline in a request handler.

App wiring, startup-time prompt-repository validation, the health endpoint,
and (docs/16 Phase 1) job creation/status/streaming endpoints — the actual
research run always happens in a separate Celery worker (D-16), never here.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.citation_graph import router as citation_graph_router
from apps.api.routers.jobs import router as jobs_router
from src.core.config import get_settings
from src.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS, render_latest
from src.prompts.loader import PromptLoadError, PromptRepository

PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent / "src" / "prompts"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate the prompt repository at startup — fail the deploy, not the
    first research job that happens to reach an invalid node (docs/16 Phase
    0 checklist, docs/17 D-25).
    """
    try:
        app.state.prompt_repository = PromptRepository(PROMPTS_ROOT)
    except PromptLoadError as exc:
        raise RuntimeError(f"prompt repository failed validation: {exc}") from exc

    yield


app = FastAPI(
    title="JurisMindAI API",
    description="Agentic Legal Research & Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = [
    origin.strip() for origin in get_settings().cors_allowed_origins.split(",") if origin.strip()
]
if _cors_origins:
    # No origins configured -> no CORS headers added, which browsers treat
    # as same-origin-only; explicit opt-in per environment (.env), never a
    # wildcard default (docs/11).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(jobs_router)
app.include_router(citation_graph_router)


@app.middleware("http")
async def _record_request_metrics(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.monotonic()
    response = await call_next(request)
    # The route's *path template* ("/jobs/{job_id}"), not the raw URL — a
    # label built from raw paths would put one unbounded time series per
    # job_id ever requested, exactly the cardinality blowup D-31's label
    # discipline rules out. Route matching has already happened by the time
    # call_next() returns, so it's on the request scope; fall back to the
    # raw path only for a 404 that never matched a route at all.
    route = request.scope.get("route")
    endpoint = route.path if route is not None else request.url.path
    labels = {"service": "api", "endpoint": endpoint, "method": request.method}
    HTTP_REQUEST_DURATION.labels(**labels).observe(time.monotonic() - start)
    HTTP_REQUESTS.labels(**labels, status=str(response.status_code)).inc()
    return response


@app.get("/metrics")
def metrics() -> Response:
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    prompt_repository: PromptRepository = app.state.prompt_repository
    return {
        "status": "ok",
        "environment": settings.environment.value,
        "prompt_nodes_loaded": prompt_repository.nodes(),
    }
