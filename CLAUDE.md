# Working in this repository

Contributor guide for humans and autonomous coding agents. (`AGENTS.md` is a different thing here: the runtime governance contract for the AI agents *inside* the product — read it to understand the domain, not for build instructions.)

## What this is

Impact Relay is donor-impact transparency middleware: donation → approved allocation → expenditure → verified outcome, surfaced to donors as use-of-funds and impact receipts with append-only corrections. Prime directive everywhere: **AI proposes, deterministic services validate, authorized humans approve, the ledger records.**

The work queue is `ROADMAP.md` — start with **v0.9.1 (Hardening and Fidelity)**, Track A first. Items marked *(ops)* or *(human)* require credentials, live data, or human sign-off: do not attempt them.

## Setup and verification

```bash
pip install -e ".[dev]"        # or: uv run --with pytest pytest
pytest                          # ~227 tests, offline, sub-second — must stay that way
```

- Python ≥ 3.11. The base package has **zero runtime dependencies** (stdlib only) — this is deliberate. Never add a runtime dependency; new integrations (boto3, PyJWT, HTTP clients) go behind optional extras with fixture-backed test paths.
- Postgres and S3 tests are optional/env-gated and skip cleanly; don't make the default suite require a network or a service.

## CI contract (`.github/workflows/validate-and-deploy.yml`)

CI will fail your change if you don't know these rules:

1. **Public artifact drift**: CI regenerates the public Pages exports and diffs them against the committed `data/*.json`. If you touch export logic, regenerate with `python -m impact_relay --publish-pages` and commit the results.
2. **PII residue**: CI greps public artifacts for donor PII and enforces privacy flags. The Privacy Sentinel (`src/impact_relay/agents/privacy.py`) is deterministic and fail-closed — never weaken it.
3. **Banned formats**: no `.csv` / `.xlsx` / member-registry files anywhere in the tree.
4. **Schema validation**: `schemas/*.json` are validated (ajv) against the committed artifacts.

## Hard guardrails

- Never label fixture or synthetic data `OBSERVED` — provenance labels (`pilot_synthetic`, etc.) are load-bearing for public trust.
- Only `src/impact_relay/agents/executor.py` may import ledger mutation APIs — enforced by `tests/test_agent_import_boundaries.py`.
- Money invariants in the ledger tests are regression gates; never special-case Hacker Dojo in product code.
- Never commit `.impact-relay/` directories, credentials, or PII (see `SECURITY.md`).
- No agent-authored change may relax an L3 human gate (expense approval, receipt publication, notification send, corrections).

## Change control

Changes to `AGENTS.md`, `policies/`, `schemas/`, or attribution/evidence/notification gating logic require **independent human review** — propose via PR, never self-merge those. Everything else: branch → PR → green CI.

## Out of scope (sibling repo)

Host UI screens (`finance-impact.html`, `donor-impact.html`, `workspace/impact-relay-bridge.js`), shadow/live-cohort ops runbooks, real Supabase JWT/MFA validation, and production notification credentials live in `scrimshawlife-ctrl/Hacker-Dojo`. This repo ships the library, console APIs, ports, fixtures, and CI oracles. Files referenced in docs but absent here are usually in that repo, not missing.
