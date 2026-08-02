"""Tenant workspace and multi-org platform (Phases 5–6 machine scope)."""

from __future__ import annotations

from typing import Any

from impact_relay.domain.donor_views import DonorReadService
from impact_relay.domain.impact import ImpactService
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.notifications import NotificationService
from impact_relay.domain.types import (
    ConsentRecord,
    FundedAsset,
    ImpactEvent,
    ImpactReceipt,
    NotificationDelivery,
    NotificationIntent,
    NotificationPreference,
    Organization,
    Program,
    TenantIsolationError,
)


class TenantWorkspace:
    """Single-organization state: ledger + impact + notification stores."""

    def __init__(
        self,
        organization: Organization,
        *,
        ledger: Ledger | None = None,
    ) -> None:
        # Optional existing ledger (agent vertical slice reuses a populated pilot ledger).
        self.ledger = ledger if ledger is not None else Ledger(organization)
        if self.ledger.organization.id != organization.id:
            raise TenantIsolationError("ledger organization_id mismatch")
        self.programs: dict[str, Program] = {}
        self.assets: dict[str, FundedAsset] = {}
        self.impact_events: dict[str, ImpactEvent] = {}
        self.impact_receipts: dict[str, ImpactReceipt] = {}
        self.consents: dict[tuple[str, str], ConsentRecord] = {}
        self.preferences: dict[tuple[str, str], NotificationPreference] = {}
        self.intents: dict[str, NotificationIntent] = {}
        self.intents_by_dedup: dict[str, NotificationIntent] = {}
        self.deliveries: dict[str, NotificationDelivery] = {}

    @property
    def organization(self) -> Organization:
        return self.ledger.organization

    def donor_reads(self) -> DonorReadService:
        return DonorReadService(self)

    def impact(self) -> ImpactService:
        return ImpactService(self)

    def notifications(self) -> NotificationService:
        return NotificationService(self)


class Platform:
    """Multi-tenant registry: each organization is fully isolated."""

    def __init__(self) -> None:
        self._tenants: dict[str, TenantWorkspace] = {}

    def register_organization(self, organization: Organization) -> TenantWorkspace:
        if organization.id in self._tenants:
            raise TenantIsolationError(f"organization already registered: {organization.id}")
        ws = TenantWorkspace(organization)
        self._tenants[organization.id] = ws
        return ws

    def get_workspace(self, organization_id: str) -> TenantWorkspace:
        if organization_id not in self._tenants:
            raise TenantIsolationError(f"unknown organization: {organization_id}")
        return self._tenants[organization_id]

    def list_organization_ids(self) -> list[str]:
        return sorted(self._tenants.keys())

    def donor_dashboard(self, organization_id: str, donor_id: str) -> dict[str, Any]:
        """Public read path with tenant + donor ownership checks."""
        ws = self.get_workspace(organization_id)
        donor = ws.ledger.donors.get(donor_id)
        if donor is None or donor.organization_id != organization_id:
            raise TenantIsolationError(f"cross-tenant or unknown donor access denied: {donor_id}")
        return ws.donor_reads().donor_dashboard(donor_id)

    def require_same_tenant(self, organization_id: str, donor_id: str) -> TenantWorkspace:
        ws = self.get_workspace(organization_id)
        donor = ws.ledger.donors.get(donor_id)
        if donor is None or donor.organization_id != organization_id:
            raise TenantIsolationError(f"cross-tenant or unknown donor access denied: {donor_id}")
        return ws
