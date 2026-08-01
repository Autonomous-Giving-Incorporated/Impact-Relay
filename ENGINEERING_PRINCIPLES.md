# Engineering Principles

## Financial truth

1. Financial state is append-only after approval.
2. Corrections reverse or supersede; they never erase history.
3. Donation allocations cannot exceed cleared funds.
4. Expense allocations must equal the approved expense amount.
5. Restricted fund balances cannot become negative.
6. Attribution is explicit, versioned, and reproducible.
7. Synthetic or fixture data is never presented as observed fact.

## Agent governance

1. AI proposes; it does not authorize consequential action.
2. Deterministic rules outrank model output.
3. Every inference carries evidence, confidence, and a policy version.
4. Low-confidence or contradictory cases stop and route to review.
5. Proposal, approval, execution, publication, and delivery are separate boundaries.
6. Every run emits a provenance receipt.

## Donor communication

1. Donors are shown what funds were used for.
2. Use-of-funds receipts and impact receipts are separate but linked.
3. Direct attribution is claimed only when directly supported.
4. Pooled attribution language must describe contribution to a fund, not ownership of specific dollars.
5. Published facts are canonical; channel copy cannot change them.
6. Corrections are visible and communicated to affected donors.

## Privacy and tenancy

1. Public exports contain no donor PII or individual gift records.
2. Tenant identity is mandatory on every private record and command.
3. Cross-tenant reads and writes fail closed.
4. Evidence is redacted before donor or public presentation.
5. Secrets, access tokens, and raw provider payloads do not enter logs.
6. Consent and communication preferences are enforced at delivery time.

## Architecture

1. Begin as a modular monolith.
2. Keep the deterministic domain independent from provider SDKs and model vendors.
3. Use durable state machines for long-running workflows.
4. Prefer idempotent commands and replayable events.
5. External systems enter through adapters and normalized contracts.
6. Public projections are generated from verified private state, never maintained manually as a competing ledger.

## Testing

1. Money invariants are regression gates.
2. Every workflow is tested for replay, duplicate input, partial failure, and correction.
3. Agent tests include low-confidence, contradictory, adversarial, and privacy-leakage cases.
4. Public artifacts are regenerated in CI and checked for drift.
5. No production provider is activated without sandbox and failure-path validation.