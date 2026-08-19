# Impact Relay Agent Contract

> **Scope note:** this document is the runtime governance contract for the AI agents *inside* Impact Relay (authority levels, human gates, proposal contracts). It is **not** contributor instructions for coding agents or humans working on this repository — see `CLAUDE.md` for that.

Impact Relay uses bounded agents to collect evidence, propose classifications, prepare receipts, and route human decisions. Agents do not own financial truth.

## Prime directive

> AI proposes. Deterministic services validate. Authorized humans approve. The ledger records. Receipts preserve lineage.

## Authority levels

| Level | Capability | Examples |
|---|---|---|
| L0 — Observe | Read and analyze | anomaly detection, evidence inspection |
| L1 — Propose | Produce bounded recommendations | allocation proposal, receipt draft |
| L2 — Reversible execution | Perform idempotent low-risk actions | import a provider batch, create a review task |
| L3 — Human approval required | Commit consequential actions | approve expense, publish receipt, send notification |

No agent may grant itself a higher authority level.

## Hard human gates

Human approval is required before:

- approving or reconciling an expense;
- changing an allocation split;
- selecting or changing an attribution policy;
- publishing a donor-facing use-of-funds or impact receipt;
- sending an outbound donor notification;
- correcting a published amount or outcome;
- publishing new public evidence;
- activating SMS delivery;
- changing policies or prompts that affect financial claims.

## Agent topology

1. **Orchestrator** — advances durable workflows and routes work.
2. **Donation Intake** — normalizes and deduplicates provider donations.
3. **Expense Intake** — normalizes expenses and attaches evidence.
4. **Allocation Classifier** — proposes fund splits with evidence and confidence.
5. **Evidence Validator** — evaluates completeness, contradictions, and redaction needs.
6. **Finance Review** — assembles decision packets for authorized operators.
7. **Attribution** — proposes direct or pooled donor-to-expense attribution.
8. **Use-of-Funds Receipt** — renders approved ledger facts for donors.
9. **Asset and Program Linkage** — connects expenditures to funded assets and programs.
10. **Impact Verification** — verifies that an activity occurred and is sufficiently evidenced.
11. **Impact Receipt** — explains what an approved expenditure enabled.
12. **Consent and Preference** — determines allowed channels, cadence, and quiet-hour behavior.
13. **Notification Composer** — creates channel-specific projections of canonical receipts.
14. **Delivery** — invokes approved provider adapters with idempotency and retries.
15. **Correction and Retraction** — creates append-only reversal and supersession workflows.
16. **Privacy Sentinel** — blocks prohibited PII, secrets, cross-tenant data, and unsupported claims.
17. **Audit and Provenance** — records run, proposal, approval, execution, and delivery receipts.

## Standard agent contract

Every agent must expose a pure evaluation boundary:

```python
class Agent:
    name: str
    version: str
    authority_level: AuthorityLevel

    def evaluate(self, context: AgentContext, command: AgentCommand) -> AgentProposal: ...

    def validate(self, context: AgentContext, proposal: AgentProposal) -> ValidationResult: ...
```

Execution is separate:

```python
class CommandExecutor:
    def execute(
        self,
        command: AgentCommand,
        *,
        approval: ApprovalReceipt | None = None,
        agent_name: str | None = None,
        proposal: AgentProposal | None = None,
    ) -> ExecutionReceipt: ...
```

The executor takes the **command**, not the proposal: a proposal is a
recommendation, and only a command carrying an `ApprovalReceipt` may reach the
ledger. L3 commands without a valid approval are rejected by
`impact_relay.agents.authority`.

An agent cannot propose and approve the same action.

## Required proposal fields

Every proposal includes:

- `tenant_id`;
- agent name and version;
- policy and prompt versions;
- input references and hashes;
- proposed commands;
- evidence references;
- confidence where inference is used;
- warnings and contradictions;
- required authority level;
- expiration time;
- deterministic idempotency key.

## Confidence behavior

| Confidence | Required behavior |
|---:|---|
| `>= 0.95` | Recommend; approval is still required for consequential actions |
| `0.75–0.94` | Recommend with uncertainty highlighted |
| `< 0.75` | Block automated progression and create a review task |
| Contradictory evidence | Block and escalate |

Confidence never overrides a money invariant, policy gate, or human approval requirement.

## Financial prohibitions

Agents must never:

- allocate more than the cleared donation amount;
- approve spending beyond a restricted fund balance;
- claim direct attribution without a valid method and evidence;
- mutate a published receipt;
- silently remove a correction or reversal;
- generate an impact event from a scheduled event alone;
- convert fixture or synthetic data into an `OBSERVED` public claim;
- place donor PII in public exports or logs.

## Communication rule

The canonical receipt owns the facts. Channel copy is a projection of that receipt.

A language model may improve readability but may not introduce or modify:

- amounts;
- vendors;
- dates;
- attribution methods;
- attendance;
- outcome metrics;
- causal claims;
- verification state.

## Workflow states

Logical expense-to-receipt progression (agent / domain view):

```text
RECEIVED
→ NORMALIZED
→ EVIDENCE_PENDING
→ CLASSIFICATION_PENDING
→ REVIEW_PENDING
→ APPROVED
→ LEDGER_COMMITTED
→ RECEIPT_DRAFTED
→ PUBLICATION_PENDING
→ PUBLISHED
→ NOTIFICATION_PENDING
→ DELIVERED
```

Evidence is gathered before classification: a classifier must not propose an
allocation split for an expense whose evidence is missing or contradictory.

Exception states (the complete `WorkflowState` exception set):

```text
BLOCKED
REJECTED
DUPLICATE
NEEDS_INFORMATION
```

`SUPERSEDED` and `REVERSED` are **expense** states (`ExpenseState`), not
workflow states — a correction supersedes the expense while its workflow
completes normally. Delivery failure is carried on the notification intent, not
as a workflow state.

Durable runtime uses a parallel `WorkflowState` / `RunStatus` model (wait signals, retries, dead-letter) so human gates and worker restarts are safe. See [docs/architecture/DURABLE-WORKFLOWS.md](docs/architecture/DURABLE-WORKFLOWS.md) and [docs/DURABLE-QUICKSTART.md](docs/DURABLE-QUICKSTART.md). Agents still do not own financial truth: only approved commands reach the ledger.

## Agent run receipt

Every run emits an immutable receipt containing:

```yaml
run_id: string
tenant_id: string
workflow: string
agent: string
agent_version: string
policy_version: string
prompt_version: string | null
input_refs: []
input_hash: string
proposed_actions: []
accepted_actions: []
rejected_actions: []
human_approvals: []
output_refs: []
output_hash: string
started_at: datetime
completed_at: datetime
status: SUCCEEDED | FAILED | PARTIAL | BLOCKED
```

## Testing requirements

Each agent requires:

- contract tests;
- deterministic fixture tests;
- malformed-input tests;
- low-confidence and contradictory-evidence tests;
- cross-tenant isolation tests;
- idempotency and replay tests;
- prompt/policy snapshot tests when applicable;
- adversarial claim and PII leakage tests.

## Change control

Changes to this file, financial policies, attribution rules, evidence thresholds, receipt schemas, or notification gates require review by a maintainer who is not the author of the change.

## Cursor Cloud specific instructions

> Non-obvious dev-environment notes for Cloud Agents. Standard build/verify commands live in `CLAUDE.md` (`pip install -e ".[dev]"`, `pytest`, `ruff check`, `ruff format`, `mypy`) — follow those; the update script already runs `pip install -e ".[dev]"` and `npm ci` on startup.

- **Interpreter:** only `python3` exists (no bare `python`). Console scripts (`impact-relay`, `pytest`, `ruff`, `mypy`) install to `~/.local/bin`, which is not on `PATH`; invoke tools as modules (`python3 -m pytest`, `python3 -m ruff check .`, `python3 -m mypy`, `python3 -m impact_relay ...`).
- **Base package is stdlib-only.** The optional `[db]`/`[s3]`/`[oidc]` extras are only needed for the Postgres store suite (`tests/test_workflow_sql_store.py` against a live Postgres via `IMPACT_RELAY_DATABASE_URL`) and boto3/JWKS paths; the default `pytest` run passes without them (one Postgres SKIP-LOCKED test is skipped when no DB is present).
- **Core library E2E (hello-world):** `python3 -m impact_relay --expense-approval-slice` runs fixture expense → allocation → human approval → ledger commit → use-of-funds receipt. `--all-phases` and `--durable {seed,list,approve,check,status,worker --once}` exercise the rest.
- **Console HTTP API:** seed first (`python3 -m impact_relay --durable seed --data-dir .impact-relay/hacker-dojo`), then `python3 -m impact_relay.console_server --data-dir .impact-relay/hacker-dojo --port 8787 --allow-unauthenticated-pilot`. Auth is default-deny; `--allow-unauthenticated-pilot` is for local demos only (never shadow/live cohorts). `/api/health` is unauthenticated; `/api/finance/queue` and `POST /api/finance/cases/{workflow_id}/approve` drive the review→approve gate.
- **Static public tracker UI:** `index.html` uses `<base href="/impact-relay/">`, so serving the repo root directly 404s CSS/JS/data. Run `./scripts/stage_cloudflare_assets.sh`, then `python3 -m http.server 4174` from `.cloudflare-assets/` and open `http://127.0.0.1:4174/impact-relay/index.html`.
- **Browser acceptance tests** (`npm run test:browser`) need the Playwright Chromium binary; install once per fresh machine with `npx playwright install --with-deps chromium` (kept out of the startup script because it is a heavy/brittle network download).
- **Public `data/*.json` are intentionally a zeroed, schema-valid public shell** (aggregates are empty until authorized OBSERVED data is applied). CI diffs these against regenerated exports, so do not run `python3 -m impact_relay --publish-pages` casually — it rewrites `updatedAt` and fails the stability gate.