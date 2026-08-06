"""Multi-tenant storage ports and SQLite/Postgres backends.

Hacker Dojo (``org_hacker_dojo``) is the canonical pilot tenant and policy
template for other nonprofits. See ``docs/HACKER-DOJO-INTEGRATION.md``.
"""

from impact_relay.storage.ledger_repo import LedgerEntityRepository
from impact_relay.storage.objects import (
    LocalObjectStorage,
    ObjectRetentionPolicy,
    ObjectStorageError,
    RetentionPurgeReceipt,
    S3ObjectStorage,
    open_object_storage,
    retention_metadata,
)
from impact_relay.storage.ports import (
    ObjectStorage,
    OutboxEvent,
    OutboxStore,
    TenantRecord,
    TenantRepository,
)
from impact_relay.storage.sql import StorageBundle, open_storage
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    CANONICAL_POLICY_SLUG,
    clone_tenant_from_hacker_dojo,
    ensure_canonical_hacker_dojo_tenant,
)

__all__ = [
    "CANONICAL_PILOT_TENANT_ID",
    "CANONICAL_POLICY_SLUG",
    "LedgerEntityRepository",
    "LocalObjectStorage",
    "ObjectRetentionPolicy",
    "ObjectStorage",
    "ObjectStorageError",
    "OutboxEvent",
    "OutboxStore",
    "RetentionPurgeReceipt",
    "S3ObjectStorage",
    "StorageBundle",
    "TenantRecord",
    "TenantRepository",
    "clone_tenant_from_hacker_dojo",
    "ensure_canonical_hacker_dojo_tenant",
    "open_object_storage",
    "open_storage",
    "retention_metadata",
]
