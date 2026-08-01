# HD-IR-007 — Agent framework + expense approval vertical slice

## Goal

Establish bounded agent contracts (v0.5) and one complete fixture-backed
expense → human approval → ledger → use-of-funds path (v0.6 slice start),
plus operator polish for live Every.org OBSERVED aggregates.

## What shipped

### A — Agent contracts

| Piece | Location |
|-------|----------|
| Authority levels L0–L3 | `src/impact_relay/agents/types.py`, `authority.py` |
| Command / proposal / approval / execution / run receipts | `agents/types.py` |
| Simulation executor (no domain mutation) | `agents/base.py` |
| Privacy Sentinel | `agents/privacy.py` |
| JSON Schemas | `schemas/agents/*.schema.json` |
| Import boundary tests | `tests/test_agent_import_boundaries.py` |

**Exit gate:** no agent can approve an expense, publish a receipt, or execute
L3 commands without a human `ApprovalReceipt` whose `approver_id` is not `agent:*`.

### B — Vertical slice

```text
expense batch fixture
  → ExpenseIntakeAgent (L2 import proposal)
  → EvidenceValidatorAgent (L0 sufficiency)
  → AllocationClassifierAgent (L1 classification)
  → FinanceReviewAgent (L1 packet + L3 approve proposal)
  → human ApprovalReceipt
  → LedgerCommandExecutor → domain ledger
  → optional L3 publish UOF + Privacy Sentinel on public projection
  → email preview (receipt projection only)
  → independent L3 send approval
  → fixture in-process delivery receipt
```

| Piece | Location |
|-------|----------|
| Workflow | `src/impact_relay/agents/expense_workflow.py` |
| Email preview / send gate | `src/impact_relay/agents/notification_composer.py` |
| Batch fixture | `fixtures/expense_intake_batch_v1.json` |
| CLI | `python -m impact_relay --expense-approval-slice [--send-email]` |

### C — Every.org operator path

| Piece | Location |
|-------|----------|
| Live aggregate validator | `every_org.validate_live_aggregate_file` |
| Dry-run CLI | `--validate-every-org-aggregate PATH` |
| Script dry-run | `scripts/apply_live_every_org_aggregate.sh --dry-run PATH` |

## Commands

```bash
# Agent slice (demo)
python -m impact_relay --expense-approval-slice
python -m impact_relay --expense-approval-slice --no-approve
python -m impact_relay --expense-approval-slice --simulate-agents
python -m impact_relay --expense-approval-slice --send-email

# Live aggregate dry-run (must not be under fixtures/)
python -m impact_relay --validate-every-org-aggregate ~/private/every_org_live.json
./scripts/apply_live_every_org_aggregate.sh --dry-run ~/private/every_org_live.json
```

## Tests

```bash
pytest tests/test_agent_contracts.py tests/test_expense_approval_slice.py \
  tests/test_notification_composer.py tests/test_agent_import_boundaries.py \
  tests/test_live_raised_provenance.py
```

## Versioned policy packs

| Piece | Location |
|-------|----------|
| Loader | `src/impact_relay/policy.py` |
| Hacker Dojo v1.0 | `policies/tenants/hacker-dojo.v1.0.yaml` |

```bash
python -c "from impact_relay.policy import load_tenant_policy; print(load_tenant_policy('org_hacker_dojo').to_dict())"
```

Confidence thresholds, evidence kinds, L3 command lists, and send-approval rules are loaded from the pack and stamped on agent run context.

## Non-goals (this ticket)

- Temporal / durable workflow runtime
- Live accounting provider adapters
- Production email / push delivery
- Authenticated finance console UI
- Autonomous expense approval
