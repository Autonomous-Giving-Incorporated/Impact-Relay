"""Scheduled digest workflow skeleton (PR-L2).

``workflow_type=scheduled_digest``:

  RECEIVED → assemble + privacy gate
    → (optional) PUBLICATION_PENDING WAIT
    → PUBLISHED → DELIVERED (COMPLETED)

No money mutations. Uses ``impact_relay.digest.build_public_digests`` and
privacy scans so public digests never include attendee names / contact data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from impact_relay.agents.privacy import PrivacySentinelError, assert_public_safe
from impact_relay.agents.types import WorkflowState
from impact_relay.digest import (
    DigestError,
    build_public_digests,
    load_events_fixture,
)
from impact_relay.workflows.machine import assert_digest_transition
from impact_relay.workflows.types import (
    SignalType,
    StepResult,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowRunStatus,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _deadline(hours: int = 72) -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
    ).isoformat()


def assemble_digests(
    *,
    events_doc: dict[str, Any] | None = None,
    events_path: Path | str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Build public digests document from fixture or in-memory events."""
    if events_doc is not None:
        doc = events_doc
    elif events_path is not None:
        doc = load_events_fixture(events_path)
    else:
        doc = load_events_fixture()
    digests = build_public_digests(doc, source=source)
    # Stamp sentinel-required privacy flags (fail closed)
    privacy = dict(digests.get("privacy") or {})
    privacy.setdefault("classification", "public_aggregate_only")
    privacy["piiAllowed"] = False
    privacy["donorNamesAllowed"] = False
    privacy["attendeeNamesAllowed"] = False
    privacy["contactDataAllowed"] = False
    digests = {**digests, "privacy": privacy}
    assert_public_safe(digests)
    return digests


def step_assemble_and_privacy(
    *,
    events_doc: dict[str, Any] | None = None,
    events_path: Path | str | None = None,
    source: str | None = None,
    require_approval: bool = False,
    period_key: str | None = None,
    current: WorkflowState = WorkflowState.RECEIVED,
) -> StepResult:
    """Assemble digests, run privacy gate, optionally park for human publish ack."""
    try:
        digests = assemble_digests(
            events_doc=events_doc, events_path=events_path, source=source
        )
    except (DigestError, PrivacySentinelError) as exc:
        assert_digest_transition(current, WorkflowState.BLOCKED)
        return StepResult(
            next_state=WorkflowState.BLOCKED,
            run_status=WorkflowRunStatus.FAILED_TERMINAL,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.ERROR,
                    payload={"error": "digest_privacy_or_assemble_failed", "detail": str(exc)},
                )
            ],
            terminal_reason=str(exc),
            context_patch={"assemble_error": str(exc)},
        )

    summary = digests.get("summary") or {}
    patch: dict[str, Any] = {
        "digests": digests,
        "digest_summary": summary,
        "period_key": period_key,
        "privacy_ok": True,
    }

    if require_approval:
        assert_digest_transition(current, WorkflowState.PUBLICATION_PENDING)
        ack_key = f"ack_digest:{period_key or digests.get('updatedAt') or _new_id('p')}"
        wait = {
            "signal_type": SignalType.APPROVAL.value,
            "command_idempotency_key": ack_key,
            "digest_ack": True,
            "proposal_id": _new_id("prop_dig"),
            # No money command — human gate for digests only confirms publish
            "frozen_command": {
                "command_type": "ack_public_digest",
                "tenant_id": "",  # filled by runtime
                "payload": {
                    "period_key": period_key,
                    "event_count": summary.get("eventCount"),
                },
                "idempotency_key": ack_key,
                "expires_at": None,
                "required_authority": "L3",
                "proposal_id": _new_id("prop_dig"),
                "agent_name": "ScheduledDigestWorkflow",
            },
        }
        return StepResult(
            next_state=WorkflowState.PUBLICATION_PENDING,
            run_status=WorkflowRunStatus.WAITING_SIGNAL,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={
                        "to": WorkflowState.PUBLICATION_PENDING.value,
                        "eventCount": summary.get("eventCount"),
                    },
                )
            ],
            wait_for=SignalType.APPROVAL,
            wait_payload=wait,
            wait_deadline=_deadline(),
            context_patch={**patch, "wait": wait},
        )

    # Auto-publish path: assemble → published → delivered
    assert_digest_transition(current, WorkflowState.PUBLISHED)
    return StepResult(
        next_state=WorkflowState.PUBLISHED,
        run_status=WorkflowRunStatus.PENDING,
        events=[
            WorkflowEventWrite(
                event_type=WorkflowEventType.STATE_CHANGED,
                payload={
                    "to": WorkflowState.PUBLISHED.value,
                    "eventCount": summary.get("eventCount"),
                    "totalAttendancePublic": summary.get("totalAttendancePublic"),
                },
            )
        ],
        context_patch=patch,
    )


def step_complete_digest(
    *,
    current: WorkflowState = WorkflowState.PUBLISHED,
) -> StepResult:
    assert_digest_transition(current, WorkflowState.DELIVERED)
    return StepResult(
        next_state=WorkflowState.DELIVERED,
        run_status=WorkflowRunStatus.COMPLETED,
        events=[
            WorkflowEventWrite(
                event_type=WorkflowEventType.STATE_CHANGED,
                payload={"to": WorkflowState.DELIVERED.value},
            )
        ],
    )
