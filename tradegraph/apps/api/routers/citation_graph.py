"""Citation graph endpoint — thin read-only wrapper over
`CitationGraphStore.neighbors` (src/rag/graph/citation_graph.py), powering
the frontend's case-citation mini-visualization.

Returns an empty list rather than an error for a node with no graph data —
until judgment ingestion (docs/16 Phase 2) has actually populated Neo4j,
every node id is "not found yet," and a 404 here would make every report
look broken rather than simply pre-ingestion.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.rag.graph.citation_graph import CitationGraphStore, get_citation_graph_store

router = APIRouter(prefix="/citation-graph", tags=["citation-graph"])


class GraphNodeResponse(BaseModel):
    id: str
    kind: str
    properties: dict[str, object]


class GraphNeighborResponse(BaseModel):
    node: GraphNodeResponse
    relation: str
    hops: int


@router.get("/{node_id}/neighbors", response_model=list[GraphNeighborResponse])
def get_neighbors(
    node_id: str,
    max_hops: int = Query(default=1, ge=1, le=3),
    store: CitationGraphStore = Depends(get_citation_graph_store),
) -> list[GraphNeighborResponse]:
    neighbors = store.neighbors(node_id, max_hops=max_hops)
    return [
        GraphNeighborResponse(
            node=GraphNodeResponse(
                id=n.node.id, kind=n.node.kind.value, properties=n.node.properties
            ),
            relation=n.relation.value,
            hops=n.hops,
        )
        for n in neighbors
    ]
