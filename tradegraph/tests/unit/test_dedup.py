"""Unit tests for src.rag.ingestion.dedup."""

from __future__ import annotations

import uuid

from src.rag.ingestion.dedup import (
    ExistingVersion,
    check_duplicate,
    compute_content_hash,
    determine_version,
)


def test_content_hash_is_deterministic() -> None:
    assert compute_content_hash(b"same content") == compute_content_hash(b"same content")


def test_content_hash_changes_with_content() -> None:
    assert compute_content_hash(b"a") != compute_content_hash(b"b")


def test_check_duplicate_no_match() -> None:
    decision = check_duplicate("abc123", existing_hash_to_id={})
    assert decision.is_duplicate is False
    assert decision.matched_document_id is None


def test_check_duplicate_match() -> None:
    doc_id = uuid.uuid4()
    decision = check_duplicate("abc123", existing_hash_to_id={"abc123": doc_id})
    assert decision.is_duplicate is True
    assert decision.matched_document_id == doc_id


def test_determine_version_first_version() -> None:
    decision = determine_version([])
    assert decision.version == 1
    assert decision.supersedes_id is None


def test_determine_version_amendment() -> None:
    original_id = uuid.uuid4()
    decision = determine_version(
        [ExistingVersion(document_id=original_id, version=1, content_hash="a" * 64)]
    )
    assert decision.version == 2
    assert decision.supersedes_id == original_id


def test_determine_version_picks_latest_of_multiple() -> None:
    v1 = ExistingVersion(document_id=uuid.uuid4(), version=1, content_hash="a" * 64)
    v2 = ExistingVersion(document_id=uuid.uuid4(), version=2, content_hash="b" * 64)

    decision = determine_version([v1, v2])
    assert decision.version == 3
    assert decision.supersedes_id == v2.document_id
