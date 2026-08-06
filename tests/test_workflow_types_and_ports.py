"""PR-M1: workflow types, ports, exception taxonomy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.types import (
    ApprovalReceipt,
    ExecutionReceipt,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.domain.types import InvariantError, StateError
from impact_relay.workflows import (
    CLAIMABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    AdvanceCommitBundle,
    ErrorClass,
    FrozenProposedCommand,
    RetryPolicy,
    SignalType,
    StepResult,
    SystemClock,
    UuidIdGenerator,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowSignal,
    WorkflowStore,
    WorkflowType,
    classify_error,
    is_retryable,
    is_terminal,
)
from impact_relay.workflows.ports import LedgerBinding


def test_workflow_run_status_claimable_set() -> None:
    assert WorkflowRunStatus.PENDING in CLAIMABLE_RUN_STATUSES
    assert WorkflowRunStatus.RETRY_SCHEDULED in CLAIMABLE_RUN_STATUSES
    assert WorkflowRunStatus.WAITING_SIGNAL not in CLAIMABLE_RUN_STATUSES
    assert WorkflowRunStatus.COMPLETED in TERMINAL_RUN_STATUSES
    assert WorkflowRunStatus.DEAD_LETTER in TERMINAL_RUN_STATUSES


def test_retry_policy_backoff_caps() -> None:
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=900.0)
    assert policy.delay_for_attempt(1) == 1.0
    assert policy.delay_for_attempt(2) == 2.0
    assert policy.delay_for_attempt(3) == 4.0
    assert policy.delay_for_attempt(20) == 900.0


def test_frozen_command_roundtrip() -> None:
    frozen = FrozenProposedCommand(
        command_type="approve_expense",
        tenant_id="org_hacker_dojo",
        payload={"expense_id": "exp_1", "packet_id": "pkt_1"},
        idempotency_key="approve:exp_1:pkt_1",
        expires_at="2099-01-01T00:00:00+00:00",
        required_authority="L3",
        proposal_id="prop_1",
        agent_name="finance_review",
    )
    restored = FrozenProposedCommand.from_dict(frozen.to_dict())
    assert restored.idempotency_key == frozen.idempotency_key
    assert restored.payload["expense_id"] == "exp_1"


def test_workflow_instance_to_dict() -> None:
    inst = WorkflowInstance(
        workflow_id="wf_1",
        tenant_id="org_hacker_dojo",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="acct_exp_1",
        workflow_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.WAITING_SIGNAL,
        simulation=False,
        context={"expense_id": "exp_1"},
    )
    body = inst.to_dict()
    assert body["workflow_state"] == "REVIEW_PENDING"
    assert body["run_status"] == "WAITING_SIGNAL"
    assert body["workflow_type"] == "expense_to_receipt"


def test_step_result_human_gate_shape() -> None:
    frozen = FrozenProposedCommand(
        command_type="approve_expense",
        tenant_id="org_x",
        payload={"expense_id": "e"},
        idempotency_key="k",
        expires_at=None,
        required_authority="L3",
        proposal_id="p",
        agent_name="finance_review",
    )
    result = StepResult(
        next_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.WAITING_SIGNAL,
        wait_for=SignalType.APPROVAL,
        wait_payload={"frozen_command": frozen.to_dict()},
        wait_deadline=datetime.now(UTC) + timedelta(days=7),
        events=[
            WorkflowEventWrite(
                event_type=WorkflowEventType.STATE_CHANGED,
                payload={"to": "REVIEW_PENDING"},
            )
        ],
    )
    assert result.wait_for == SignalType.APPROVAL
    assert result.commands_to_execute == []


def test_workflow_signal_approval_receipt() -> None:
    approval = ApprovalReceipt(
        approval_id="appr_1",
        tenant_id="org_x",
        proposal_id="prop_1",
        command_idempotency_key="approve:e:p",
        decision="APPROVE",
        approver_id="human@example.org",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
    )
    from impact_relay.agents.types import to_jsonable

    sig = WorkflowSignal(
        signal_id="sig_1",
        workflow_id="wf_1",
        tenant_id="org_x",
        signal_type=SignalType.APPROVAL,
        payload=to_jsonable(approval),
        created_at=utc_now_iso(),
    )
    got = sig.approval_receipt()
    assert got is not None
    assert got.approver_id == "human@example.org"
    assert got.command_idempotency_key == "approve:e:p"


def test_advance_commit_bundle_fields() -> None:
    inst = WorkflowInstance(
        workflow_id="wf_1",
        tenant_id="org_x",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk",
        workflow_state=WorkflowState.LEDGER_COMMITTED,
        run_status=WorkflowRunStatus.PENDING,
    )
    receipt = ExecutionReceipt(
        execution_id="exec_1",
        tenant_id="org_x",
        command_type="approve_expense",
        idempotency_key="k",
        status="SUCCEEDED",
        output_refs=["exp_1"],
        output_hash="abc",
        executed_at=utc_now_iso(),
    )
    from impact_relay.workflows.types import SignalConsumeResult

    bundle = AdvanceCommitBundle(
        tenant_id="org_x",
        workflow_id="wf_1",
        instance=inst,
        execution_receipts=[receipt],
        consume_signals=[("sig_1", SignalConsumeResult.ACCEPTED)],
    )
    assert bundle.instance.workflow_state == WorkflowState.LEDGER_COMMITTED
    assert len(bundle.execution_receipts) == 1


def test_classify_authority_terminal() -> None:
    c = classify_error(AuthorityError("requires human"))
    assert c.error_class == ErrorClass.TERMINAL
    assert is_terminal(AuthorityError("x"))
    assert not is_retryable(AuthorityError("x"))


def test_classify_invariant_terminal() -> None:
    c = classify_error(InvariantError("balance would go negative"))
    assert c.terminal


def test_classify_state_already_applied() -> None:
    c = classify_error(StateError("expense already approved"))
    assert c.already_applied


def test_classify_unknown_retryable() -> None:
    c = classify_error(RuntimeError("transient glitch"))
    assert c.retryable


def test_classify_connection_retryable() -> None:
    c = classify_error(ConnectionError("db gone"))
    assert c.retryable


def test_system_clock_and_id_generator() -> None:
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert "T" in clock.now_iso()
    gen = UuidIdGenerator()
    a = gen.new_id("wf")
    b = gen.new_id("wf")
    assert a.startswith("wf_")
    assert a != b


def test_workflow_store_is_runtime_checkable_protocol() -> None:
    assert isinstance(WorkflowStore, type)

    class StubStore:
        def create(self, instance): ...
        def get(self, tenant_id, workflow_id): ...
        def get_by_business_key(self, tenant_id, workflow_type, business_key): ...
        def list(self, tenant_id, *, workflow_state=None, run_status=None, limit=100): ...
        def claim(self, *, worker_id, limit, now, lease_ttl): ...
        def update_instance(self, instance): ...
        def append_events(self, tenant_id, workflow_id, events): ...
        def list_events(self, tenant_id, workflow_id): ...
        def enqueue_signal_and_wake(
            self, *, tenant_id, workflow_id, signal, new_run_status, next_run_at, clear_lease
        ): ...
        def take_unconsumed_signals(self, tenant_id, workflow_id): ...
        def mark_signal_consumed(self, tenant_id, signal_id, result): ...
        def put_execution_receipt(self, receipt, *, workflow_id): ...
        def get_execution_receipt(self, tenant_id, idempotency_key): ...
        def commit_advance(self, bundle): ...

    assert isinstance(StubStore(), WorkflowStore)


def test_ledger_binding_protocol_structural() -> None:
    class T1Binding:
        def for_tenant(self, tenant_id: str):
            return object()

        def workspace(self, tenant_id: str):
            return None

        def rehydrate(self, tenant_id: str):
            return self.for_tenant(tenant_id)

        def append_command_result(self, **kwargs):
            return None

        def durability_mode(self) -> str:
            return "none"

    assert isinstance(T1Binding(), LedgerBinding)


def test_dual_axis_human_gate_mapping() -> None:
    """REVIEW_PENDING pairs with WAITING_SIGNAL until signal wake → PENDING."""
    parked = WorkflowInstance(
        workflow_id="wf",
        tenant_id="org",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk",
        workflow_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.WAITING_SIGNAL,
    )
    woken = WorkflowInstance(
        workflow_id="wf",
        tenant_id="org",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk",
        workflow_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.PENDING,
    )
    assert parked.run_status not in CLAIMABLE_RUN_STATUSES
    assert woken.run_status in CLAIMABLE_RUN_STATUSES
