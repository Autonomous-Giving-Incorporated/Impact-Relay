# Pilot systems of record (fixture assumptions)

These pilots do **not** connect to live payment, CRM, accounting, or notification products.

| Concern | Pilot assumption |
|--------|-------------------|
| Payment / donations | `fixture://payments/stripe-export-v1` — normalized rows in `fixtures/pilot_hd_ir_001.json` and `pilot_all_phases.json` |
| Accounting / expenses | `fixture://accounting/quickbooks-export-v1` — normalized expense + invoice summary |
| CRM / donors | `fixture://crm/manual-roster-v1` — donor ids and display names only |
| Programs / classes | `fixture://programs/calendar-export-v1` — impact events in all-phases fixture |
| Notifications | `fixture://notify/in-process-adapters` — no live APNs/FCM/Twilio/email |
| Attribution policy | `DIRECT_RESTRICTED` in default fixtures; `PRO_RATA_POOL` covered in tests |
| Policy version | Organization `policy_version` (default `v1.0`) stamped on receipts and audit |
| Multi-tenant | Second org `org_other_makerspace` in all-phases fixture for isolation checks only |

Accounting remains authoritative for real operations; Impact Relay mirrors approved financial facts only.

## Entry paths

- HD-IR-001: `python -m impact_relay`
- Phases 2–6 multi-stage: `python -m impact_relay --all-phases`
