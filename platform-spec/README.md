# Platform specification pin

This repository **pins** the Autonomous Giving Platform Specification at:

| Field | Value |
| --- | --- |
| Repository | [scrimshawlife-ctrl/Autonomous-Giving-Specs](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Specs) |
| Version | **1.0.0** |
| Release | https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Specs/releases/tag/v1.0.0 |
| Service role | Evidence / transparency (`impact-relay`) |

Do **not** track floating `main` of the specs repository for production behavior. Consume the tagged release package or git tag `v1.0.0`.

## Manifest

[`conformance.yml`](conformance.yml) declares which SPECs, contracts, and events Impact Relay implements. Schema:

https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Specs/blob/v1.0.0/schemas/meta/conformance-manifest.schema.json

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
