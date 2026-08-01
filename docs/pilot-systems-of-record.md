# HD-IR-001 pilot systems of record (fixture assumptions)

This pilot does **not** connect to live payment, CRM, or accounting products.

| Concern | Pilot assumption |
|--------|-------------------|
| Payment / donations | `fixture://payments/stripe-export-v1` — normalized donation rows in `fixtures/pilot_hd_ir_001.json` |
| Accounting / expenses | `fixture://accounting/quickbooks-export-v1` — normalized expense + invoice summary |
| CRM / donors | `fixture://crm/manual-roster-v1` — donor ids and display names only |
| Attribution policy | `DIRECT_RESTRICTED` for the single-donor publish step in the default fixture; `PRO_RATA_POOL` covered in tests |
| Policy version | Organization `policy_version` (default `v1.0`) stamped on receipts and audit |

Accounting remains authoritative for real operations; Impact Relay mirrors approved financial facts only.
