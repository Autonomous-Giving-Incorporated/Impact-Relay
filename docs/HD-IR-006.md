# HD-IR-006 — Public IMPACT outcomes + raised provenance

## Objective

1. Publish **program impact outcomes** from domain IMPACT receipts without donor identity.
2. Label campaign raised totals with **provenance** (pilot vs processor vs unavailable).
3. Document Every.org aggregate reduction for operators.

## Public IMPACT outcomes

```text
TenantWorkspace.impact_receipts
  → collapse by impact_event_id (no per-donor rows)
  → data/public-impact.json
  → Pages “Impact outcomes” section
```

Stripped: `donor_id`, `donation_id`, operator provenance.

## Raised provenance

`impact-state.campaign` may include:

| Field | Values |
|---|---|
| `raisedSource` | `pilot_synthetic` \| `processor_aggregate` \| `not_available` |
| `raisedClaimLabel` | `PILOT` \| `OBSERVED` \| `NOT_COMPUTABLE` |

Notion public evidence still reports live raised as **NOT_COMPUTABLE** until a real aggregate export is authorized.

## Commands

```bash
python -m impact_relay --publish-pages
# includes public-impact.json

python -m impact_relay --all-phases --write-public-impact data/public-impact.json
```

Suite join key on public outcomes is `allocationId` (`alloc_[a-z0-9_]+`).
Phase C fixtures and vocabulary: [CONTRACT-GOVERNANCE.md](CONTRACT-GOVERNANCE.md).
