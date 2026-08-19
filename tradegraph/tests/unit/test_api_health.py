"""Smoke test for the API's startup-time prompt validation + /health route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from src.prompts.loader import REQUIRED_NODES


def test_health_endpoint_reports_all_prompt_nodes_loaded() -> None:
    # Using the app as a context manager triggers the lifespan (startup)
    # handler, which is where prompt-repository validation happens —
    # docs/16 Phase 0: "fail the deploy, not the first research job."
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["prompt_nodes_loaded"]) == REQUIRED_NODES
