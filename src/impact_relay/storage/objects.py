"""Local filesystem object storage (tenant-scoped). S3 later implements same port."""

from __future__ import annotations

import json
import re
from pathlib import Path

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._/\-]+$")


class ObjectStorageError(ValueError):
    """Invalid tenant, key, or path escape."""


class LocalObjectStorage:
    """``{root}/{tenant_id}/{key}`` with path traversal protection."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, tenant_id: str, key: str) -> Path:
        if not tenant_id or "/" in tenant_id or ".." in tenant_id:
            raise ObjectStorageError(f"invalid tenant_id: {tenant_id!r}")
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ObjectStorageError(f"invalid object key: {key!r}")
        if not _SAFE_KEY.match(key):
            raise ObjectStorageError(f"object key has illegal characters: {key!r}")
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
        return f"{tenant_id}/{key}"

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
