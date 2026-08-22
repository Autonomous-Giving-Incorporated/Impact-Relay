# Operational runbooks

## Provider outage (Every.org / accounting export)

1. Keep Impact Relay offline pilot fixtures for CI.
2. Do not invent live aggregates — reduce outside the repo (Every.org runbook).
3. When feed returns, re-import via host adapter; workflows resume from WAITING_SIGNAL / PENDING.

## Email provider outage or rejection (SMTP / Postmark / Resend)

1. Stop approving new notification sends if the provider is broadly unavailable.
2. Inspect sanitized delivery status. For SMTP, transport and 4xx failures are temporary while authentication, sender/recipient rejection, and 5xx responses are permanent. For Postmark, HTTP 429/5xx and transport failures are temporary; other HTTP 4xx and nonzero API `ErrorCode` responses are permanent for that attempt. For Resend, HTTP 429/5xx and transport failures are temporary; other HTTP 4xx and named API errors (`validation_error`, and similar) are permanent for that attempt.
3. Verify credentials and sender configuration in the host secret manager. Never paste passwords or raw provider responses into findings or tickets.
4. Do not repeatedly invoke the same command: command and intent deduplication prevent duplicate sends. Preserve the failed delivery receipt.
5. Correct the host configuration or donor contact record, confirm consent and preference remain active, then use host-owned recovery tooling to create a newly versioned, independently approved notification intent. Automated redelivery is not shipped in the library yet.

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
