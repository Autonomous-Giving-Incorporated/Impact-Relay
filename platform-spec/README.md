# Platform specification pin

This repository **pins** the Autonomous Giving Platform Specification at:

| Field | Value |
| --- | --- |
| Repository | [Autonomous-Giving-Incorporated/Autonomous-Giving-Specs](https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Specs) |
| Version | **2.0.0** |
| Release | https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Specs/releases/tag/v2.0.0 |
| Tag | `v2.0.0` (commit `c089739`) |
| Service role | Evidence / transparency (`impact-relay`) |

Do **not** track floating `main` of the specs repository for production behavior. Consume the tagged release package or git tag `v2.0.0`. This pin is a specification cut, not a live Worker, product READY claim, or leadership sign-off.

## Manifest

[`conformance.yml`](conformance.yml) declares which SPECs, contracts, and events Impact Relay implements. Schema:

https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Specs/blob/v2.0.0/schemas/meta/conformance-manifest.schema.json

Impact Relay **owns** the ImpactNotice artifacts (SPEC-027, CONTRACT-013, EVENT-011). This repository does not yet emit those payloads. They are listed as owned/produced in the manifest and called out as not implemented in the evidence notes. Do not treat the impact loop as READY.

Suite-tracked (not implemented here): SPEC-023, SPEC-024, SPEC-026, SPEC-028. Money lock from the pin: AGI never processes donations; Stripe is tenant/SaaS billing only; P0 connector is every.org. Host lock: Cloudflare + Supabase. Cloud Run / Render are historical only.

## Relationship to existing IR conformance

`docs/platform-conformance.yml` remains the **Impact Relay product** acceptance inventory (HD-IR checks, agent contracts, privacy gates).

`platform-spec/conformance.yml` is the **cross-suite** declaration against the Autonomous Giving platform canon (SPEC-001+). Both must stay consistent when platform contracts change.

## Boundary (from platform canon)

Impact Relay collects evidence, verifies, and notifies. It **must not** silently edit lifecycle history or grant Allocation authority.

## Updating the pin

1. Review the specs release notes and migration guide.
2. Bump `platform_spec.version` in `conformance.yml`.
3. Align agent/public schemas with any contract changes in the release package.
4. Re-run `scripts/check_platform_conformance.py` and product tests.
