"""Content-hash dedup and document versioning (docs/04 requirements 1 & 2).

Two pure functions, deliberately decoupled from the database: the ingestion
pipeline queries PostgreSQL for what already exists and passes the result
in, which is what makes both functions unit-testable without a live
connection and keeps the idempotency/versioning *policy* in one place
separate from *where the data lives*.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass


def compute_content_hash(content: bytes) -> str:
    """sha256 hex digest — the idempotency key (docs/04 requirement 1).

    ❗ Hash the raw bytes exactly as fetched, before any parsing. Hashing
    post-parse output would make the hash depend on this parser's
    behaviour, so a parser bug fix would look like new content and defeat
    the idempotency guarantee this hash exists to provide.
    """
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class DedupDecision:
    is_duplicate: bool
    matched_document_id: uuid.UUID | None


def check_duplicate(content_hash: str, existing_hash_to_id: dict[str, uuid.UUID]) -> DedupDecision:
    """Content-hash gate — re-runs must be no-ops (docs/04 requirement 1)."""
    matched_id = existing_hash_to_id.get(content_hash)
    return DedupDecision(is_duplicate=matched_id is not None, matched_document_id=matched_id)


@dataclass(frozen=True)
class ExistingVersion:
    document_id: uuid.UUID
    version: int
    content_hash: str


@dataclass(frozen=True)
class VersionDecision:
    version: int
    supersedes_id: uuid.UUID | None


def determine_version(existing_versions: list[ExistingVersion]) -> VersionDecision:
    """Next version number for a document that shares identity (company,
    ticker, document_type, filing_date/period) with prior version(s) but
    has different content — e.g. a 10-K/A amendment (docs/04 requirement 2:
    "version every source document and preserve provenance").

    Superseded versions are never deleted or overwritten — this function
    only ever returns a *new* version number pointing back at the latest
    prior one, so `documents.supersedes_id` forms an append-only chain.
    """
    if not existing_versions:
        return VersionDecision(version=1, supersedes_id=None)

    latest = max(existing_versions, key=lambda v: v.version)
    return VersionDecision(version=latest.version + 1, supersedes_id=latest.document_id)
