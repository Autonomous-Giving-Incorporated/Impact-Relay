"""Phase 4 — programs, funded assets, impact events, IMPACT receipts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from impact_relay.domain.types import (
    VERIFIED_EXPENSE_STATES,
    AssetLifecycle,
    FundedAsset,
    ImpactEvent,
    ImpactEventState,
    ImpactReceipt,
    NotFoundError,
    Program,
    StateError,
)

if TYPE_CHECKING:
    from impact_relay.domain.tenant import TenantWorkspace


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _stable_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ImpactService:
    def __init__(self, workspace: TenantWorkspace) -> None:
        self.ws = workspace
        self.ledger = workspace.ledger

    def register_program(self, program: Program) -> Program:
        if program.organization_id != self.ledger.organization.id:
            raise StateError("program organization_id mismatch")
        self.ws.programs[program.id] = program
        return program

    def register_funded_asset(self, asset: FundedAsset) -> FundedAsset:
        if asset.organization_id != self.ledger.organization.id:
            raise StateError("asset organization_id mismatch")
        exp = self.ledger.expenses.get(asset.expense_id)
        if exp is None:
            raise NotFoundError(f"expense not found: {asset.expense_id}")
        if exp.state not in VERIFIED_EXPENSE_STATES:
            raise StateError("funded asset requires APPROVED or RECONCILED expense")
        if asset.allocation_id not in self.ledger.allocations:
            raise NotFoundError(f"allocation not found: {asset.allocation_id}")
        self.ws.assets[asset.id] = asset
        return asset

    def deploy_asset(self, asset_id: str) -> FundedAsset:
        asset = self.ws.assets.get(asset_id)
        if asset is None:
            raise NotFoundError(f"asset not found: {asset_id}")
        from dataclasses import replace

        updated = replace(asset, lifecycle=AssetLifecycle.DEPLOYED)
        self.ws.assets[asset_id] = updated
        return updated

    def submit_impact_event(self, event: ImpactEvent) -> ImpactEvent:
        if event.organization_id != self.ledger.organization.id:
            raise StateError("impact event organization_id mismatch")
        if event.program_id not in self.ws.programs:
            raise NotFoundError(f"program not found: {event.program_id}")
        if event.state not in (ImpactEventState.DRAFT, ImpactEventState.SUBMITTED):
            raise StateError("submit only accepts DRAFT or SUBMITTED")
        for aid in event.funded_asset_ids:
            if aid not in self.ws.assets:
                raise NotFoundError(f"funded asset not found: {aid}")
        for eid in event.expense_ids:
            if eid not in self.ledger.expenses:
                raise NotFoundError(f"expense not found: {eid}")
        from dataclasses import replace

        submitted = replace(event, state=ImpactEventState.SUBMITTED)
        self.ws.impact_events[submitted.id] = submitted
        return submitted

    def verify_impact_event(self, event_id: str, *, verified_by: str) -> ImpactEvent:
        event = self.ws.impact_events.get(event_id)
        if event is None:
            raise NotFoundError(f"impact event not found: {event_id}")
        if event.state not in (ImpactEventState.SUBMITTED, ImpactEventState.DRAFT):
            raise StateError(f"cannot verify impact event in state {event.state.value}")
        if not verified_by:
            raise StateError("verified_by is required")
        from dataclasses import replace

        verified = replace(
            event,
            state=ImpactEventState.VERIFIED,
            verified_by=verified_by,
            verified_at=_now_iso(),
        )
        self.ws.impact_events[event_id] = verified
        return verified

    def publish_impact_receipts(
        self,
        event_id: str,
        *,
        actor: str,
        created_at: str | None = None,
    ) -> list[ImpactReceipt]:
        """Publish IMPACT receipts for donors attributed to linked verified expenses."""
        event = self.ws.impact_events.get(event_id)
        if event is None:
            raise NotFoundError(f"impact event not found: {event_id}")
        if event.state != ImpactEventState.VERIFIED:
            raise StateError(
                f"IMPACT receipt requires VERIFIED impact event; got {event.state.value}"
            )
        program = self.ws.programs[event.program_id]
        created = created_at or _now_iso()

        # Eligible: attributions on linked expenses (or assets' expenses) that are verified.
        expense_ids = set(event.expense_ids)
        for aid in event.funded_asset_ids:
            asset = self.ws.assets[aid]
            expense_ids.add(asset.expense_id)

        if not expense_ids:
            raise StateError("impact event has no linked expenses or funded assets")

        receipts: list[ImpactReceipt] = []
        # One receipt per donor+donation+allocation linked to those expenses
        seen: set[tuple[str, str, str]] = set()
        for attr in self.ledger.attributions.values():
            if attr.expense_id not in expense_ids:
                continue
            exp = self.ledger.expenses.get(attr.expense_id)
            if exp is None or exp.state not in VERIFIED_EXPENSE_STATES:
                continue
            # Prefer one IMPACT receipt per donor+allocation+event
            dkey = (attr.donor_id, attr.allocation_id, event_id)
            if dkey in seen:
                continue
            # Only if a live UOF exists or attribution is on verified expense
            seen.add(dkey)
            alloc = self.ledger.allocations[attr.allocation_id]
            receipt_id = _new_id("imp")
            body = {
                "type": "IMPACT",
                "organization_id": self.ledger.organization.id,
                "donor_id": attr.donor_id,
                "donation_id": attr.donation_id,
                "allocation_id": attr.allocation_id,
                "impact_event_id": event_id,
                "program_id": program.id,
                "event_type": event.event_type,
                "event_date": event.event_date,
                "participants": event.participants,
                "created_at": created,
            }
            receipt_hash = _stable_hash(body)
            # Block duplicate live IMPACT for same donor+event+allocation
            existing = self._find_live_impact(attr.donor_id, event_id, attr.allocation_id)
            if existing is not None:
                raise StateError(
                    f"IMPACT receipt already published for donor/event/allocation "
                    f"(receipt_id={existing.receipt_id})"
                )
            ir = ImpactReceipt(
                receipt_id=receipt_id,
                type="IMPACT",
                organization_id=self.ledger.organization.id,
                organization_name=self.ledger.organization.name,
                donor_id=attr.donor_id,
                donation_id=attr.donation_id,
                allocation_id=attr.allocation_id,
                allocation_name=alloc.name,
                impact_event_id=event_id,
                program_id=program.id,
                program_name=program.name,
                event_type=event.event_type,
                event_date=event.event_date,
                participants=event.participants,
                evidence_state=event.state.value,
                linked_expense_ids=tuple(sorted(expense_ids)),
                attribution_method=attr.method.value,
                policy_version=self.ledger.organization.policy_version,
                receipt_hash=receipt_hash,
                created_at=created,
                description=event.description,
                provenance={
                    "actor": actor,
                    "policy_version": self.ledger.organization.policy_version,
                },
            )
            self.ws.impact_receipts[receipt_id] = ir
            receipts.append(ir)
        return receipts

    def _find_live_impact(
        self, donor_id: str, event_id: str, allocation_id: str
    ) -> ImpactReceipt | None:
        for ir in self.ws.impact_receipts.values():
            if (
                ir.donor_id == donor_id
                and ir.impact_event_id == event_id
                and ir.allocation_id == allocation_id
            ):
                return ir
        return None
