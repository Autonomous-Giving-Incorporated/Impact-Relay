# Allocation middleware — Impact Relay role

**Status:** MVP host is Portfolio Signals · Impact Relay owns proof/trail discipline long-term  
**Canonical design:** [Specs design doc](https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Specs/blob/v2.0.0/docs/superpowers/specs/2026-08-03-allocation-middleware-design.md)  
**Suite summary:** [AGI PRODUCT-ALLOCATION-MIDDLEWARE](https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Incorporated/blob/main/docs/PRODUCT-ALLOCATION-MIDDLEWARE.md)

## Positioning

Impact Relay remains the **evidence / verification / transparency** boundary. In the allocation middleware product it owns **proof attachment**, **trail projections**, and discipline that impact claims require evidence—not gift ingestion or allocation approval.

The first modular-monolith MVP co-locates a lightweight proof/packet path inside [Portfolio Signals `services/allocation-middleware/`](https://github.com/Autonomous-Giving-Incorporated/Portfolio-Signals/tree/main/services/allocation-middleware) so directors can complete an allocate→proof loop without standing up a second deployable. Deeper ledger, use-of-funds receipts, and public-safe projections remain this repository’s product surface.

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

- **Today:** MVP proof endpoints and packet UI ship with the Portfolio Signals middleware package (Specs SPEC-002A / SPEC-020 Profile B).  
- **Next for this repo:** optional binding of middleware allocation IDs to IR ledger / UOF receipts when a client needs full donor-chain evidence; keep HD-IR agent contracts and `docs/platform-conformance.yml` as product-internal gates; platform pin is Specs v2.0.0. ImpactNotice (SPEC-027 / CONTRACT-013 / EVENT-011) is owned here and not yet emitted.

## Cross-links

| Resource | URL |
| --- | --- |
| Portfolio Signals middleware status | https://github.com/Autonomous-Giving-Incorporated/Portfolio-Signals/blob/main/docs/ALLOCATION-MIDDLEWARE.md |
| Hacker Dojo pilot | https://github.com/Autonomous-Giving-Incorporated/Portfolio-Signals/blob/main/docs/HACKER-DOJO-ALLOCATION-PILOT.md |
| Specs design | https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Specs/blob/v2.0.0/docs/superpowers/specs/2026-08-03-allocation-middleware-design.md |
