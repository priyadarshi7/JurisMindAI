"""Integration test: the object storage client against a real MinIO
instance (`docker compose up -d minio`) — not a mock.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from src.core.config import get_settings
from src.data.object_storage import ObjectStorageClient, build_raw_document_key

TEST_BUCKET = "tradegraph-test-bucket"


@pytest.fixture
def client() -> Iterator[ObjectStorageClient]:
    settings = get_settings()
    c = ObjectStorageClient(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key or "tradegraph",
        secret_key=settings.s3_secret_key or "tradegraph123",
        region=settings.s3_region,
    )
    try:
        c.ensure_bucket(TEST_BUCKET)
    except Exception as exc:
        pytest.skip(f"MinIO not reachable: {exc}")
    yield c


def test_round_trip_against_real_minio(client: ObjectStorageClient) -> None:
    # A fresh hash per run: MinIO is real, persistent storage (a docker
    # volume) — a fixed key would collide with whatever a previous run of
    # this same test already wrote, making the "does not exist yet"
    # assertion below flaky rather than a real signal.
    content_hash = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars
    key = build_raw_document_key(
        source="sec_edgar",
        ticker="NVDA",
        document_type="10-K",
        content_hash=content_hash,
        extension="htm",
    )
    body = b"<html>a real filing body</html>"

    assert client.object_exists(bucket=TEST_BUCKET, key=key) is False

    client.put_object(bucket=TEST_BUCKET, key=key, body=body, content_type="text/html")

    assert client.object_exists(bucket=TEST_BUCKET, key=key) is True
    assert client.get_object(bucket=TEST_BUCKET, key=key) == body
