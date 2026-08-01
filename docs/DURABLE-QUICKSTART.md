# Durable pilot — quick start

Easy durable workflows. **Default: SQLite in a local folder — no Docker, no Postgres install.**

## One-time flow

```bash
# optional: pip install -e '.[dev]'
# 1. Seed a fixture expense and park at human approval
python -m impact_relay --durable seed

# 2. See what is waiting
python -m impact_relay --durable list

# 3. Approve (picks the first waiting workflow)
python -m impact_relay --durable approve

# 4. Confirm expense ids survive a “restart” (rehydrate from log)
python -m impact_relay --durable check

# 5. Status overview (includes completed workflows)
python -m impact_relay --durable status
```

Or after install: `impact-relay --durable seed` (same as `python -m impact_relay`).

Custom data directory:

```bash
python -m impact_relay --durable seed --data-dir ./my-pilot-data
python -m impact_relay --durable list --data-dir ./my-pilot-data
python -m impact_relay --durable approve --data-dir ./my-pilot-data --approver-id you@example.org
```

## After a crash / process restart

Use the **same** `--data-dir`. Nothing is rebuilt from scratch.

1. **Rehydrate check** — expense ids and states match the command log (K17 fold, no re-dispatch).
2. **Worker drain** — claim any `PENDING` / `RETRY_SCHEDULED` left mid-advance.
3. **List / approve** — human gates still wait for a human.

```bash
python -m impact_relay --durable status --data-dir ./my-pilot-data
python -m impact_relay --durable check --data-dir ./my-pilot-data
python -m impact_relay --durable worker --once --data-dir ./my-pilot-data
python -m impact_relay --durable list --data-dir ./my-pilot-data
```

Module entry (same behavior):

```bash
python -m impact_relay.workflows.worker --data-dir ./my-pilot-data --once
```

### Continuous worker (optional)

For a long-running claim loop (multi-process pilot):

```bash
export WORKFLOW_WORKER_ENABLED=1
python -m impact_relay --durable worker --data-dir ./my-pilot-data --poll-interval 1
# or:
python -m impact_relay.workflows.worker --data-dir ./my-pilot-data --poll-interval 1
```

Without the env flag, continuous mode refuses to start (use `--once` or `--force-worker` / `--force`).

SQL engines without a durable ledger command log are refused (K11).

## What is stored

| Path | Purpose |
|------|---------|
| `.impact-relay/durable/HOWTO.md` | Copy of these steps |
| `workflows.db` | SQLite workflow store (instances, waits, signals, receipts) |
| `ledger_commands.jsonl` | Successful money commands (K17 rehydrate — stable expense ids) |
| `meta.json` | Tenant pointer + backend |

## Optional Postgres

Same CLI. Point the store at Postgres with one env var:

```bash
# docker compose -f docker-compose.postgres.yml up -d
export IMPACT_RELAY_DATABASE_URL=postgresql://impact:impact@localhost:5432/impact_relay
pip install 'impact-relay[db]'   # or: pip install 'psycopg[binary]>=3.1'
python -m impact_relay --durable seed --data-dir ./my-pilot-data
python -m impact_relay --durable worker --once --data-dir ./my-pilot-data
```

Ledger money log still lives under `--data-dir` (`ledger_commands.jsonl`).
Workflow rows live in Postgres (`SKIP LOCKED` claim for multi-worker pilots).

## Rules (trust)

- Approvers must be humans (`agent:*` is rejected).
- Rehydrate **folds** logged results; it never re-runs mutations with new random ids.
- Expense ids stay stable across process restarts when you use the same `--data-dir`.
- Claim never returns pure `WAITING_SIGNAL`. FAILED execution receipts are never stored as skip keys.
- Worker enablement: `--once` is always safe; continuous needs `WORKFLOW_WORKER_ENABLED=1`.

## Help

```bash
python -m impact_relay --durable help
```
