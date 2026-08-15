# AGI Phase C — Impact Relay contract governance

This is the Impact Relay half of AGI Phase C (field owners, `allocationId` /
status vocabulary, representative public-safe fixtures). It does **not**
approve evidence-access policy, invent a READY state, or freeze a SHA.

Canonical AGI references:

- [INTEGRATION_CONTRACTS.md](https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Incorporated/blob/main/docs/INTEGRATION_CONTRACTS.md)
- [CONTRACT_GOVERNANCE.md](https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Incorporated/blob/main/docs/CONTRACT_GOVERNANCE.md)
- [THREE_REPO_INTEGRATION.md](https://github.com/Autonomous-Giving-Incorporated/Autonomous-Giving-Incorporated/blob/main/docs/THREE_REPO_INTEGRATION.md)
- Contract version: `2026-08-02` (`integration/contracts.ts`)

Related in this repo: [public-impact schema](../schemas/public-impact.schema.json),
[public_impact.py](../src/impact_relay/public_impact.py),
[HD-IR-006](HD-IR-006.md).

---

## Phase C note

| Item | Status |
| --- | --- |
| Representative public-safe fixtures | Published under `fixtures/agi_phase_c/` |
| `allocationId` + status vocabulary | Aligned below; live `VERIFIED` meaning unchanged |
| ImpactEvent field ownership | Recorded as **roles** (see C1) |
| Evidence-access, retention, redaction, and public-publication rules | **PROPOSED** — remains unsigned until leadership + eng sign-off |
| Phase C exit (reviewed schemas, approved public-data rules, named owners confirmed) | **Not complete** |

Do not treat this document as leadership approval.

---

## C1 — ImpactEvent field ownership (roles)

Owners are **roles**, not invented people. The current operator login
`scrimshawlife-ctrl` is recorded only as a human filler for the Impact Relay
owner role. No other individuals are named.

| Field (AGI `ImpactEvent`) | IR public-impact counterpart | Role owner | Notes |
| --- | --- | --- | --- |
| `schemaVersion` | document `version` + this contract date | AGI contract steward | Date string `2026-08-02`; bump on breaking change |
| `allocationId` | `outcomes[].allocationId` | Fund-Intel issues at decision publish; **Impact Relay owner** stores and exports the same value | Suite join key only. Never a donor id. |
| `eventId` | `outcomes[].impactEventId` | **Impact Relay owner** | Stable public event identity |
| `type` | `outcomes[].eventType` | **Impact Relay owner** | Domain taxonomy; map to AGI types below. Do not silently coerce unmapped types. |
| `occurredAt` | `outcomes[].eventDate` | **Impact Relay owner** | Date-only on the public aggregate; ISO-8601 on the narrative contract |
| `verificationStatus` | `outcomes[].evidenceState` | **Impact Relay owner** | Normalized for AGI; live meaning of `VERIFIED` is frozen (see C2) |
| `evidenceReference` | public-safe pointer only (optional) | **Impact Relay owner** | Never a raw receipt, personal data, or secret URL |

Public-impact envelope fields (`authority`, `privacy`, `summary`) remain owned
by the **Impact Relay owner**. They are not ImpactEvent fields.

Human filler for the Impact Relay owner role: `scrimshawlife-ctrl`.

---

## C2 — `allocationId` and status vocabulary

### `allocationId`

| Rule | Value |
| --- | --- |
| Pattern | `^alloc_[a-z0-9_]+$` (AGI `validate-public.ts` + this repo’s public-impact schema) |
| Representative example | `alloc_community_hardware` |
| Issuer | Fund-Intel / Portfolio Signals at decision publish |
| Consumer | Impact Relay public outcome export; AGI joins only on this value |
| Not | donor id, donation id, operator identity, or a secret |

Existing ledger allocation ids in this repo already use this shape
(`alloc_community_hardware`, `alloc_other_tools`). Do not invent a second
public identifier.

AGI’s earlier draft suggested `alloc_<slug>_<nnn>`. The **implemented**
suite vocabulary (AGI fixtures + validator, Portfolio Signals campaign
allocations, this repo’s ledger) is `alloc_[a-z0-9_]+` without a mandatory
sequence suffix. A suffix is allowed when Fund-Intel issues one; Impact Relay
must echo it unchanged.

### Verification status (do not change live `VERIFIED` semantics)

`VERIFIED` on an Impact Relay impact event means a human program verifier
approved that the activity occurred and is sufficiently evidenced. It is a
**source-system state**. It is not individual donor attribution, not
`OBSERVED` raised-claim provenance, and not a live-cohort declaration.

| Impact Relay domain `ImpactEventState` | Public `evidenceState` | AGI `verificationStatus` | Public export? |
| --- | --- | --- | --- |
| `DRAFT` | — | — | No |
| `SUBMITTED` | — | `pending` (internal / narrative only) | No |
| `VERIFIED` | `VERIFIED` | `verified` | Yes, after human verify |
| `REJECTED` | — | `rejected` | No |

Public Pages / AGI live projection still require at least one
`evidenceState: "VERIFIED"` outcome. The committed `data/public-impact.json`
shell stays empty until an authorized live path exists. Fixture `VERIFIED`
rows in `fixtures/agi_phase_c/` are contract examples, not a live cohort.

`OBSERVED` remains a raised-claim label for authorized processor aggregates
only. Fixture and synthetic data must never be labeled `OBSERVED`.

### Allocation / decision status (Portfolio Signals + AGI)

These are **decision-workspace** statuses. Impact Relay does not redefine them
and does not treat them as impact verification.

| Status | System | Meaning |
| --- | --- | --- |
| `proposed` | Portfolio Signals / AGI campaign allocation | Advisory; not spend authority |
| `approved` | AGI `FundingDecision.status` (only modeled value) | Published decision text |
| `active` | Portfolio Signals allocation | In-period |
| `closed` | Portfolio Signals allocation | Closed |
| `blocked` \| `review` \| `authorized` \| `active` \| `sealed` | Portfolio Signals `execution.state` | Campaign execution. Invented states such as READY or freeze are rejected by AGI. |

### Event type map (initial)

Unmapped domain types must not be silently coerced into an AGI type.

| Impact Relay domain / public `eventType` | AGI `ImpactEventType` |
| --- | --- |
| expense / purchase approval (ledger, not public impact) | `purchase_approved` |
| receipt attached (ledger / UOF) | `receipt_attached` |
| equipment / funded-asset delivery | `equipment_delivered` |
| `CLASS_HELD` / program occurrence | `program_held` |
| attendance verified | `attendance_verified` |
| notification delivered | `notification_delivered` |

---

## C3 — Evidence-access policy (PROPOSED)

Restatement of the public-data rules already enforced on this repo’s public
aggregates. **Not approved.** Leadership + eng sign-off is still required
before this is treated as suite policy.

1. Join only by `allocationId`. Never by donor identity.
2. Accept only `authority: "public_aggregate_only"` on this surface.
3. Evidence references are public-safe identifiers only.
4. `verified` / `VERIFIED` is a source-system state, not one-to-one attribution.
5. Do not infer evidence from missing, delayed, malformed, or rejected records.
6. Public exports stay free of PII, contact data, individual gift amounts, and private notes.
7. Retention and redaction of private ledger/evidence records stay with Impact Relay; public projections inherit only what this repo publishes.

---

## C4 — Representative fixtures

| File | Contract | Live claim? |
| --- | --- | --- |
| `fixtures/agi_phase_c/public_impact.json` | Impact Relay `public-impact.schema.json` + AGI `validatePublicImpact` shape | No — `source` is `fixture:agi_phase_c` |
| `fixtures/agi_phase_c/impact_events.json` | AGI `ImpactEvent` (`2026-08-02`) | No — narrative contract examples |
| `data/public-impact.json` | Same public-impact schema (empty outcomes) | No live `VERIFIED` cohort |

Shared narrative example: Community Hardware / `alloc_community_hardware`,
matching AGI `communityHardwareFixture` and `validPublicImpact`.

---

## C5 — Versioning (this repo)

1. Public-impact document `version` stays semver (`1.0.0` today).
2. Narrative contract version is AGI’s date string `2026-08-02`.
3. Breaking public-shape or vocabulary changes need a version bump and
   coordinated notes in AGI and Portfolio Signals.
4. Additive optional public-safe fields may ship under the same version if
   consumers ignore unknowns.
5. Runtime write APIs are out of scope for Phase C.

---

## Hosting (not Render)

Designed stack: **Cloudflare Workers + Supabase**. The public tracker is an
assets-only Worker; operator auth/tenancy stay on platform Supabase. See
[CLOUDFLARE.md](CLOUDFLARE.md) and [PLATFORM.md](PLATFORM.md).

An earlier AGI-001 note recommended Cloud Run for hosted APIs. That
recommendation is **historical**. Render is not the host. Workers config
already landed (`wrangler.toml`); this Phase C work does not add Wrangler.

---

Last updated: 2026-08-15
