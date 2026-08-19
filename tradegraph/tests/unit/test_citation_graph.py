"""Unit tests for src.rag.graph.citation_graph — Driver/Session mocked (no
live Neo4j needed), verifying the Cypher this module emits and how it maps
query results back into GraphNeighbor objects. Live-graph behavior (does
Neo4j itself do what the Cypher says) belongs in an integration test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.rag.graph.citation_graph import (
    CitationGraphStore,
    CitationRelation,
    NodeKind,
)


def _store_with_session() -> tuple[CitationGraphStore, MagicMock]:
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    driver = MagicMock()
    driver.session.return_value = session
    return CitationGraphStore(driver), session


def test_upsert_node_merges_by_id_with_kind_label() -> None:
    store, session = _store_with_session()

    store.upsert_node(NodeKind.CASE, "case-1", citation="AIR 1973 SC 1461", year=1973)

    query = session.run.call_args.args[0]
    kwargs = session.run.call_args.kwargs
    assert "MERGE (n:Case {id: $id})" in query
    assert kwargs["id"] == "case-1"
    assert kwargs["properties"] == {"citation": "AIR 1973 SC 1461", "year": 1973}


def test_upsert_edge_matches_both_nodes_by_kind_and_id() -> None:
    store, session = _store_with_session()

    store.upsert_edge(
        from_id="case-1",
        from_kind=NodeKind.CASE,
        to_id="section-17",
        to_kind=NodeKind.SECTION,
        relation=CitationRelation.INTERPRETS,
    )

    query = session.run.call_args.args[0]
    kwargs = session.run.call_args.kwargs
    assert "MATCH (a:Case {id: $from_id}), (b:Section {id: $to_id})" in query
    assert "MERGE (a)-[:INTERPRETS]->(b)" in query
    assert kwargs == {"from_id": "case-1", "to_id": "section-17"}


def test_neighbors_maps_records_into_graph_neighbors() -> None:
    store, session = _store_with_session()
    record = {
        "n": {"id": "case-2", "citation": "AIR 1980 SC 1"},
        "labels": ["Case"],
        "last_relation": "DISTINGUISHES",
        "hops": 1,
    }
    session.run.return_value = [record]

    neighbors = store.neighbors("case-1", relations=[CitationRelation.DISTINGUISHES])

    assert len(neighbors) == 1
    neighbor = neighbors[0]
    assert neighbor.node.id == "case-2"
    assert neighbor.node.kind == NodeKind.CASE
    assert neighbor.relation == CitationRelation.DISTINGUISHES
    assert neighbor.hops == 1

    query = session.run.call_args.args[0]
    assert ":DISTINGUISHES*1..1" in query


def test_neighbors_without_relation_filter_allows_any_relation_type() -> None:
    store, session = _store_with_session()
    session.run.return_value = []

    store.neighbors("case-1", max_hops=2)

    query = session.run.call_args.args[0]
    assert "-[r*1..2]->" in query
