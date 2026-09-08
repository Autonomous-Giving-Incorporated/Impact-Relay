# Schema mapping — AutoGive Synthetic Dataset v1 (Impact Relay)

Portfolio Signals owns the NATIVE gift/donor/role universe under
`fixtures/autogive-v1/`. This repo owns the BRIDGE ledger, evidence, and
public-impact projection. Classification is `SYNTHETIC_ONLY`. Never label
these rows `OBSERVED`.

```yaml
dataset: autogive-synthetic-dataset
version: 1.0.0
seed: 20260821
classification: SYNTHETIC_ONLY
tenant_id: org_synthetic_civic_forge
campaign_id: cmp_synthetic_builder_fund_2026
```

Hacker Dojo (`org_hacker_dojo`) remains the reference tenant. Civic Forge sits
beside it. Live `data/public-impact.json` stays the gated empty shell.

| Dataset / PS bridge entity | Classification | Impact Relay target | Transform | Authority |
|---|---|---|---|---|
| tenant `org_synthetic_civic_forge` | BRIDGE | `Organization.id` | Same string. Policy falls back to built-in defaults (`default_policy`) until a signed Civic Forge pack exists. | Not HD |
| 3 compact donors | BRIDGE | `Donor` | `donor_syn_*` display names only. No emails. | No outreach |
| compact donations | BRIDGE | `Donation` + `DonationAllocation` | Hardware 90910 + scholarships 67880 only. Undesignated 125200 stays NATIVE in PS. | Cleared only |
| public allocation IDs | BRIDGE | `Allocation.id` | Stable suite IDs below. | Suite join |
| `alloc_community_programs` | BRIDGE (negative) | registered, not published | Agent proposal. `exp_syn_006` is allocated to `APPROVAL_PENDING` and is not approved. | Human gate |
| expenses 001–003 | BRIDGE | `Expense` + evidence + UOF publish | Happy path. Evidence kinds mapped to `invoice` when the source pack used `approval_packet`. | Human approve in `run_pilot` |
| expenses 004–005 | BRIDGE | `Expense` on `alloc_facility_resilience` | Recorded. Approval must fail: pot has no cleared gifts. | Money honesty |
| expense 006 | BRIDGE | `Expense` on `alloc_community_programs` | Estimate evidence only. Not in `publish`. | Agent cannot approve |
| expense 007 | BRIDGE | `edge.duplicate_invoice` | Same `external_source_id` / digest as 001. Executor skip. Not a second ledger row. | Quarantine |
| expense 008 | BRIDGE | `Expense` with empty evidence | `EvidenceValidatorAgent` → `MISSING` | Block |
| programs 001–003 | BRIDGE | `Program` (fixture metadata) | Compact ledger does not auto-run all-phases notify. | — |
| outcomes 001–004 | PUBLIC_ONLY | `fixtures/synthetic_v1/public_impact.json` | `evidenceState=VERIFIED`, claim `PILOT`. | Not OBSERVED |
| outcome 005 | BRIDGE (negative) | `edge.unverified_outcome` | `NOT_COMPUTABLE` / `proposed`. Not a public outcome. | Unverified stays unpublished |
| PS `bridge/impact-relay-public-impact.json` | PS impact-state shape | not this file | Raised/committed live on the PS impact-state fixture. This file is IR `public-impact` outcomes. | Do not overwrite `data/` |

## Public allocation IDs (stable)

```text
alloc_community_hardware
alloc_access_scholarships
alloc_facility_resilience
alloc_community_programs
```

## Money honesty (do not falsify)

| Measure | Value | Where |
|---|---:|---|
| PS gift records | 438 | Portfolio Signals `private/gifts.json` |
| Gift amount sum (all statuses) | 286450 | includes 2 pending + 2 refunded |
| Cleared amount | 283990 | PS pots / middleware |
| Compact IR inflows | 158790 | 90910 hardware + 67880 scholarships |
| Happy-path published spend | 55550 | 18750 + 24300 + 12500 |
| Facility / programs cleared gifts | 0 | allocation registered; do not debit a pot |

## Edge-case ownership

| Case | Owner | IR behavior |
|---|---|---|
| `edge_003` | BRIDGE_ONLY | Missing evidence → `EvidenceSufficiency.MISSING` |
| `edge_004` | BRIDGE_ONLY | Duplicate `external_source_id` → executor skip |
| `edge_009` | BRIDGE_ONLY | `reverse_expense` publishes a correction; prior receipt hash unchanged |
| `edge_010` | BRIDGE_ONLY | `out_syn_005` stays `NOT_COMPUTABLE`; IMPACT publish requires `VERIFIED` |

NATIVE edges (duplicate gift, pot overallocation, suppressed contact, stale aggregate, public PII, agent allocation approval) stay in Portfolio Signals.
