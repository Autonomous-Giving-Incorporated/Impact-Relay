# Durable pilot — quick start

File-backed durable workflows (pilot P1). **No database required.**

## One-time flow

```bash
# 1. Seed a fixture expense and park at human approval
python -m impact_relay --durable seed

# 2. See what is waiting
python -m impact_relay --durable list

# 3. Approve (picks the first waiting workflow)
python -m impact_relay --durable approve

# 4. Confirm ids survive a “restart” (rehydrate from log)
python -m impact_relay --durable check

# 5. Status overview
python -m impact_relay --durable status
```

Custom data directory:

```bash
python -m impact_relay --durable seed --data-dir ./my-pilot-data
python -m impact_relay --durable list --data-dir ./my-pilot-data
python -m impact_relay --durable approve --data-dir ./my-pilot-data --approver-id you@example.org
```

## What is stored

| Path | Purpose |
|------|---------|
| `.impact-relay/durable/HOWTO.md` | Copy of these steps |
| `ledger_commands.jsonl` | Successful money commands (rehydrate source of truth) |
| `workflow_session.pkl` | Workflow wait/signal state |
| `meta.json` | Tenant pointer |

## Rules (trust)

- Approvers must be humans (`agent:*` is rejected).
- Rehydrate **folds** logged results; it never re-runs mutations with new random ids.
- Expense ids stay stable across process restarts when you use the same `--data-dir`.

## Help

```bash
python -m impact_relay --durable help
```
