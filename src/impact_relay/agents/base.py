"""Agent evaluation boundary and command executor interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from impact_relay.agents.authority import (
    AuthorityError,
    assert_agent_may_propose,
    assert_execution_authorized,
    assert_proposal_executable,
)
from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    AgentRunReceipt,
    AgentRunStatus,
    ApprovalReceipt,
    AuthorityLevel,
    ExecutionReceipt,
    ValidationResult,
    ValidationStatus,
    stable_hash,
    to_jsonable,
    utc_now_iso,
)


@dataclass
class AgentContext:
    """Read-only context passed into agent.evaluate / validate."""

    tenant_id: str
    policy_version: str = "v1.0"
    prompt_version: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    now: str | None = None


class Agent(Protocol):
    name: str
    version: str
    authority_level: AuthorityLevel

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal:
        ...

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult:
        ...


class CommandExecutor:
    """Executes approved commands. Subclasses implement domain side-effects.

    Simulation mode records intents without mutating domain state.
    """

    def __init__(self, *, simulation: bool = False) -> None:
        self.simulation = simulation
        self._seen_keys: set[str] = set()
        self.receipts: list[ExecutionReceipt] = []

    def execute(
        self,
        command: AgentCommand,
        *,
        approval: ApprovalReceipt | None = None,
        agent_name: str | None = None,
        proposal: AgentProposal | None = None,
    ) -> ExecutionReceipt:
        if proposal is not None:
            assert_proposal_executable(proposal)
        assert_execution_authorized(command, approval, agent_name=agent_name)

        if command.idempotency_key in self._seen_keys:
            receipt = ExecutionReceipt(
                execution_id=f"exec_dup_{command.idempotency_key[:12]}",
                tenant_id=command.tenant_id,
                command_type=command.command_type,
                idempotency_key=command.idempotency_key,
                status="SKIPPED",
                output_refs=[],
                output_hash=stable_hash({"duplicate": True}),
                executed_at=utc_now_iso(),
                simulated=self.simulation,
                error="duplicate idempotency_key",
                approval_id=approval.approval_id if approval else None,
            )
            self.receipts.append(receipt)
            return receipt

        if self.simulation:
            receipt = ExecutionReceipt(
                execution_id=f"exec_sim_{command.idempotency_key[:12]}",
                tenant_id=command.tenant_id,
                command_type=command.command_type,
                idempotency_key=command.idempotency_key,
                status="SIMULATED",
                output_refs=[],
                output_hash=stable_hash({"simulated": True, "payload": command.payload}),
                executed_at=utc_now_iso(),
                simulated=True,
                approval_id=approval.approval_id if approval else None,
            )
            self._seen_keys.add(command.idempotency_key)
            self.receipts.append(receipt)
            return receipt

        try:
            output_refs, output_payload = self._dispatch(command)
            receipt = ExecutionReceipt(
                execution_id=f"exec_{command.idempotency_key[:12]}",
                tenant_id=command.tenant_id,
                command_type=command.command_type,
                idempotency_key=command.idempotency_key,
                status="SUCCEEDED",
                output_refs=output_refs,
                output_hash=stable_hash(output_payload),
                executed_at=utc_now_iso(),
                simulated=False,
                approval_id=approval.approval_id if approval else None,
            )
            self._seen_keys.add(command.idempotency_key)
        except Exception as exc:  # noqa: BLE001 — surface domain failures as receipts
            receipt = ExecutionReceipt(
                execution_id=f"exec_fail_{command.idempotency_key[:12]}",
                tenant_id=command.tenant_id,
                command_type=command.command_type,
                idempotency_key=command.idempotency_key,
                status="FAILED",
                output_refs=[],
                output_hash=stable_hash({"error": str(exc)}),
                executed_at=utc_now_iso(),
                simulated=False,
                error=str(exc),
                approval_id=approval.approval_id if approval else None,
            )
        self.receipts.append(receipt)
        return receipt

    def _dispatch(self, command: AgentCommand) -> tuple[list[str], dict[str, Any]]:
        raise NotImplementedError(
            f"no handler for command_type={command.command_type!r}"
        )


def build_run_receipt(
    *,
    run_id: str,
    tenant_id: str,
    workflow: str,
    agent: str,
    agent_version: str,
    policy_version: str,
    prompt_version: str | None,
    input_refs: list[str],
    input_payload: Any,
    proposals: list[AgentProposal],
    validations: list[ValidationResult],
    approvals: list[ApprovalReceipt],
    executions: list[ExecutionReceipt],
    started_at: str,
    status: AgentRunStatus | None = None,
) -> AgentRunReceipt:
    proposed = [c.command_type for p in proposals for c in p.proposed_commands]
    accepted = [
        e.command_type for e in executions if e.status in ("SUCCEEDED", "SIMULATED")
    ]
    rejected = [
        e.command_type
        for e in executions
        if e.status in ("FAILED", "SKIPPED")
    ] + [
        "validation"
        for v in validations
        if v.status
        in (ValidationStatus.REJECTED, ValidationStatus.BLOCKED, ValidationStatus.NEEDS_INFORMATION)
    ]
    outputs = [ref for e in executions for ref in e.output_refs]
    if status is None:
        if any(e.status == "FAILED" for e in executions):
            status = AgentRunStatus.FAILED
        elif any(e.simulated for e in executions):
            status = AgentRunStatus.SIMULATED
        elif any(
            v.status == ValidationStatus.BLOCKED for v in validations
        ) or any(e.status == "SKIPPED" for e in executions):
            status = AgentRunStatus.PARTIAL
        else:
            status = AgentRunStatus.SUCCEEDED
    completed = utc_now_iso()
    body = {
        "proposed": proposed,
        "accepted": accepted,
        "outputs": outputs,
    }
    return AgentRunReceipt(
        run_id=run_id,
        tenant_id=tenant_id,
        workflow=workflow,
        agent=agent,
        agent_version=agent_version,
        policy_version=policy_version,
        prompt_version=prompt_version,
        input_refs=input_refs,
        input_hash=stable_hash(input_payload),
        proposed_actions=proposed,
        accepted_actions=accepted,
        rejected_actions=rejected,
        human_approvals=[a.approval_id for a in approvals],
        output_refs=outputs,
        output_hash=stable_hash(body),
        started_at=started_at,
        completed_at=completed,
        status=status,
    )


def proposal_to_dict(proposal: AgentProposal) -> dict[str, Any]:
    return to_jsonable(proposal)


__all__ = [
    "Agent",
    "AgentContext",
    "AuthorityError",
    "CommandExecutor",
    "assert_agent_may_propose",
    "build_run_receipt",
    "proposal_to_dict",
]
