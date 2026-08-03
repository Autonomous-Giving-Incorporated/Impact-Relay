# Security and privacy boundary

Impact Relay has two surfaces:

1. **Public aggregate** publishing (GitHub Pages / `data/`) — no donor PII.
2. **Library + pilot data-dir** (local/staging durable store, host consoles) — may hold synthetic or authorized operational records **outside git**.

Ops detail: [docs/ops/](docs/ops/) (threat model, incident response, security checklist).

## Must never appear in this repository

- donor or member names
- email addresses, phone numbers, street addresses
- itemized donation amounts tied to a person
- private stewardship notes
- CRM exports, workbooks, PDFs of registries
- service-role keys, API secrets, private tokens
- populated `.impact-relay/` pilot databases with real people

## Allowed content

- aggregate raised / committed totals
- public donor counts
- milestone labels and impact statements
- operational notifications without personal data
- public donation processor links
- synthetic fixture identities used only in tests and local pilots

## Host and console notes

- Host apps (e.g. Hacker Dojo) own live IdP JWT validation; this library ships RBAC ports and a fixture/header bridge for pilot.
- Separation of duties: proposers cannot self-approve; agent principals are rejected for L3 money paths.
- Production notification credentials and SMS activation remain operator-gated.

## Local operator session files

Local `--workflow-ops` sessions use a versioned JSON format with an explicit class allowlist and a corruption-detection checksum. The checksum is not a signature and does not authenticate the file. Legacy Python pickle sessions are rejected because deserializing an attacker-controlled pickle can execute code. Treat session files as sensitive operational state, and use the durable SQLite/Postgres workflow path for production or restart-sensitive deployments.

## Incident response

If personal data is accidentally committed:

1. Remove it in a follow-up commit immediately.
2. Rotate any exposed credentials.
3. Treat historical git history as compromised for that data class and rewrite only with explicit operator approval.

See also [docs/ops/INCIDENT-RESPONSE.md](docs/ops/INCIDENT-RESPONSE.md).
