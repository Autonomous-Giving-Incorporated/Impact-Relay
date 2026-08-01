# Threat model (Impact Relay library)

## Trust boundaries

| Boundary | Trust |
|----------|--------|
| Host app (Hacker-Dojo / other nonprofit) | Authenticates humans (OIDC); binds `Principal`; owns UX |
| Impact Relay domain ledger | Money truth; no agent self-approve |
| Durable stores | Tenant-scoped; command log is K17 fold-only |
| Object storage | Tenant-prefixed keys; SSE when S3 |
| Public Pages exports | Privacy Sentinel fail-closed |

## Assets

- Donor PII (names, emails) — never in public aggregates
- Use-of-funds receipts and correction lineage
- Evidence objects (invoices) — donor_visible flag
- ApprovalReceipt / L3 command execution

## Adversaries & mitigations

| Threat | Mitigation |
|--------|------------|
| Agent self-approval | `agent:*` rejected; L3 requires human ApprovalReceipt |
| Cross-tenant read | tenant_id on every store; executor rejects mismatch |
| Path traversal on objects | `validate_object_ref` |
| Replay / double spend of commands | idempotency keys + receipt index (FAILED never stored) |
| Silent receipt mutation | append-only corrections; snapshot hash |
| Role escalation | Host maps OIDC → roles; library RBAC on host session |
| Quiet-hour spam | preference quiet hours → DEFERRED_QUIET_HOURS |

## Out of scope (host)

- OIDC token crypto validation (host IdP SDK)
- Network perimeter / WAF
- Physical access to Postgres/S3
