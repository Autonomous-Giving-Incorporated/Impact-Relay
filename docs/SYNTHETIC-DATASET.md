# AutoGive Synthetic Dataset v1

Canonical **development / disposable** Civic Forge universe for Impact Relay.
Classification is `SYNTHETIC_ONLY`. It is not live campaign data, not Every.org,
and not `OBSERVED`.

```yaml
dataset: autogive-synthetic-dataset
version: 1.0.0
seed: 20260821
classification: SYNTHETIC_ONLY
tenant_id: org_synthetic_civic_forge
campaign_id: cmp_synthetic_builder_fund_2026
```

Hacker Dojo (`org_hacker_dojo`) remains the reference tenant. Civic Forge sits
beside it. Portfolio Signals owns NATIVE gifts, donors, roles, and pots
(`fixtures/autogive-v1/`). This repo owns the BRIDGE ledger and public-impact
projection.

## Commands

```bash
pip install -e ".[dev]"
pytest tests/test_synthetic_v1_corpus.py
```

Library entry (does not change the HD default pilot):

```python
from impact_relay.pilot import DEFAULT_SYNTHETIC_V1_FIXTURE, run_pilot

ledger, receipts = run_pilot(
    DEFAULT_SYNTHETIC_V1_FIXTURE,
    finance_actor="civicforge.finance@example.test",
)
```

Do **not** run `python -m impact_relay --publish-pages` to promote this fixture
into `data/`. Live `data/public-impact.json` stays the gated empty shell.

## Where the fixture lives

| Path | Surface |
|---|---|
| `fixtures/synthetic_v1/civic_forge_ledger_v1.json` | Compact ledger for `run_pilot` |
| `fixtures/synthetic_v1/public_impact.json` | IR public-impact outcomes (`PILOT`, not OBSERVED) |
| `fixtures/synthetic_v1/MAPPING.md` | PS bridge → IR domain |

The compact ledger credits hardware 90910 and scholarships 67880 only. Facility
and community-programs allocations are registered for suite ID stability and
have **zero** cleared gifts. Happy-path publish is expenses 001–003.

## Public vs private

Public `public_impact.json` is aggregate-only: no donor rows, no emails,
`piiAllowed=false`. Raised / committed / donor-count figures live on the
Portfolio Signals impact-state fixture (`raisedSource=pilot_synthetic`), not on
this IR outcomes document.

Schema mapping and edge ownership: [`fixtures/synthetic_v1/MAPPING.md`](../fixtures/synthetic_v1/MAPPING.md).
