"""Celery application (D-8, D-16) — the job queue research and ingestion
work runs on, never inline in an API request handler (docs/06).

`docker/worker.Dockerfile` already expects this exact module path
(`src.core.celery_app`) and selects a queue via `--queues=research` /
`--queues=ingestion` at deploy time — this module only has to define `app`
with those two queues declared; it does not choose which one a given
deployable consumes.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init
from prometheus_client import start_http_server

from src.core.config import get_settings

settings = get_settings()

app = Celery(
    "tradegraph",
    broker=str(settings.celery_broker_url) if settings.celery_broker_url else None,
    backend=str(settings.celery_result_backend) if settings.celery_result_backend else None,
    include=["src.graph.tasks"],
)

app.conf.task_routes = {
    "tradegraph.research.*": {"queue": "research"},
    "tradegraph.ingestion.*": {"queue": "ingestion"},
}
# Research jobs are long-running (a real reasoning chain over CPU-served
# Qwen3 took 494s in tests/integration/test_research_pipeline_live.py) —
# never ack early, and never let a crashed worker silently drop a job that
# was mid-flight.
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.worker_prefetch_multiplier = 1


@worker_process_init.connect  # type: ignore[untyped-decorator]  # celery has no type stubs
def _start_metrics_server(**_kwargs: object) -> None:
    """Unlike the API (uvicorn already serves HTTP), a Celery worker has no
    request/response cycle to hang a `/metrics` route off — it needs its
    own tiny HTTP server, started once when the worker process comes up.
    `--pool=solo` (this project's only worker pool — Windows has no fork,
    see src/graph/tasks.py's module docstring) means exactly one process,
    so "once per process" is "once", not "once per fork" racing on the
    same port.
    """
    start_http_server(settings.prometheus_metrics_port)
