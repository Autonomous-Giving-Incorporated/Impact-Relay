# HD-IR-002 — Public use-of-funds export

## Objective

Publish verified use-of-funds receipts on the public GitHub Pages site without leaking donor identity or operator contact details.

## Pipeline

1. Run HD-IR-001 pilot against the synthetic fixture.
2. Project each `UseOfFundsReceipt` through `public_export.receipt_to_public`.
3. Write `data/use-of-funds-public.json`.
4. Validate with `schemas/use-of-funds-public.schema.json`.
5. Render on the tracker under **Use of funds**.

## Privacy rules

| Field class | Public? |
|---|---|
| Allocation name / purpose description | Yes |
| Expense category, vendor, amounts | Yes |
| Attribution method / verification state | Yes |
| Receipt content hash | Yes |
| Donor id / donor display name | No |
| Donation reference | No |
| Operator email / approved_by | No |

## Stability

Public `receiptId` values are derived from `receipt_hash` (`pub_<hash12>`) so regenerating the export from the same pilot content is deterministic for CI drift checks.

## Evidence

- Domain tests: `tests/test_public_export.py`
- CI: `ledger-tests` job regenerates export and asserts no donor residue
- Live site loads `data/use-of-funds-public.json` with a client privacy fail-closed check
