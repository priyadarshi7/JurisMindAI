"""Object storage client — MinIO / S3-compatible (docs/01 Tier 3, docs/04).

Holds the untouched original of every ingested document, written **before**
any parsing, so a parse can always be re-derived and audited without
re-fetching from a source that may have changed or gone away (docs/01 Flow
A). The key namespace is content-addressed by `content_hash`, which gives
storage-layer idempotency that complements (does not replace) the
`documents.content_hash` unique constraint in PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from src.core.config import get_settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    content_type: str
    size_bytes: int


class ObjectStorageClient:
    """Thin wrapper around boto3's S3 client, pointed at MinIO locally and
    at a real S3-compatible endpoint in staging/production — same client
    code, same API, per docs/12's "local stack runs the real software."
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str,
    ) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Idempotent bucket creation — safe to call on every startup."""
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code not in {"404", "NoSuchBucket"}:
                raise
            self._client.create_bucket(Bucket=bucket)

    def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str) -> StoredObject:
        self._client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
        return StoredObject(bucket=bucket, key=key, content_type=content_type, size_bytes=len(body))

    def get_object(self, *, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def object_exists(self, *, bucket: str, key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in {"404", "NoSuchKey"}:
                return False
            raise


def build_raw_document_key(
    *, source: str, ticker: str, document_type: str, content_hash: str, extension: str
) -> str:
    """Content-addressed key for a raw original (docs/04 Stage 2).

    Deliberately keyed on `content_hash`, not a timestamp or a random id:
    two ingestion runs that fetch byte-identical content land on the same
    object, which is the storage-layer expression of the idempotency rule
    docs/04 requires at the database layer via the `content_hash` unique
    constraint.
    """
    ext = extension.lstrip(".")
    return f"raw/{source}/{ticker.upper()}/{document_type}/{content_hash}.{ext}"


@lru_cache
def get_object_storage_client() -> ObjectStorageClient:
    settings = get_settings()
    return ObjectStorageClient(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
    )
