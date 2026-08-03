# Allocation middleware — Impact Relay role

**Canonical design:** [Specs design doc](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Specs/blob/main/docs/superpowers/specs/2026-08-03-allocation-middleware-design.md)  
**Suite summary:** [AGI PRODUCT-ALLOCATION-MIDDLEWARE](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/PRODUCT-ALLOCATION-MIDDLEWARE.md)

## Positioning

Impact Relay remains the **evidence / verification / transparency** boundary. In the allocation middleware product it owns **proof attachment**, **trail projections**, and discipline that impact claims require evidence—not gift ingestion or allocation approval.

## Relevance to Impact Relay

| Middleware concept | Impact Relay affinity |
| --- | --- |
| Proof linked to allocation | Evidence artifacts; public-safe projection rules |
| Trail (gift → pot → allocation → proof) | Lineage narrative for operators and funders |
| MISSING_PROOF exceptions | Operational pressure toward evidence completeness |
| Board packet (share of proven story) | Aggregate, privacy-safe outputs |

## Explicit non-overlap

- Does not become the every.org connector  
- Does not approve allocations  
- Does not require full bank transaction history  
- Public `public_aggregate_only` JSON for AGI Pages remains a separate, stricter surface  

## Implementation note

Co-locate proof modules with pots/allocations in a modular monolith when shipping middleware (Specs SPEC-002A / SPEC-020). Keep HD-IR agent contracts and `docs/platform-conformance.yml` as product-internal gates; platform pin remains Specs v1.x.
