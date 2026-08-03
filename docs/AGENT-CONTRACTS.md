# SPEC-007 — Agent Contracts

## Scope

This specification defines the governed agent contracts used by Impact Relay's
`agents/` layer. It aligns with:

- [AGENTS.md](../AGENTS.md)
- [HD-IR-007](HD-IR-007.md)
- `schemas/agents/*.schema.json`
- Contract test files in `tests/test_agent_*`

## Contract model

Agents are allowed to reason and propose; only the domain may mutate money.

```text
Evaluate → Validate → (optional human ApprovalReceipt) → Execute
```

- `evaluate()` emits a proposal.
- `validate()` accepts or rejects that proposal.
- only commands with matching human approval are executable.
- execution always emits an execution receipt and cannot execute side effects for
  simulated runs.

## Authority levels

| Level | Name | Meaning |
|---|---|---|
| `L0` | Observe | Read and inspect only |
| `L1` | Propose | Recommendation output; may propose impactful commands |
| `L2` | Reversible | Low-risk idempotent domain operations |
| `L3` | Human approval required | Always requires explicit `ApprovalReceipt` |

`L3` commands are defined by `L3_COMMAND_TYPES` in
`src/impact_relay/agents/types.py`.

## Core command contract (`AgentCommand`)

| Field | Purpose |
|---|---|
| `command_type` | Domain operation identifier |
| `tenant_id` | Tenant scope for authorization |
| `payload` | Deterministic command input |
| `required_authority` | Command ceiling; auto-upgraded to `L3` for `L3_COMMAND_TYPES` |
| `idempotency_key` | Deterministic dedupe and approval binding key |
| `expires_at` | Optional per-command expiry |

## Core proposal contract (`AgentProposal`)

Proposal is never an authorization token. It is an auditable recommendation.

| Field | Purpose |
|---|---|
| `proposal_id`, `agent_name`, `agent_version` | Traceability |
| `tenant_id`, `policy_version`, `prompt_version` | Scope + governance provenance |
| `input_refs` / `input_hash` | Evidence/input binding for replay |
| `proposed_commands` | Commands to evaluate for execution |
| `evidence_refs` | Evidence attachments |
| `required_authority` / `confidence` | Escalation and review behavior |
| `warnings`, `contradictions` | Human decision hints |
| `expires_at` | Proposal validity bound |
| `idempotency_key` | Cross-run dedupe binding |

A proposal with contradictions, low confidence, or expiry is blocked by
`assert_proposal_executable`.

## Validation contract (`ValidationResult`)

| Field | Status values |
|---|---|
| `status` | `ACCEPTED`, `REJECTED`, `NEEDS_INFORMATION`, `BLOCKED` |
| `reasons` | Blocking rationale |
| `warnings` | Non-blocking observations |

`ValidationResult.ok` is true only for `ACCEPTED`.

## Human approval contract (`ApprovalReceipt`)

| Field | Requirement |
|---|---|
| `approval_id` | Approval receipt id |
| `tenant_id` | Must equal command tenant |
| `proposal_id` | Human decision anchor |
| `command_idempotency_key` | Must equal command key |
| `decision` | `APPROVE`, `REJECT`, `REQUEST_INFORMATION`, `EDIT` |
| `approver_id` | Must be human identity (not `agent:*`) |
| `approver_role` | Role context for audit |
| `approved_at` | Timestamp |

Approval is required for all `L3` and consequential commands.

## Execution contract (`ExecutionReceipt`)

Execution receipts are immutable evidence of side-effect attempts.

| Field | Purpose |
|---|---|
| `execution_id` | Idempotent execution trace id |
| `tenant_id` | Tenant scope |
| `command_type` / `idempotency_key` | Replays are safe and dedupable |
| `status` | `SUCCEEDED`, `FAILED`, `SKIPPED`, `SIMULATED` |
| `output_refs`, `output_hash` | Side-effect evidence |
| `executed_at` | Timestamp |
| `simulated` | true when no mutation occurred |
| `approval_id` | Present for approved L3 execution |
| `error` | Error details for failed/skipped branch |

`SIMULATED` execution mode must emit a receipt without calling domain mutators.

## Run contract (`AgentRunReceipt`)

A wrapper receipt for run-level traceability when workflows execute many agents.
It records:

- run inputs and hashes,
- proposed / accepted / rejected actions,
- human approvals used,
- output references,
- status.

## Hard gates (enforced)

1. **L3 enforcement**

   - `assert_execution_authorized` rejects missing approvals, non-approve
     decisions, tenant mismatch, stale/invalid idempotency, and agent self-approval.

2. **Proposal safety**

   - `assert_proposal_executable` rejects expired proposals, contradictory proposals,
     and low-confidence proposals below block threshold.

3. **Proposal purity**

   - `assert_agent_may_propose` rejects L0 proposals and over-authorized commands.

4. **Schema parity**

   - JSON Schema files under `schemas/agents/*.schema.json` must match dataclasses
     field set and required field list.

5. **Privacy sentinel**

   - Public payloads must satisfy the privacy scan.
   - Banned keys and public classification flags are enforced before publish.

6. **Simulation + idempotency**

   - Simulation cannot dispatch domain mutations.
   - Duplicate command keys should return `SKIPPED` and preserve deterministic
     output hashes.

## Deterministic evidence references

- `tests/test_agent_contracts.py`
- `tests/test_agent_contract_schemas.py`
- `tests/test_agent_import_boundaries.py`
- `tests/test_expense_approval_slice.py`
- `tests/test_expense_approval_slice.py` + `tests/test_workflow_facade_parity.py` for
  proposal/approval/execute path behavior

## Normative file references

- Contract boundaries: `src/impact_relay/agents/types.py`,
  `src/impact_relay/agents/authority.py`,
  `src/impact_relay/agents/base.py`,
  `src/impact_relay/agents/privacy.py`,
  `src/impact_relay/agents/executor.py`,
  `src/impact_relay/agents/expense_workflow.py`
- JSON schemas: `schemas/agents/*.schema.json`

## Conformance hook

`docs/platform-conformance.yml` defines concrete checks for this contract layer and
connects each check to authoritative evidence files.
