"""Bounded agent framework for Impact Relay (v0.5+).

AI proposes. Deterministic services validate. Authorized humans approve.
Agents must not import ledger mutation APIs except through LedgerCommandExecutor.
"""

from impact_relay.agents.authority import AuthorityError, requires_human_approval
from impact_relay.agents.base import AgentContext, CommandExecutor, build_run_receipt
from impact_relay.agents.expense_workflow import (
    AllocationClassifierAgent,
    EvidenceValidatorAgent,
    ExpenseIntakeAgent,
    FinanceReviewAgent,
    FinanceReviewPacket,
    LedgerCommandExecutor,
    NormalizedExpenseImport,
    run_expense_approval_slice,
)
from impact_relay.agents.notification_composer import (
    EmailPreview,
    NotificationComposerAgent,
    compose_email_from_uof,
)
from impact_relay.agents.privacy import PrivacySentinelError, assert_public_safe, scan_public_payload
from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    AgentRunReceipt,
    ApprovalReceipt,
    AuthorityLevel,
    EvidenceSufficiency,
    ExecutionReceipt,
    ValidationResult,
    ValidationStatus,
    WorkflowState,
)

__all__ = [
    "AgentCommand",
    "AgentContext",
    "AgentProposal",
    "AgentRunReceipt",
    "AllocationClassifierAgent",
    "ApprovalReceipt",
    "AuthorityError",
    "AuthorityLevel",
    "CommandExecutor",
    "EvidenceSufficiency",
    "EmailPreview",
    "EvidenceValidatorAgent",
    "ExecutionReceipt",
    "ExpenseIntakeAgent",
    "FinanceReviewAgent",
    "FinanceReviewPacket",
    "LedgerCommandExecutor",
    "NormalizedExpenseImport",
    "NotificationComposerAgent",
    "PrivacySentinelError",
    "ValidationResult",
    "ValidationStatus",
    "WorkflowState",
    "assert_public_safe",
    "build_run_receipt",
    "compose_email_from_uof",
    "requires_human_approval",
    "run_expense_approval_slice",
    "scan_public_payload",
]
