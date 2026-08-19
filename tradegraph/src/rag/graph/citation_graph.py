"""Citation knowledge graph — Neo4j (NyayaGraph pivot, docs/16 Phase 1).

PostgreSQL (`src/models/orm.py`) stays the system of record for every
document/chunk/evidence/claim/citation row; this module owns only the
*relationships between legal authorities* (Case cites Case, Case interprets
Section, ...) that a relational join table would make expensive to traverse
transitively ("what does this case's own authority ultimately rest on").
Neo4j node ids are always the same UUID string as the corresponding
PostgreSQL `documents.id` (a `Case`/`Constitution`/`CentralAct` row) or
`legal_sections.id` (a `Section`/`Article` row) — this module never mints a
separate identity for something Postgres already has one for.

❗ Edges are only ever written from something the ingestion pipeline actually
found in the source text (an LLM-assisted citation-extraction pass over a
judgment, classifying each citation mention's relation). A relation this
module cannot confidently classify degrades to CITES — the most
conservative, defensible relation — rather than guessing DISTINGUISHES or
FOLLOWS with no textual basis. Never invent an edge with no source evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from src.core.config import get_settings


class NodeKind(StrEnum):
    CASE = "Case"
    SECTION = "Section"
    ARTICLE = "Article"


class CitationRelation(StrEnum):
    CITES = "CITES"
    INTERPRETS = "INTERPRETS"
    FOLLOWS = "FOLLOWS"
    DISTINGUISHES = "DISTINGUISHES"
    REFERS_TO = "REFERS_TO"


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    properties: dict[str, object]


@dataclass(frozen=True)
class GraphNeighbor:
    node: GraphNode
    relation: CitationRelation
    hops: int


class CitationGraphStore:
    """Thin wrapper — every method is one Cypher statement, no query
    building beyond what `relations`/`max_hops` need. Kept intentionally
    small: this is a citation-neighborhood lookup used to enrich retrieval
    and feed the counterargument node, not a general graph-analytics layer.
    """

    def __init__(self, driver: Driver, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def close(self) -> None:
        self._driver.close()

    def upsert_node(self, kind: NodeKind, node_id: str, **properties: object) -> None:
        query = f"MERGE (n:{kind.value} {{id: $id}}) SET n += $properties"
        with self._driver.session(database=self._database) as session:
            session.run(query, id=node_id, properties=properties)

    def upsert_edge(
        self,
        *,
        from_id: str,
        from_kind: NodeKind,
        to_id: str,
        to_kind: NodeKind,
        relation: CitationRelation,
    ) -> None:
        query = (
            f"MATCH (a:{from_kind.value} {{id: $from_id}}), (b:{to_kind.value} {{id: $to_id}}) "
            f"MERGE (a)-[:{relation.value}]->(b)"
        )
        with self._driver.session(database=self._database) as session:
            session.run(query, from_id=from_id, to_id=to_id)

    def neighbors(
        self,
        node_id: str,
        *,
        relations: Iterable[CitationRelation] | None = None,
        max_hops: int = 1,
    ) -> list[GraphNeighbor]:
        """Outgoing neighbors up to `max_hops` hops away, optionally
        filtered to specific relation types (e.g. only DISTINGUISHES, for
        the counterargument node — cases that push back on a candidate
        authority rather than every case that merely mentions it).
        """
        rel_filter = "|".join(r.value for r in relations) if relations else ""
        rel_clause = f":{rel_filter}" if rel_filter else ""
        query = (
            f"MATCH (start {{id: $node_id}})-[r{rel_clause}*1..{max_hops}]->(n) "
            "RETURN DISTINCT n, labels(n) AS labels, "
            "[rel IN r | type(rel)][-1] AS last_relation, size(r) AS hops"
        )
        with self._driver.session(database=self._database) as session:
            result = session.run(query, node_id=node_id)
            neighbors: list[GraphNeighbor] = []
            for record in result:
                node = record["n"]
                labels = record["labels"]
                kind = NodeKind(labels[0]) if labels else NodeKind.CASE
                neighbors.append(
                    GraphNeighbor(
                        node=GraphNode(id=node["id"], kind=kind, properties=dict(node)),
                        relation=CitationRelation(record["last_relation"]),
                        hops=record["hops"],
                    )
                )
            return neighbors


@lru_cache
def get_citation_graph_store() -> CitationGraphStore:
    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    return CitationGraphStore(driver)
