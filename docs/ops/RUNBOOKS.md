# Operational runbooks

## Provider outage (Every.org / accounting export)

1. Keep Impact Relay offline pilot fixtures for CI.
2. Do not invent live aggregates — reduce outside the repo (Every.org runbook).
3. When feed returns, re-import via host adapter; workflows resume from WAITING_SIGNAL / PENDING.

## Replay after crash

```bash
python -m impact_relay --durable status --data-dir ./data
python -m impact_relay --durable check --data-dir ./data
python -m impact_relay --durable worker --once --data-dir ./data
```

Or host session: `session.check_rehydrate()` / `session.worker_once()`.

## Backup & restore (pilot)

**Backup**

- `data-dir/ledger_commands.jsonl`
- `data-dir/workflows.db`
- `data-dir/storage.db`
- object store prefix / `objects/` tree
- policy files under `policies/tenants/`

**Restore**

1. Restore files to data-dir.
2. Open workspace; run `durable check`.
3. Compare entity snapshot expense ids to pre-backup list.

**Automated test:** `tests/test_durable_ledger_log.py` (rehydrate) + `tests/test_storage_ledger_repo.py` (snapshot).

## Retention

- Command log: retain for audit period (tenant policy; default indefinite in pilot).
- Object evidence: retain while expense not terminal + policy years.
- Public digests: no PII; retain for transparency site history.

## Unsubscribe / opt-out

```python
api.set_notification_preference(donor_id, channel="EMAIL", enabled=False)
# or grant=False via NotificationService.record_consent
```
