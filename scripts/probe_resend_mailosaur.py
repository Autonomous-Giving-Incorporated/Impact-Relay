#!/usr/bin/env python3
"""Optional live probe: Resend adapter -> Mailosaur capture inbox.

Skips without ``IMPACT_RELAY_RESEND_API_KEY``/``RESEND_API_KEY`` and
``MAILOSAUR_API_KEY``. Default pytest never imports this script. Production
notification activation stays host-owned and NOT_ACTIVATED.

Sends only to a Mailosaur address. Deletes the captured message after
assertions. Does not log API keys, tokens, or donor PII.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from impact_relay.agents.expense_workflow import LedgerCommandExecutor, run_expense_approval_slice
from impact_relay.agents.notification_composer import compose_email_from_uof
from impact_relay.agents.types import AgentCommand, ApprovalReceipt, AuthorityLevel, utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    ConsentRecord,
    NotificationChannel,
    NotificationPreference,
)
from impact_relay.notifications import ResendConfig, ResendEmailAdapter
from impact_relay.notifications.mailosaur import (
    DEFAULT_MAILOSAUR_SERVER_ID,
    MailosaurClient,
    inbox_address,
    is_mailosaur_configured,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"
DEFAULT_LOCAL_PART = "ir-p8"


def _skip(reason: str) -> int:
    print(json.dumps({"status": "skipped", "reason": reason}, indent=2))
    return 0


def _from_address() -> str:
    return (
        os.environ.get("IMPACT_RELAY_RESEND_FROM")
        or os.environ.get("RESEND_FROM")
        or os.environ.get("AUTH_EMAIL_FROM")
        or ""
    ).strip()


def _api_key() -> str:
    return (
        os.environ.get("IMPACT_RELAY_RESEND_API_KEY") or os.environ.get("RESEND_API_KEY") or ""
    ).strip()


def _recipient() -> str:
    assigned = os.environ.get("MAILOSAUR_ASSIGNED_EMAIL", "").strip()
    if assigned:
        return assigned
    server = os.environ.get("MAILOSAUR_SERVER_ID", DEFAULT_MAILOSAUR_SERVER_ID)
    local = os.environ.get("MAILOSAUR_LOCAL_PART", DEFAULT_LOCAL_PART)
    return inbox_address(server, local)


def _ledger_with_receipt():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    rows = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]
    result = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=[
            {
                "donor_id": "donor_alice",
                "donation_id": "don_1000_alice",
                "allocation_id": "alloc_community_hardware",
                "attribution_method": "DIRECT_RESTRICTED",
                "attributed_amount": "720.00",
                "created_at": "2026-08-12T12:00:00+00:00",
            }
        ],
        send_email=False,
    )
    return ledger, result.receipts[0]


def main() -> int:
    if not _api_key():
        return _skip("resend_api_key_missing")
    if not _from_address():
        return _skip("resend_from_missing")
    if not is_mailosaur_configured(os.environ):
        return _skip("mailosaur_not_configured")

    recipient = _recipient()
    if not recipient.endswith(".mailosaur.net"):
        print(json.dumps({"status": "blocked", "reason": "recipient_must_be_mailosaur"}, indent=2))
        return 2

    received_after = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    ledger, receipt = _ledger_with_receipt()
    workspace = TenantWorkspace(ledger.organization, ledger=ledger)
    adapter = ResendEmailAdapter(
        ResendConfig(api_key=_api_key(), from_address=_from_address()),
        address_resolver=lambda _intent: recipient,
    )
    workspace.configure_notification_adapters({NotificationChannel.EMAIL: adapter})
    workspace.notifications().record_consent(
        ConsentRecord(
            donor_id=receipt.donor_id,
            organization_id=receipt.organization_id,
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="probe://mailosaur/resend",
            recorded_at=utc_now_iso(),
        )
    )
    workspace.notifications().set_preference(
        NotificationPreference(
            donor_id=receipt.donor_id,
            organization_id=receipt.organization_id,
            channel=NotificationChannel.EMAIL,
            enabled=True,
            topics=("MONEY_USED", "CORRECTION"),
        )
    )
    preview = compose_email_from_uof(receipt)
    executor = LedgerCommandExecutor(ledger, workspace=workspace)
    executor.register_preview(preview)
    command = AgentCommand(
        command_type="send_notification",
        tenant_id=preview.tenant_id,
        payload={
            "preview_id": preview.preview_id,
            "receipt_id": preview.receipt_id,
            "content_hash": preview.content_hash,
            "receipt_hash": preview.receipt_hash,
            "channel": "EMAIL",
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
    )
    approval = ApprovalReceipt(
        approval_id="resend-mailosaur-probe",
        tenant_id=preview.tenant_id,
        proposal_id="resend-mailosaur-proposal",
        command_idempotency_key=command.idempotency_key,
        decision="APPROVE",
        approver_id="probe.approver@example.org",
        approver_role="communications_approver",
        approved_at=utc_now_iso(),
    )
    execution = executor.execute(
        command,
        approval=approval,
        agent_name="notification_composer",
    )
    if execution.status != "SUCCEEDED":
        print(
            json.dumps(
                {
                    "status": "failed",
                    "phase": "governed_send",
                    "execution_status": execution.status,
                    "error": execution.error,
                },
                indent=2,
            )
        )
        return 1

    client = MailosaurClient(
        api_key=os.environ["MAILOSAUR_API_KEY"],
        server_id=os.environ.get("MAILOSAUR_SERVER_ID", DEFAULT_MAILOSAUR_SERVER_ID),
    )
    captured = client.wait_for_message(
        recipient,
        received_after=received_after,
        timeout_seconds=30,
        interval_seconds=1,
    )
    ok = preview.subject == captured["subject"] and preview.body_text in captured["text"]
    if captured.get("id"):
        client.delete_message(captured["id"])
    report = {
        "status": "observed" if ok else "mismatch",
        "backend": "resend",
        "provider": "resend",
        "recipient_domain": "mailosaur.net",
        "subject_matches": preview.subject == captured["subject"],
        "body_matches": preview.body_text in captured["text"],
        "subject": captured["subject"],
        "text_preview": captured["text"][:240],
        "message_deleted": True,
        "production_notifications": "NOT_ACTIVATED",
        "provenance": "pilot_synthetic",
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
