"""Tenant-scoped object storage — local FS default; S3-compatible optional.

Keys are always ``{tenant_id}/{key}``. Path traversal and cross-tenant
access are rejected. Hacker Dojo and other nonprofits share the same API.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._/\-]+$")


class ObjectStorageError(ValueError):
    """Invalid tenant, key, path escape, or backend misconfiguration."""


@dataclass(frozen=True)
class ObjectRetentionPolicy:
    """Per-object retention metadata for evidence and receipt artifacts."""

    classification: str
    retain_until: str
    legal_hold: bool = False

    @classmethod
    def for_days(
        cls,
        *,
        classification: str,
        days: int,
        now: datetime | None = None,
        legal_hold: bool = False,
    ) -> ObjectRetentionPolicy:
        if days < 0:
            raise ObjectStorageError("retention days must be non-negative")
        base = now or datetime.now(UTC)
        if base.tzinfo is None:
            base = base.replace(tzinfo=UTC)
        retain_until = (base + timedelta(days=days)).replace(microsecond=0).isoformat()
        return cls(classification=classification, retain_until=retain_until, legal_hold=legal_hold)

    def __post_init__(self) -> None:
        if not self.classification.strip():
            raise ObjectStorageError("retention classification is required")
        if any(ch in self.classification for ch in "\r\n"):
            raise ObjectStorageError("retention classification must be a single metadata value")
        _parse_retention_time(self.retain_until)

    def metadata(self) -> dict[str, str]:
        return {
            "retention_classification": self.classification,
            "retain_until": self.retain_until,
            "legal_hold": "true" if self.legal_hold else "false",
        }


@dataclass(frozen=True)
class RetentionPurgeReceipt:
    tenant_id: str
    scanned: int
    purged: int
    retained: int
    held: int
    purged_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "scanned": self.scanned,
            "purged": self.purged,
            "retained": self.retained,
            "held": self.held,
            "purged_keys": list(self.purged_keys),
        }


def _parse_retention_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObjectStorageError("retain_until must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def retention_metadata(
    policy: ObjectRetentionPolicy | None,
    meta: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge caller metadata with normalized retention metadata."""

    merged = {str(k): str(v) for k, v in (meta or {}).items()}
    if policy is not None:
        merged.update(policy.metadata())
    return merged


def validate_object_ref(tenant_id: str, key: str) -> None:
    """Shared validation for local + S3 backends."""
    if not tenant_id or "/" in tenant_id or ".." in tenant_id or "\\" in tenant_id:
        raise ObjectStorageError(f"invalid tenant_id: {tenant_id!r}")
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ObjectStorageError(f"invalid object key: {key!r}")
    if not _SAFE_KEY.match(key):
        raise ObjectStorageError(f"object key has illegal characters: {key!r}")


def object_storage_id(tenant_id: str, key: str) -> str:
    validate_object_ref(tenant_id, key)
    return f"{tenant_id}/{key}"


class LocalObjectStorage:
    """``{root}/{tenant_id}/{key}`` with path traversal protection."""

    backend = "local"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, tenant_id: str, key: str) -> Path:
        validate_object_ref(tenant_id, key)
        base = (self.root / tenant_id).resolve()
        path = (base / key).resolve()
        if not str(path).startswith(str(base)):
            raise ObjectStorageError("path escape rejected")
        return path

    def put(
        self,
        tenant_id: str,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        meta: dict[str, str] | None = None,
    ) -> str:
        path = self._resolve(tenant_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        meta_path = path.with_suffix(path.suffix + ".meta.json")
        meta_path.write_text(
            json.dumps(
                {"content_type": content_type, "meta": meta or {}, "bytes": len(data)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return object_storage_id(tenant_id, key)

    def put_with_retention(
        self,
        tenant_id: str,
        key: str,
        data: bytes,
        *,
        retention: ObjectRetentionPolicy,
        content_type: str = "application/octet-stream",
        meta: dict[str, str] | None = None,
    ) -> str:
        return self.put(
            tenant_id,
            key,
            data,
            content_type=content_type,
            meta=retention_metadata(retention, meta),
        )

    def get(self, tenant_id: str, key: str) -> bytes | None:
        path = self._resolve(tenant_id, key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def exists(self, tenant_id: str, key: str) -> bool:
        return self._resolve(tenant_id, key).is_file()

    def delete(self, tenant_id: str, key: str) -> bool:
        path = self._resolve(tenant_id, key)
        meta = path.with_suffix(path.suffix + ".meta.json")
        deleted = False
        if path.is_file():
            path.unlink()
            deleted = True
        if meta.is_file():
            meta.unlink()
        return deleted

    def purge_expired(
        self,
        tenant_id: str,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
    ) -> RetentionPurgeReceipt:
        validate_object_ref(tenant_id, "retention-scan")
        tenant_root = (self.root / tenant_id).resolve()
        if not tenant_root.exists():
            return RetentionPurgeReceipt(tenant_id, 0, 0, 0, 0, ())
        if not str(tenant_root).startswith(str(self.root.resolve())):
            raise ObjectStorageError("path escape rejected")

        cutoff = now or datetime.now(UTC)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        cutoff = cutoff.astimezone(UTC)

        scanned = purged = retained = held = 0
        purged_keys: list[str] = []
        for meta_path in sorted(tenant_root.rglob("*.meta.json")):
            object_path = Path(str(meta_path)[: -len(".meta.json")])
            if not object_path.is_file():
                continue
            key = object_path.relative_to(tenant_root).as_posix()
            validate_object_ref(tenant_id, key)
            scanned += 1
            try:
                meta_doc = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                retained += 1
                continue
            metadata = meta_doc.get("meta") if isinstance(meta_doc, dict) else None
            if not isinstance(metadata, dict):
                retained += 1
                continue
            if str(metadata.get("legal_hold", "")).lower() == "true":
                held += 1
                continue
            retain_until = metadata.get("retain_until")
            if not isinstance(retain_until, str) or not retain_until:
                retained += 1
                continue
            if _parse_retention_time(retain_until) > cutoff:
                retained += 1
                continue
            purged += 1
            purged_keys.append(key)
            if not dry_run:
                self.delete(tenant_id, key)
        return RetentionPurgeReceipt(
            tenant_id=tenant_id,
            scanned=scanned,
            purged=purged,
            retained=retained,
            held=held,
            purged_keys=tuple(purged_keys),
        )


class S3ObjectStorage:
    """S3-compatible object store (AWS S3, MinIO, R2, etc.).

    Object key layout: ``{prefix}{tenant_id}/{key}``.

    Requires ``pip install 'impact-relay[s3]'`` (boto3). For local MinIO::

        IMPACT_RELAY_OBJECT_STORE=s3
        IMPACT_RELAY_S3_BUCKET=impact-relay
        IMPACT_RELAY_S3_ENDPOINT_URL=http://127.0.0.1:9000
        AWS_ACCESS_KEY_ID=minio
        AWS_SECRET_ACCESS_KEY=minio123
    """

    backend = "s3"

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client: Any | None = None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        server_side_encryption: str | None = "AES256",
    ) -> None:
        if not bucket:
            raise ObjectStorageError("S3 bucket name is required")
        self.bucket = bucket
        # Normalize prefix to end with / when non-empty
        pref = prefix or ""
        if pref and not pref.endswith("/"):
            pref = pref + "/"
        self.prefix = pref
        self.server_side_encryption = server_side_encryption
        self._client = client
        self._endpoint_url = endpoint_url
        self._region_name = region_name

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise ObjectStorageError("S3 support requires: pip install 'impact-relay[s3]'") from exc
        kwargs: dict[str, Any] = {}
        if self._region_name:
            kwargs["region_name"] = self._region_name
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        self._client = boto3.client("s3", **kwargs)
        return self._client

    def _s3_key(self, tenant_id: str, key: str) -> str:
        validate_object_ref(tenant_id, key)
        return f"{self.prefix}{tenant_id}/{key}"

    def put(
        self,
        tenant_id: str,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        meta: dict[str, str] | None = None,
    ) -> str:
        s3_key = self._s3_key(tenant_id, key)
        extra: dict[str, Any] = {
            "ContentType": content_type,
            "Metadata": {k: str(v) for k, v in (meta or {}).items()},
        }
        if self.server_side_encryption and self.server_side_encryption.lower() not in (
            "none",
            "off",
            "false",
            "0",
            "",
        ):
            extra["ServerSideEncryption"] = self.server_side_encryption
        self.client.put_object(Bucket=self.bucket, Key=s3_key, Body=data, **extra)
        return object_storage_id(tenant_id, key)

    def put_with_retention(
        self,
        tenant_id: str,
        key: str,
        data: bytes,
        *,
        retention: ObjectRetentionPolicy,
        content_type: str = "application/octet-stream",
        meta: dict[str, str] | None = None,
    ) -> str:
        return self.put(
            tenant_id,
            key,
            data,
            content_type=content_type,
            meta=retention_metadata(retention, meta),
        )

    def get(self, tenant_id: str, key: str) -> bytes | None:
        s3_key = self._s3_key(tenant_id, key)
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=s3_key)
        except Exception as exc:
            # botocore ClientError NoSuchKey / 404
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound") or "NoSuchKey" in str(exc):
                return None
            # Also handle 404 status
            if (
                getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
                == 404
            ):
                return None
            raise ObjectStorageError(f"S3 get failed: {exc}") from exc
        body = resp["Body"].read()
        return body

    def exists(self, tenant_id: str, key: str) -> bool:
        s3_key = self._s3_key(tenant_id, key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound") or "Not Found" in str(exc):
                return False
            if (
                getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
                == 404
            ):
                return False
            raise ObjectStorageError(f"S3 head failed: {exc}") from exc

    def delete(self, tenant_id: str, key: str) -> bool:
        s3_key = self._s3_key(tenant_id, key)
        # delete_object is idempotent on S3
        if not self.exists(tenant_id, key):
            return False
        self.client.delete_object(Bucket=self.bucket, Key=s3_key)
        return True


def open_object_storage(
    data_dir: Path | str | None = None,
    *,
    backend: str | None = None,
    bucket: str | None = None,
    prefix: str | None = None,
    endpoint_url: str | None = None,
    region_name: str | None = None,
    server_side_encryption: str | None = None,
    client: Any | None = None,
) -> LocalObjectStorage | S3ObjectStorage:
    """Open object storage: local under data_dir, or S3 when configured.

    Env (when args omitted)::

        IMPACT_RELAY_OBJECT_STORE=local|s3   (default local)
        IMPACT_RELAY_S3_BUCKET=...
        IMPACT_RELAY_S3_PREFIX=impact-relay/
        IMPACT_RELAY_S3_ENDPOINT_URL=...     # MinIO
        IMPACT_RELAY_S3_REGION=us-east-1
        IMPACT_RELAY_S3_SSE=AES256|aws:kms|none
    """
    kind = (backend or os.environ.get("IMPACT_RELAY_OBJECT_STORE") or "local").strip().lower()
    if kind in ("local", "fs", "filesystem", "file"):
        root = Path(data_dir or os.environ.get("IMPACT_RELAY_DATA_DIR") or ".impact-relay")
        return LocalObjectStorage(root / "objects")

    if kind in ("s3", "minio", "r2"):
        bkt = bucket or os.environ.get("IMPACT_RELAY_S3_BUCKET")
        if not bkt:
            raise ObjectStorageError("S3 object store requires IMPACT_RELAY_S3_BUCKET or bucket=")
        pref = prefix if prefix is not None else os.environ.get("IMPACT_RELAY_S3_PREFIX", "")
        ep = endpoint_url or os.environ.get("IMPACT_RELAY_S3_ENDPOINT_URL")
        region = (
            region_name or os.environ.get("IMPACT_RELAY_S3_REGION") or os.environ.get("AWS_REGION")
        )
        sse: str | None = (
            server_side_encryption
            if server_side_encryption is not None
            else os.environ.get("IMPACT_RELAY_S3_SSE", "AES256")
        )
        if sse and sse.lower() in ("none", "off", "false", "0"):
            sse = None
        return S3ObjectStorage(
            bkt,
            prefix=pref or "",
            client=client,
            endpoint_url=ep,
            region_name=region,
            server_side_encryption=sse,
        )

    raise ObjectStorageError(f"unknown IMPACT_RELAY_OBJECT_STORE={kind!r} (use local or s3)")
