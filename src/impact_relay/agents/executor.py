"""Sole ledger mutation gateway (K14).

Only this module may import ``impact_relay.domain.ledger`` and call money
mutations. Workflow packages and other agents must go through
``LedgerCommandExecutor``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.base import CommandExecutor
from impact_relay.agents.notification_composer import (
    EmailPreview,
    assert_preview_matches_receipt,
)
from impact_relay.agents.privacy import assert_public_safe
from impact_relay.agents.types import AgentCommand, utc_now_iso
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    AttributionMethod,
    ConsentRecord,
    EvidenceRecord,
    Expense,
    ExpenseState,
    NotificationChannel,
    NotificationPreference,
    money,
)
from impact_relay.public_export import receipt_to_public


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class LedgerCommandExecutor(CommandExecutor):
    """Dispatches approved/reversible commands onto a Ledger instance."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        simulation: bool = False,
        workspace: TenantWorkspace | None = None,
    ) -> None:
        super().__init__(simulation=simulation)
        self.ledger = ledger
        self.workspace = workspace
        # external_source_id -> expense_id for dedup
        self._external_index: dict[str, str] = {
            e.external_source_id: e.id
            for e in ledger.expenses.values()
            if e.external_source_id
        }
        # preview_id -> EmailPreview for send gate
        self.previews: dict[str, EmailPreview] = {}

    def register_preview(self, preview: EmailPreview) -> None:
        self.previews[preview.preview_id] = preview

    def _dispatch(self, command: AgentCommand) -> tuple[list[str], dict[str, Any]]:
        if command.tenant_id != self.ledger.organization.id:
            raise AuthorityError("cross-tenant command rejected")

        if command.command_type == "import_normalized_expense":
            return self._import_normalized(command.payload["expense"])
        if command.command_type == "allocate_expense":
            return self._allocate(command.payload)
        if command.command_type == "approve_expense":
            return self._approve(command.payload)
        if command.command_type == "reject_expense":
            return self._reject(command.payload)
        if command.command_type == "publish_use_of_funds_receipt":
            return self._publish_receipt(command.payload)
        if command.command_type == "send_notification":
            return self._send_notification(command.payload)
        if command.command_type == "reverse_expense":
            return self._reverse_expense(command.payload)
        if command.command_type == "supersede_expense":
            return self._supersede_expense(command.payload)
        raise NotImplementedError(f"unsupported command_type={command.command_type}")

    def _import_normalized(self, row: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        ext = row["external_source_id"]
        if ext in self._external_index:
            eid = self._external_index[ext]
            return [eid], {"expense_id": eid, "duplicate": True}

        expense_id = row.get("expense_id") or _new_id("exp")
        expense = Expense(
            id=expense_id,
            organization_id=self.ledger.organization.id,
            vendor=row["vendor"],
            amount=money(row["amount"]),
            currency=row.get("currency", "USD"),
            purchase_date=row["purchase_date"],
            category=row.get("category", "UNCLASSIFIED"),
            description=row.get("description", ""),
            state=ExpenseState.IMPORTED,
            external_source_id=ext,
        )
        self.ledger.import_expense(expense)
        for ev in row.get("evidence") or []:
            self.ledger.attach_evidence(
                EvidenceRecord(
                    id=ev.get("id") or _new_id("ev"),
                    expense_id=expense_id,
                    kind=ev.get("kind", "invoice"),
                    summary=ev.get("summary", ""),
                    donor_visible=bool(ev.get("donor_visible", True)),
                )
            )
        self._external_index[ext] = expense_id
        return [expense_id], {"expense_id": expense_id, "duplicate": False}

    def _allocate(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        expense_id = payload["expense_id"]
        allocation_id = payload["allocation_id"]
        amount = payload.get("amount")
        if amount is None:
            amount = self.ledger.expenses[expense_id].amount
        ea = self.ledger.allocate_expense(
            expense_id=expense_id,
            allocation_id=allocation_id,
            amount=amount,
        )
        return [ea.id], {"expense_allocation_id": ea.id, "expense_id": expense_id}

    def _approve(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        expense_id = payload["expense_id"]
        approved_by = payload.get("approved_by")
        if not approved_by:
            raise AuthorityError(
                "approve_expense payload requires approved_by from human"
            )
        updated = self.ledger.approve_expense(expense_id, approved_by=approved_by)
        return [expense_id], {"expense_id": expense_id, "state": updated.state.value}

    def _reject(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        expense_id = payload["expense_id"]
        if expense_id not in self.ledger.expenses:
            raise KeyError(expense_id)
        return [expense_id], {
            "expense_id": expense_id,
            "decision": "REJECT",
            "note": payload.get("rationale", ""),
        }

    def _publish_receipt(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        method = payload["attribution_method"]
        if isinstance(method, str):
            method = AttributionMethod(method)
        actor = payload.get("actor") or payload.get("approved_by")
        if not actor:
            raise AuthorityError("publish_use_of_funds_receipt requires actor")
        self.ledger.attribute_donor_to_expense(
            donor_id=payload["donor_id"],
            donation_id=payload["donation_id"],
            expense_id=payload["expense_id"],
            allocation_id=payload["allocation_id"],
            method=method,
            attributed_amount=Decimal(str(payload["attributed_amount"])),
        )
        receipt = self.ledger.publish_use_of_funds_receipt(
            expense_id=payload["expense_id"],
            donation_id=payload["donation_id"],
            allocation_id=payload["allocation_id"],
            actor=actor,
            created_at=payload.get("created_at"),
        )
        public = receipt_to_public(receipt)
        assert_public_safe(public)
        return [receipt.receipt_id], {
            "receipt_id": receipt.receipt_id,
            "public": public,
        }

    def _send_notification(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        if self.workspace is None:
            raise AuthorityError("send_notification requires a TenantWorkspace")
        preview_id = payload.get("preview_id")
        preview = self.previews.get(preview_id) if preview_id else None
        if preview is None:
            raise AuthorityError("send_notification requires a registered email preview")
        receipt_id = payload["receipt_id"]
        receipt = self.ledger.receipts.get(receipt_id)
        if receipt is None:
            raise KeyError(f"receipt not found: {receipt_id}")
        assert_preview_matches_receipt(preview, receipt)
        if payload.get("content_hash") != preview.content_hash:
            raise AuthorityError(
                "send payload content_hash does not match registered preview"
            )
        if payload.get("receipt_hash") != receipt.receipt_hash:
            raise AuthorityError(
                "send payload receipt_hash does not match ledger receipt"
            )

        ns = self.workspace.notifications()
        if not self.workspace.consents.get(
            (receipt.donor_id, NotificationChannel.EMAIL.value)
        ):
            ns.record_consent(
                ConsentRecord(
                    donor_id=receipt.donor_id,
                    organization_id=self.ledger.organization.id,
                    channel=NotificationChannel.EMAIL,
                    granted=True,
                    provenance="fixture://consent/email-v1",
                    recorded_at=utc_now_iso(),
                )
            )
            ns.set_preference(
                NotificationPreference(
                    donor_id=receipt.donor_id,
                    organization_id=self.ledger.organization.id,
                    channel=NotificationChannel.EMAIL,
                    enabled=True,
                    topics=("MONEY_USED", "CORRECTION"),
                )
            )

        intent = ns.evaluate_for_use_of_funds(receipt_id, deliver=True)
        deliveries = [
            d
            for d in self.workspace.deliveries.values()
            if d.intent_id == intent.id
        ]
        delivery = deliveries[-1] if deliveries else None
        refs = [intent.id]
        if delivery:
            refs.append(delivery.id)
        return refs, {
            "intent_id": intent.id,
            "intent_status": intent.status.value,
            "delivery_id": delivery.id if delivery else None,
            "delivery_success": delivery.success if delivery else None,
            "provider_receipt": delivery.provider_receipt if delivery else None,
            "preview_id": preview.preview_id,
        }

    def _reverse_expense(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        """L3 reverse — maps ledger.reverse_expense (K15)."""
        expense_id = payload["expense_id"]
        actor = payload.get("actor") or payload.get("approved_by")
        reason = payload.get("reason") or ""
        if not actor:
            raise AuthorityError("reverse_expense requires actor from human approval")
        if not reason:
            raise AuthorityError("reverse_expense requires reason")
        exp = self.ledger.expenses.get(expense_id)
        if exp is not None and exp.state == ExpenseState.REVERSED:
            # Idempotent no-op success (design: already reversed)
            return [expense_id], {
                "expense_id": expense_id,
                "state": exp.state.value,
                "noop": True,
            }
        reversed_exp, corrections = self.ledger.reverse_expense(
            expense_id, actor=actor, reason=reason
        )
        corr_ids = [c.receipt_id for c in corrections]
        return [expense_id, *corr_ids], {
            "expense_id": expense_id,
            "state": reversed_exp.state.value,
            "correction_receipt_ids": corr_ids,
            "correction_kind": "REVERSAL",
        }

    def _supersede_expense(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        """L3 supersede — maps ledger.supersede_expense (K15)."""
        expense_id = payload["expense_id"]
        actor = payload.get("actor") or payload.get("approved_by")
        reason = payload.get("reason") or ""
        approved_by = payload.get("approved_by") or actor
        if not actor:
            raise AuthorityError("supersede_expense requires actor from human approval")
        if not reason:
            raise AuthorityError("supersede_expense requires reason")
        exp = self.ledger.expenses.get(expense_id)
        if exp is not None and exp.state == ExpenseState.SUPERSEDED:
            return [expense_id], {
                "expense_id": expense_id,
                "state": exp.state.value,
                "noop": True,
            }

        repl_raw = payload.get("replacement") or {}
        if not repl_raw:
            raise AuthorityError("supersede_expense requires replacement expense payload")
        replacement_id = repl_raw.get("id") or repl_raw.get("expense_id") or _new_id("exp")
        replacement = Expense(
            id=replacement_id,
            organization_id=self.ledger.organization.id,
            vendor=repl_raw["vendor"],
            amount=money(repl_raw["amount"]),
            currency=repl_raw.get("currency", "USD"),
            purchase_date=repl_raw["purchase_date"],
            category=repl_raw.get("category", "UNCLASSIFIED"),
            description=repl_raw.get("description", ""),
            state=ExpenseState.IMPORTED,
            external_source_id=repl_raw.get("external_source_id"),
        )
        splits_raw = payload.get("splits") or []
        if not splits_raw:
            raise AuthorityError("supersede_expense requires splits")
        splits: list[tuple[str, Any]] = []
        for item in splits_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                splits.append((str(item[0]), item[1]))
            elif isinstance(item, dict):
                splits.append(
                    (
                        str(item["allocation_id"]),
                        item.get("amount", replacement.amount),
                    )
                )
            else:
                raise AuthorityError(f"invalid split entry: {item!r}")

        superseded, approved, corrections = self.ledger.supersede_expense(
            expense_id,
            replacement=replacement,
            splits=splits,
            actor=actor,
            reason=reason,
            approved_by=approved_by,
        )
        corr_ids = [c.receipt_id for c in corrections]
        if approved.external_source_id:
            self._external_index[approved.external_source_id] = approved.id
        return [expense_id, approved.id, *corr_ids], {
            "expense_id": expense_id,
            "state": superseded.state.value,
            "replacement_expense_id": approved.id,
            "replacement_state": approved.state.value,
            "correction_receipt_ids": corr_ids,
            "correction_kind": "SUPERSEDE",
        }
