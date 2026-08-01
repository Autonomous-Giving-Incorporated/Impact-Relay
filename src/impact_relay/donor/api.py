"""Donor-facing API for host apps (Hacker-Dojo first).

All methods are donor-scoped and fail closed on cross-tenant / wrong donor.
"""

from __future__ import annotations

from typing import Any

from impact_relay.auth.principal import Principal
from impact_relay.auth.rbac import AuthorizationError, Permission, assert_permission
from impact_relay.domain.donor_views import DonorReadService
from impact_relay.domain.notifications import NotificationService
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    NotificationChannel,
    NotificationPreference,
    NotFoundError,
)


class DonorExperienceAPI:
    """Use-of-funds receipt detail, timeline, balances, prefs (read + preference write)."""

    def __init__(self, workspace: TenantWorkspace) -> None:
        self.ws = workspace
        self.reads = DonorReadService(workspace)
        self.notifications = NotificationService(workspace)

    def _assert_donor_access(
        self, donor_id: str, principal: Principal | None
    ) -> None:
        if principal is None:
            return
        assert_permission(
            principal, Permission.RECEIPT_READ, tenant_id=self.ws.organization.id
        )
        from impact_relay.auth.roles import Role

        staff = any(
            principal.has_role(r)
            for r in (
                Role.FINANCE_APPROVER,
                Role.FINANCE_REVIEWER,
                Role.AUDITOR,
                Role.TENANT_ADMIN,
                Role.COMMUNICATIONS_APPROVER,
                Role.PROGRAM_VERIFIER,
            )
        )
        if staff:
            return
        # Donor-only principals must bind claims.donor_id to the requested donor
        claim_donor = principal.raw_claims.get("donor_id")
        if claim_donor is not None and claim_donor != donor_id:
            raise AuthorizationError(
                f"donor principal cannot access donor_id={donor_id!r}"
            )

    def get_receipt(
        self,
        donor_id: str,
        receipt_id: str,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._assert_donor_access(donor_id, principal)
        return self.reads.get_receipt_detail(donor_id, receipt_id)

    def list_receipts(
        self, donor_id: str, *, principal: Principal | None = None
    ) -> list[dict[str, Any]]:
        self._assert_donor_access(donor_id, principal)
        return self.reads.list_receipts(donor_id)

    def fund_timeline(
        self, donor_id: str, *, principal: Principal | None = None
    ) -> list[dict[str, Any]]:
        self._assert_donor_access(donor_id, principal)
        return [e.to_dict() for e in self.reads.fund_timeline(donor_id)]

    def allocation_balances(
        self, donor_id: str, *, principal: Principal | None = None
    ) -> list[dict[str, Any]]:
        self._assert_donor_access(donor_id, principal)
        return [b.to_dict() for b in self.reads.allocation_balances(donor_id)]

    def correction_history(
        self,
        donor_id: str,
        receipt_id: str,
        *,
        principal: Principal | None = None,
    ) -> list[dict[str, Any]]:
        self._assert_donor_access(donor_id, principal)
        return self.reads.correction_history(donor_id, receipt_id)

    def evidence_attachments(
        self,
        donor_id: str,
        receipt_id: str,
        *,
        principal: Principal | None = None,
    ) -> list[dict[str, Any]]:
        self._assert_donor_access(donor_id, principal)
        return self.reads.evidence_safe_attachments(donor_id, receipt_id)

    def dashboard(
        self, donor_id: str, *, principal: Principal | None = None
    ) -> dict[str, Any]:
        self._assert_donor_access(donor_id, principal)
        return self.reads.donor_dashboard(donor_id)

    def get_notification_preferences(
        self, donor_id: str, *, principal: Principal | None = None
    ) -> list[dict[str, Any]]:
        self._assert_donor_access(donor_id, principal)
        return self.notifications.get_preferences(donor_id)

    def set_notification_preference(
        self,
        donor_id: str,
        *,
        channel: str | NotificationChannel,
        enabled: bool,
        topics: list[str] | None = None,
        cadence: str = "immediate",
        quiet_hours_start: str | None = None,
        quiet_hours_end: str | None = None,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._assert_donor_access(donor_id, principal)
        ch = (
            channel
            if isinstance(channel, NotificationChannel)
            else NotificationChannel(str(channel))
        )
        pref = NotificationPreference(
            donor_id=donor_id,
            organization_id=self.ws.organization.id,
            channel=ch,
            enabled=enabled,
            topics=tuple(topics or ()),
            cadence=cadence,
            quiet_hours_start=quiet_hours_start,
            quiet_hours_end=quiet_hours_end,
        )
        saved = self.notifications.set_preference(pref)
        return {
            "donor_id": saved.donor_id,
            "channel": saved.channel.value,
            "enabled": saved.enabled,
            "topics": list(saved.topics),
            "cadence": saved.cadence,
            "quiet_hours_start": saved.quiet_hours_start,
            "quiet_hours_end": saved.quiet_hours_end,
        }


def open_donor_api(workspace: TenantWorkspace) -> DonorExperienceAPI:
    return DonorExperienceAPI(workspace)
