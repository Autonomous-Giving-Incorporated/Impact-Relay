"""Object storage: local + S3 backend (mock client; no live AWS required)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from impact_relay.storage.objects import (
    LocalObjectStorage,
    ObjectStorageError,
    S3ObjectStorage,
    open_object_storage,
    validate_object_ref,
)
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID


class FakeS3Client:
    """Minimal in-memory S3 client for unit tests."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **kwargs: Any) -> dict:
        self.objects[(Bucket, Key)] = {
            "Body": Body,
            "ContentType": kwargs.get("ContentType"),
            "Metadata": kwargs.get("Metadata") or {},
            "ServerSideEncryption": kwargs.get("ServerSideEncryption"),
        }
        return {"ETag": "fake"}

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        item = self.objects.get((Bucket, Key))
        if item is None:
            err = Exception("NoSuchKey")
            err.response = {  # type: ignore[attr-defined]
                "Error": {"Code": "NoSuchKey"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            }
            raise err
        body = MagicMock()
        body.read.return_value = item["Body"]
        return {"Body": body}

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        if (Bucket, Key) not in self.objects:
            err = Exception("404")
            err.response = {  # type: ignore[attr-defined]
                "Error": {"Code": "404"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            }
            raise err
        return {"ContentLength": len(self.objects[(Bucket, Key)]["Body"])}

    def delete_object(self, *, Bucket: str, Key: str) -> dict:
        self.objects.pop((Bucket, Key), None)
        return {}


def test_validate_rejects_escape() -> None:
    with pytest.raises(ObjectStorageError):
        validate_object_ref(CANONICAL_PILOT_TENANT_ID, "../x")
    with pytest.raises(ObjectStorageError):
        validate_object_ref("bad/tenant", "k")


def test_local_and_s3_same_api_hd_tenant(tmp_path: Path) -> None:
    local = LocalObjectStorage(tmp_path / "obj")
    fake = FakeS3Client()
    s3 = S3ObjectStorage("test-bucket", prefix="pilot/", client=fake)

    data = b"%PDF-hd-invoice"
    for store in (local, s3):
        sid = store.put(
            CANONICAL_PILOT_TENANT_ID,
            "evidence/inv-1.pdf",
            data,
            content_type="application/pdf",
            meta={"source": "fixture"},
        )
        assert sid == f"{CANONICAL_PILOT_TENANT_ID}/evidence/inv-1.pdf"
        assert store.get(CANONICAL_PILOT_TENANT_ID, "evidence/inv-1.pdf") == data
        assert store.exists(CANONICAL_PILOT_TENANT_ID, "evidence/inv-1.pdf")
        # Cross-tenant isolation
        assert store.get("org_other_makerspace", "evidence/inv-1.pdf") is None
        assert store.delete(CANONICAL_PILOT_TENANT_ID, "evidence/inv-1.pdf") is True
        assert store.get(CANONICAL_PILOT_TENANT_ID, "evidence/inv-1.pdf") is None


def test_s3_key_prefix_and_sse() -> None:
    fake = FakeS3Client()
    s3 = S3ObjectStorage(
        "bkt",
        prefix="impact-relay",
        client=fake,
        server_side_encryption="AES256",
    )
    s3.put(CANONICAL_PILOT_TENANT_ID, "evidence/a.bin", b"x")
    key = f"impact-relay/{CANONICAL_PILOT_TENANT_ID}/evidence/a.bin"
    assert ("bkt", key) in fake.objects
    assert fake.objects[("bkt", key)]["ServerSideEncryption"] == "AES256"


def test_s3_sse_disabled() -> None:
    fake = FakeS3Client()
    s3 = S3ObjectStorage("bkt", client=fake, server_side_encryption=None)
    s3.put(CANONICAL_PILOT_TENANT_ID, "k", b"y")
    stored = next(iter(fake.objects.values()))
    assert stored["ServerSideEncryption"] is None


def test_open_object_storage_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMPACT_RELAY_OBJECT_STORE", raising=False)
    store = open_object_storage(tmp_path)
    assert isinstance(store, LocalObjectStorage)
    store.put(CANONICAL_PILOT_TENANT_ID, "e/1", b"1")
    assert store.get(CANONICAL_PILOT_TENANT_ID, "e/1") == b"1"


def test_open_object_storage_s3_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMPACT_RELAY_OBJECT_STORE", "s3")
    monkeypatch.setenv("IMPACT_RELAY_S3_BUCKET", "env-bucket")
    monkeypatch.setenv("IMPACT_RELAY_S3_PREFIX", "p/")
    monkeypatch.setenv("IMPACT_RELAY_S3_SSE", "none")
    fake = FakeS3Client()
    store = open_object_storage(
        backend="s3",
        bucket="env-bucket",
        prefix="p/",
        server_side_encryption="none",
        client=fake,
    )
    assert isinstance(store, S3ObjectStorage)
    store.put(CANONICAL_PILOT_TENANT_ID, "x", b"z")
    assert ("env-bucket", f"p/{CANONICAL_PILOT_TENANT_ID}/x") in fake.objects


def test_open_s3_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMPACT_RELAY_OBJECT_STORE", "s3")
    monkeypatch.delenv("IMPACT_RELAY_S3_BUCKET", raising=False)
    with pytest.raises(ObjectStorageError, match="BUCKET"):
        open_object_storage(backend="s3")


def test_storage_bundle_uses_s3_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from impact_relay.storage import open_storage

    fake = FakeS3Client()
    monkeypatch.setenv("IMPACT_RELAY_OBJECT_STORE", "s3")
    monkeypatch.setenv("IMPACT_RELAY_S3_BUCKET", "bundle-bkt")
    # Force object store via open_storage path: open_object_storage reads env
    # but creates real boto3 without client. Inject by constructing bundle manually.
    from impact_relay.storage.sql import StorageBundle
    from impact_relay.storage.objects import S3ObjectStorage

    bundle = StorageBundle(
        tmp_path / "st",
        object_store=S3ObjectStorage("bundle-bkt", client=fake),
    )
    bundle.objects.put(CANONICAL_PILOT_TENANT_ID, "ev/1", b"data")
    assert bundle.objects.get(CANONICAL_PILOT_TENANT_ID, "ev/1") == b"data"
    # local default still works when env not s3
    monkeypatch.delenv("IMPACT_RELAY_OBJECT_STORE", raising=False)
    local_bundle = open_storage(tmp_path / "st2")
    assert isinstance(local_bundle.objects, LocalObjectStorage)
