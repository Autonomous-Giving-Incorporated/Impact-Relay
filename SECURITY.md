# Security and privacy boundary

Impact Relay has two surfaces:

1. **Public aggregate** publishing (Cloudflare Workers static assets / Vercel until cutover / GitHub Pages fallback / `data/`) — no donor PII.
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

## SMTP credentials and donor addresses

- Keep `IMPACT_RELAY_SMTP_PASSWORD` in the host secret manager or process environment, never in policy files, fixtures, logs, delivery receipts, or git.
- Donor email resolution is host-owned. The library receives an address only at the consent-checked delivery boundary and does not add email fields to the donor ledger or public exports.
- SMTP provider response text is not persisted. Delivery details contain only sanitized classifications and status codes.
- Production adapters never create consent. Missing or revoked consent blocks delivery before recipient resolution or network access.
- Prefer `starttls` or `ssl`. Plain SMTP (`none`) is an explicit host decision and should be limited to a protected local relay.

## Postmark credentials and delivery responses

- Keep `IMPACT_RELAY_POSTMARK_SERVER_TOKEN` in the host secret manager or process environment. It is redacted from configuration representations and must never appear in fixtures, logs, receipts, findings, or git.
- Postmark uses the same host-owned donor resolver, consent checks, enabled-preference checks, and independently approved content boundary as SMTP. Selecting Postmark never creates consent or falls back to fixture delivery.
- The endpoint must use HTTPS. Production should retain the default `https://api.postmarkapp.com/email`; endpoint overrides exist for controlled gateways and should be domain-allowlisted by the host.
- Provider response messages can contain recipient details and are never persisted. Durable delivery records retain only the Postmark `MessageID`, numeric error code classification, and sanitized status.

## Aggregate HTTP bridge credentials

- Every.org and Notion HTTP inputs are operator-configured bridges for pre-aggregated JSON documents. They are not direct donor, gift, transaction, or Notion-row APIs.
- Keep `IMPACT_RELAY_EVERY_ORG_AGGREGATE_TOKEN` and `IMPACT_RELAY_NOTION_PUBLIC_EVIDENCE_TOKEN` in the host secret manager or process environment. Never put tokens in endpoint query strings, fixtures, logs, public artifacts, or git.
- Fetchers require absolute HTTPS URLs, reject URL userinfo and fragments, require a JSON content type and object root, cap responses at 1 MiB, and sanitize network failures.
- Network acceptance does not imply data acceptance. Every fetched payload passes the same mandatory deterministic personal-data and itemization validators as a local aggregate file.
- Endpoint configuration is trusted operator input. Hosts should additionally restrict egress and allowlist bridge domains to reduce SSRF and supply-chain risk.

## Incident response

If personal data is accidentally committed:

1. Remove it in a follow-up commit immediately.
2. Rotate any exposed credentials.
3. Treat historical git history as compromised for that data class and rewrite only with explicit operator approval.

See also [docs/ops/INCIDENT-RESPONSE.md](docs/ops/INCIDENT-RESPONSE.md).
