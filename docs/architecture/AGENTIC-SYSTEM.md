# Agentic System Architecture

## Purpose

This document defines how Impact Relay uses agents to move evidence through a governed workflow without allowing model output to become financial truth.

## System boundary

```text
Donation and accounting providers
        │
        ▼
Provider adapters
        │ normalized records
        ▼
Agent workflow layer
        │ proposals, evidence assessments, review packets
        ▼
Human approval gates
        │ approved commands
        ▼
Deterministic domain services
        │ ledger events and canonical receipts
        ▼
Donor projections and notification adapters
```

The current domain in `src/impact_relay/domain/` remains authoritative for money invariants, receipt lineage, donor projections, consent policy, impact records, and tenant isolation. The agent layer wraps these capabilities; it does not replace them.

## Recommended deployment shape

Start as a modular monolith:

```text
Hacker Dojo App
       │
       ▼
Impact Relay API
       │
       ├── Identity and consent
       ├── Donation and expense ledger
       ├── Attribution
       ├── Evidence
       ├── Programs and assets
       ├── Receipts
       ├── Notifications
       ├── Agent workflows
       └── Audit
               │
               ▼
        PostgreSQL + object storage
               │
       ┌──────┬────────┐
       ▼                ▼
 Workflow workers   Provider adapters
```

Do not split into microservices until independently scaling or isolating a boundary is an observed requirement.

## Recommended production stack

> **Aspirational, not current.** This table describes what a host would deploy
> at production scale. The shipped library is **stdlib-only with zero runtime
> dependencies** (`http.server`, `sqlite3`, a restricted YAML-subset policy
> loader) and requires Python ≥ 3.11. Postgres, S3, and JWKS validation are
> opt-in extras (`[db]`, `[s3]`, `[oidc]`). Do not add a runtime dependency to
> the library on the strength of this table — see `CLAUDE.md`.

| Boundary | Recommendation |
|---|---|
| Language | Python 3.12 |
| API | FastAPI |
| Validation | Pydantic v2 + JSON Schema |
| Database | PostgreSQL |
| Persistence | SQLAlchemy 2 + Alembic |
| Durable workflow | **Pilot default:** bounded SQL worker (SQLite local / Postgres + SKIP LOCKED) with co-durable ledger command log. Temporal remains a scale-up option |
| Evidence storage | S3-compatible encrypted object storage |
| Identity | OIDC |
| Policy | versioned YAML evaluated by deterministic application code |
| Observability | OpenTelemetry, structured logs, Prometheus-compatible metrics |
| Email | Shipped: standard-library SMTP, Postmark, and Resend adapters. Resend is the AGI suite-aligned HTTP backend. Other scale options: SendGrid or SES adapter |
| SMS | Twilio adapter after explicit-consent validation |
| Push | APNs and FCM adapters |

## Core workflows

### Expense to use-of-funds receipt

```text
RECEIVED
→ NORMALIZED
→ EVIDENCE_PENDING          # evidence before classify (runtime machine)
→ CLASSIFICATION_PENDING
→ REVIEW_PENDING            # human L3 gate
→ LEDGER_COMMITTED          # APPROVED is audit-only, not a parked cursor
→ RECEIPT_DRAFTED
→ PUBLICATION_PENDING       # optional human publish gate
→ PUBLISHED
→ NOTIFICATION_PENDING      # optional human send gate
→ DELIVERED
```

1. Expense Intake normalizes a provider record.
2. Duplicate detection prevents replay.
3. **Evidence Validator** determines whether evidence is sufficient and safe to expose (**before** classification).
4. Allocation Classifier proposes one or more fund splits (only when evidence allows).
5. Finance Review prepares a decision packet.
6. An authorized human approves, rejects, edits, or requests information (`ApprovalReceipt`).
7. The deterministic ledger validates money invariants and commits the approved action (sole gateway: `LedgerCommandExecutor`).
8. Attribution proposes a reproducible donor relationship.
9. The receipt service creates a canonical use-of-funds receipt.
10. A communications approver authorizes publication and delivery when enabled.
11. Consent policy selects allowed channels and cadence.
12. Delivery adapters send and record delivery receipts.

**Runtime:** `src/impact_relay/workflows/` (expense_to_receipt, correction, scheduled_digest). Durable pilot: `docs/DURABLE-QUICKSTART.md`.

### Program event to impact receipt

```text
Expense
→ Funded asset or program budget
→ Program occurrence
→ Evidence collection
→ Program verifier review
→ Verified impact event
→ Impact receipt
→ Donor notification
```

A scheduled event is never sufficient. Completion and evidence must be verified before publication.

### Correction and retraction

```text
Discrepancy detected
→ correction workflow (workflow_type=correction)
→ frozen reverse_expense | supersede_expense (L3)
→ human ApprovalReceipt
→ ledger reverse/supersede (append-only correction receipts)
→ complete (prior UOF receipts never rewritten)
```

K15: `reverse_expense` / `supersede_expense` are explicit L3 command types — not L1 aliases.

Original receipts remain immutable and visible in lineage.

## Agent contracts

### Agent command

```yaml
command_id: string
tenant_id: string
workflow_id: string
command_type: string
input_refs: []
idempotency_key: string
requested_by: string
requested_at: datetime
```

### Agent proposal

```yaml
proposal_id: string
command_id: string
agent_name: string
agent_version: string
policy_version: string
prompt_version: string | null
proposed_actions: []
evidence_refs: []
confidence: decimal | null
warnings: []
contradictions: []
required_authority: L0 | L1 | L2 | L3
expires_at: datetime
proposal_hash: string
```

### Approval receipt

```yaml
approval_id: string
proposal_id: string
tenant_id: string
actor_id: string
actor_role: string
decision: APPROVE | REJECT | EDIT | REQUEST_INFORMATION
decision_payload_hash: string
reason: string | null
approved_at: datetime
```

### Execution receipt

> **Design sketch.** The implemented contract is
> `impact_relay.agents.types.ExecutionReceipt`, specified by
> [`schemas/agents/execution-receipt.schema.json`](../../schemas/agents/execution-receipt.schema.json)
> and kept in sync by `tests/test_agent_contract_schemas.py`. It differs from
> the sketch below: it carries `tenant_id`, `idempotency_key`, `output_refs`,
> and `simulated`; it has no `proposal_id`, `aggregate_refs`, or `event_refs`;
> and its statuses are `SUCCEEDED | FAILED | SKIPPED | SIMULATED` (no
> `PARTIAL`). Build against the schema, not this block.

```yaml
execution_id: string
proposal_id: string
approval_id: string | null
command_type: string
aggregate_refs: []
event_refs: []
output_hash: string
executed_at: datetime
status: SUCCEEDED | FAILED | PARTIAL
```

## Finance review packet

Every consequential expense review should contain:

```yaml
expense:
  vendor: string
  amount: decimal
  date: date
  description: string
proposed_allocation:
  splits: []
  remaining_balances_after_approval: []
donor_attribution:
  method: string
  affected_donation_count: integer
evidence:
  status: MISSING | PARTIAL | SUFFICIENT | CONTRADICTORY | EXPIRED | REDACTION_REQUIRED
  document_refs: []
anomalies: []
agent_recommendation: APPROVE | REJECT | REQUEST_INFORMATION
```

The recommendation is advisory. The decision is human.

## Attribution semantics

Supported initial policies:

- `DIRECT_RESTRICTED`;
- `PRO_RATA_POOL`;
- `FIFO_POOL`;
- `DONATION_COHORT`;
- `CAMPAIGN_POOL`;
- `NO_INDIVIDUAL_ATTRIBUTION`.

For pooled attribution, donor language must say that the donation **contributed to the fund** supporting the expenditure. It must not claim that specific dollars purchased a specific item.

## Receipt model

A use-of-funds receipt contains:

- attributed amount;
- total expenditure amount;
- vendor display name;
- purchase date and category;
- allocation and designation;
- attribution method and explanation;
- verification state;
- evidence-safe references;
- remaining designated balance;
- correction lineage.

An impact receipt contains:

- linked program or funded asset;
- verified occurrence date;
- outcome type;
- verified metrics;
- evidence references;
- cumulative usage where supported;
- correction lineage.

## Consent and notifications

The consent service evaluates permission at delivery time using:

- explicit channel opt-in;
- notification type;
- quiet hours;
- digest preference;
- jurisdiction and tenant policy;
- prior delivery and deduplication state.

SMS is blocked without explicit consent. Channel copy cannot change canonical receipt facts.

## Privacy Sentinel

Deterministic output gates block:

- donor names, emails, phones, addresses, or individual gifts in public exports;
- participant names without approved consent;
- raw invoices or receipts without redaction;
- internal approver identities in donor/public projections;
- provider credentials or secrets;
- cross-tenant identifiers;
- unsupported financial or causal claims.

Model-assisted review may flag ambiguous prose, but deterministic schema and policy checks make the final allow/block decision.

## Failure handling

Every workflow must support:

- idempotent replay;
- duplicate provider events;
- human approval timeouts;
- temporary provider failure;
- permanent delivery failure;
- missing or contradictory evidence;
- partial execution;
- correction after publication;
- tenant suspension;
- policy-version migration.

Blocked and dead-letter cases must remain visible to operators.

## Observability

Required telemetry:

- workflow state and age;
- blocked-case count and reason;
- proposal acceptance/rejection rate;
- evidence sufficiency rate;
- classification confidence distribution;
- approval latency;
- receipt publication latency;
- notification delivery and permanent-failure rates;
- correction frequency;
- privacy-gate blocks;
- cross-tenant access denials.

Logs must use stable identifiers and exclude raw donor PII.

## First implementation slice

Implement exactly one full path before broadening scope:

```text
fixture/accounting expense
→ evidence validation
→ allocation proposal
→ finance approval (L3)
→ ledger commit
→ donor attribution
→ use-of-funds receipt
→ email preview
→ independent send approval
→ fixture delivery receipt
```

This slice must pass money-invariant, replay, cross-tenant, correction, low-confidence, contradictory-evidence, and PII-leakage tests before live providers are introduced. Shipped paths: façade `run_expense_approval_slice` (default runtime), durable CLI (`--durable seed|list|approve|worker`), correction + scheduled digest workflows.
