# Impact Relay

Public **donation tracker** and **impact notifications** surface.

This repository publishes **aggregate campaign progress only**. It does not store donor names, emails, individual gift amounts, private notes, or contact lists.

Live site (GitHub Pages):

https://scrimshawlife-ctrl.github.io/Impact-Relay/

## What it does

- shows public raised / committed / donor-count aggregates
- tracks funding milestones and impact statements
- publishes a notification feed for campaign events
- links to the donation processor (Every.org) without handling card data
- validates the public data contract in CI before deploy

## Repository map

```text
index.html                         Public tracker UI
styles.css                         Visual system
app.js                             Client renderer
data/impact-state.json             Canonical public aggregate state
schemas/impact-state.schema.json   JSON Schema contract
SECURITY.md                        Data boundary
.github/workflows/                 Validate + GitHub Pages deploy
```

## Local preview

```bash
python3 -m http.server 8080
```

Open `http://localhost:8080`.

## Validate public state

```bash
npx --yes \
  --package ajv-cli@5 \
  --package ajv-formats@3 \
  ajv validate \
  --spec=draft2020 \
  -c ajv-formats \
  -s schemas/impact-state.schema.json \
  -d data/impact-state.json
```

## Updating totals

1. Reconcile an authorized donation export outside this repo.
2. Update only aggregate fields in `data/impact-state.json`.
3. Never commit donor names, emails, or itemized gifts.
4. Open a PR; CI must pass schema validation before Pages deploy.

## Privacy rules

| Allowed | Prohibited |
|---|---|
| Aggregate raised amount | Donor names |
| Aggregate committed amount | Emails / phones / addresses |
| Public donor count | Individual gift amounts |
| Milestone copy | Private notes / CRM fields |
| Processor deep-link | Service credentials |

## License

Apache-2.0. See [LICENSE](LICENSE).
