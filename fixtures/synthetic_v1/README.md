# AutoGive Synthetic Dataset v1 — Impact Relay

Compact Civic Forge fixture universe for this library. Classification is
`SYNTHETIC_ONLY`. It is not a live cohort, not Every.org, and not `OBSERVED`.

Canonical NATIVE gifts, donors, and roles live in Portfolio Signals
`fixtures/autogive-v1/`. This directory is the BRIDGE projection.

| File | Surface |
|---|---|
| `civic_forge_ledger_v1.json` | `load_fixture` / `run_pilot` compact ledger |
| `public_impact.json` | IR public-impact schema (outcomes). Does **not** replace `data/public-impact.json` |
| `MAPPING.md` | PS bridge → IR domain |

```bash
python -c "from impact_relay.pilot import run_pilot, DEFAULT_SYNTHETIC_V1_FIXTURE; run_pilot(DEFAULT_SYNTHETIC_V1_FIXTURE, finance_actor='civicforge.finance@example.test')"
pytest tests/test_synthetic_v1_corpus.py
```

Do not run `--publish-pages` to promote this fixture into `data/`. The live
public shell stays gated and empty.
