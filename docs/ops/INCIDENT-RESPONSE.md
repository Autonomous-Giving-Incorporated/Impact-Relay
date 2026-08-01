# Incident response (money / privacy)

## Severity

| Sev | Example | Response |
|-----|---------|----------|
| S1 | Wrong money amount published; PII in public Pages | Stop publish pipeline; reverse/supersede; rotate Pages artifact |
| S2 | Cross-tenant data exposure | Disable affected tenant worker; audit command log |
| S3 | Notification spam / quiet-hour miss | Pause adapters; fix prefs |

## Immediate steps (S1/S2)

1. **Stop writes** — set `WORKFLOW_WORKER_ENABLED=0`; stop host deploy.
2. **Preserve evidence** — copy `ledger_commands.jsonl`, `workflows.db`, `storage.db`, object keys.
3. **Money path** — use L3 `reverse_expense` / `supersede_expense` via correction workflow (never silent edit).
4. **Public** — rebuild digests/public export; re-run Privacy Sentinel.
5. **Notify** — finance + privacy contacts for the tenant (Hacker Dojo ops list in pilot doc).

## Recovery

- Rehydrate from command log (K17); confirm expense ids stable.
- `python -m impact_relay --durable check --data-dir …`
- Re-save entity snapshot; re-open donor API and verify correction_history.

## Contacts (fill for production)

| Role | Contact |
|------|---------|
| Finance approver on-call | _host config_ |
| Privacy / admin | _host config_ |
