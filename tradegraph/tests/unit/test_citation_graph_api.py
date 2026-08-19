"""Unit tests for apps/api/routers/citation_graph.py — CitationGraphStore
faked via FastAPI dependency override (no live Neo4j needed), mirroring the
convention tests/unit/test_jobs_api.py uses for the DB session.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from src.rag.graph.citation_graph import (
    CitationRelation,
    GraphNeighbor,
    GraphNode,
    NodeKind,
    get_citation_graph_store,
)


class FakeCitationGraphStore:
    def __init__(self, neighbors: list[GraphNeighbor]) -> None:
        self._neighbors = neighbors
        self.last_call: dict[str, object] | None = None

    def neighbors(self, node_id: str, *, max_hops: int = 1, **_: object) -> list[GraphNeighbor]:
        self.last_call = {"node_id": node_id, "max_hops": max_hops}
        return self._neighbors


def test_get_neighbors_returns_empty_list_for_unseeded_node() -> None:
    """No graph data yet (pre-ingestion) must render as "nothing here," not
    an error — the frontend can't tell "not ingested" from "server broke."
    """
    fake = FakeCitationGraphStore([])
    app.dependency_overrides[get_citation_graph_store] = lambda: fake

    try:
        with TestClient(app) as client:
            response = client.get("/citation-graph/case-1/neighbors")
    finally:
        app.dependency_overrides.pop(get_citation_graph_store, None)

    assert response.status_code == 200
    assert response.json() == []


def test_get_neighbors_maps_store_results_to_response_shape() -> None:
    fake = FakeCitationGraphStore(
        [
            GraphNeighbor(
                node=GraphNode(
                    id="case-2", kind=NodeKind.CASE, properties={"citation": "AIR 1980 SC 1"}
                ),
                relation=CitationRelation.DISTINGUISHES,
                hops=1,
            )
        ]
    )
    app.dependency_overrides[get_citation_graph_store] = lambda: fake

    try:
        with TestClient(app) as client:
            response = client.get("/citation-graph/case-1/neighbors")
    finally:
        app.dependency_overrides.pop(get_citation_graph_store, None)

    body = response.json()
    assert body == [
        {
            "node": {"id": "case-2", "kind": "Case", "properties": {"citation": "AIR 1980 SC 1"}},
            "relation": "DISTINGUISHES",
            "hops": 1,
        }
    ]


def test_get_neighbors_passes_max_hops_through() -> None:
    fake = FakeCitationGraphStore([])
    app.dependency_overrides[get_citation_graph_store] = lambda: fake

    try:
        with TestClient(app) as client:
            client.get("/citation-graph/case-1/neighbors", params={"max_hops": 2})
    finally:
        app.dependency_overrides.pop(get_citation_graph_store, None)

    assert fake.last_call == {"node_id": "case-1", "max_hops": 2}
