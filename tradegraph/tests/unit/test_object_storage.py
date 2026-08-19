"""Unit tests for src.data.object_storage — mocked via moto, no real MinIO."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from moto import mock_aws

from src.data.object_storage import ObjectStorageClient, build_raw_document_key


@pytest.fixture
def client() -> Iterator[ObjectStorageClient]:
    with mock_aws():
        c = ObjectStorageClient(
            endpoint_url="https://s3.amazonaws.com",
            access_key="test",
            secret_key="test",
            region="us-east-1",
        )
        c.ensure_bucket("tradegraph-raw-documents")
        yield c


def test_ensure_bucket_is_idempotent(client: ObjectStorageClient) -> None:
    client.ensure_bucket("tradegraph-raw-documents")  # second call, must not raise
    client.ensure_bucket("tradegraph-raw-documents")


def test_put_and_get_object_round_trip(client: ObjectStorageClient) -> None:
    key = build_raw_document_key(
        source="sec_edgar",
        ticker="NVDA",
        document_type="10-K",
        content_hash="a" * 64,
        extension="htm",
    )
    client.put_object(
        bucket="tradegraph-raw-documents",
        key=key,
        body=b"<html>filing content</html>",
        content_type="text/html",
    )

    fetched = client.get_object(bucket="tradegraph-raw-documents", key=key)
    assert fetched == b"<html>filing content</html>"


def test_object_exists(client: ObjectStorageClient) -> None:
    key = "raw/sec_edgar/NVDA/10-K/" + "b" * 64 + ".htm"
    assert client.object_exists(bucket="tradegraph-raw-documents", key=key) is False

    client.put_object(
        bucket="tradegraph-raw-documents", key=key, body=b"x", content_type="text/html"
    )
    assert client.object_exists(bucket="tradegraph-raw-documents", key=key) is True


def test_build_raw_document_key_is_content_addressed() -> None:
    """docs/04: idempotent ingestion — identical content must map to the
    same key regardless of when/how it was fetched.
    """
    key_a = build_raw_document_key(
        source="sec_edgar",
        ticker="nvda",
        document_type="10-K",
        content_hash="c" * 64,
        extension=".htm",
    )
    key_b = build_raw_document_key(
        source="sec_edgar",
        ticker="NVDA",
        document_type="10-K",
        content_hash="c" * 64,
        extension="htm",
    )
    assert key_a == key_b
    assert key_a == f"raw/sec_edgar/NVDA/10-K/{'c' * 64}.htm"


def test_different_content_hash_produces_different_key() -> None:
    key_a = build_raw_document_key(
        source="sec_edgar",
        ticker="NVDA",
        document_type="10-K",
        content_hash="d" * 64,
        extension="htm",
    )
    key_b = build_raw_document_key(
        source="sec_edgar",
        ticker="NVDA",
        document_type="10-K",
        content_hash="e" * 64,
        extension="htm",
    )
    assert key_a != key_b
