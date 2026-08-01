# HD-IR-005 — Notion public evidence → Pages

## Notion findings (2026-08-01)

| Fact | Value | Label |
|---|---|---|
| Campaign minimum | $420,000 | USER_PROVIDED / OBSERVED in campaign docs |
| Campaign stretch | $2,000,000 | USER_PROVIDED / OBSERVED in campaign docs |
| Event | SupperHappyFundHouse 2026-08-21 | OBSERVED |
| Live 2026 campaign raised | **unavailable** | **NOT_COMPUTABLE** without internal/processor records |
| 2012 code-compliance campaign | ~$250,000 / ~640 backers | OBSERVED (press) |
| FY2019–FY2024 contributions | $99,776 … $66,232 (sum $432,861) | OBSERVED (Form 990 via ProPublica) |
| Meetup members | 19,641 | OBSERVED (community surface, not donors) |

Source pages:

- [Hacker Dojo — Public EvidencePack v1.0](https://app.notion.com/p/3af3e8ba2f5c8193bdecd045ff169dab)
- [Campaign Intelligence Book v1.0](https://app.notion.com/p/3af3e8ba2f5c8166a412dfc0a820fbdf)
- [Campaign Execution Kit v1.0](https://app.notion.com/p/3af3e8ba2f5c81eb939fc088e152403f)
- [Impact Relay platform spec v0.1](https://app.notion.com/p/3af3e8ba2f5c8168894eefc2e4e8c1d6)

## What this ships

```text
fixtures/notion_public_evidence_v1.json
  → notion_public.build_public_evidence_document
  → data/public-evidence.json
  → Pages “Public evidence” section
```

Also patches campaign **targets** (minimum/stretch/event) from Notion without inventing live raised cash.

## Operator runbook — export Notion aggregates

1. Open the Public EvidencePack (or successor) in Notion.
2. Copy **only** aggregate tables: Form 990 contributions, historical campaign totals, campaign targets.
3. Do **not** export donor lists, sponsor contact sheets, or gift itemization.
4. Save as JSON matching `fixtures/notion_public_evidence_v1.json`.
5. Run:

```bash
python -m impact_relay \
  --notion-public-evidence path/to/export.json \
  --write-public-evidence data/public-evidence.json \
  --write-impact-state data/impact-state.json
```

Or full Pages publish:

```bash
python -m impact_relay --publish-pages
```

## Separation of truth

| Artifact | Meaning |
|---|---|
| `data/public-evidence.json` | Historical / Form 990 OBSERVED aggregates |
| `data/impact-state.json` campaign raised | Live campaign tracker (currently pilot Every.org synthetic unless replaced) |
| Live processor export | Required for real 2026 raised; still operator-reduced aggregates only |

## Privacy

Forbidden in Notion exports used here: donors, gifts, transactions, emails, phones, rosters.
