# Hacker Dojo pilot (process)

Canonical tenant: **`org_hacker_dojo`**.  
Policy: `policies/tenants/hacker-dojo.v1.0.yaml`.  
Host API: `impact_relay.host.open_hacker_dojo_session`.

## Systems of record (confirmed assumptions)

| System | Pilot source | Production path |
|--------|--------------|-----------------|
| Donations | Every.org aggregate fixture | Aggregate export reduced outside repo |
| Expenses | Fixture accounting batch | QuickBooks/Xero export → normalized rows |
| Policy | hacker-dojo.v1.0.yaml | Same file + dual review |
| Auth | Fixture OIDC / finance_approver_fixture | Host OIDC (Auth0/Clerk/…) |

See also `docs/pilot-systems-of-record.md`.

## Finance roles (approval chain)

| Step | Role | Permission |
|------|------|------------|
| Review queue | `finance_reviewer` | workflow.list, expense.read |
| Approve expense / correction | `finance_approver` | workflow.approve_expense |
| Publish / send notification | `communications_approver` | workflow.approve_publish / send |
| Audit | `auditor` | audit.read |

Map OIDC groups → these roles in the Hacker-Dojo app.

## First restricted allocation

Fixture: **Community Hardware Fund** (`alloc_community_hardware`) — donor-restricted classroom hardware (soldering / robotics kits in pilot data).

## Synthetic dry run

```bash
pip install -e '.[dev]'
python - <<'PY'
from impact_relay.host import open_hacker_dojo_session
from impact_relay.host.hacker_dojo import finance_approver_fixture

with open_hacker_dojo_session(".impact-relay/hd-dry-run", require_principal_for_approve=True) as s:
    s = s.with_principal(finance_approver_fixture())
    print(s.seed())
    w = s.list_waiting()
    print(s.approve(workflow_id=w["cases"][0]["workflow_id"]))
    print(s.status())
    api = s.donor_api()
    # After pilot fixture UOF, donor ids come from fixture ledger — use run_pilot for full UOF
print("dry-run ok")
PY
python -m impact_relay --all-phases  # multi-stage pilot with donor dashboard
```

## Shadow / live cohort

- **Shadow:** see Hacker-Dojo `docs/IMPACT-RELAY-SHADOW.md` — dedicated data-dir, finance UI + donor UI, `deliver=False` only.
- **Live cohort:** enable fixture→email only after consent records; start with staff donors; require Supabase MFA for privileged roles.

### Shadow exit criteria (copy from host runbook)

- [ ] Seed + approve via `finance-impact.html` with campaign_lead/director
- [ ] data_steward cannot approve
- [ ] Donor dashboard for fixture donor without CRM in git
- [ ] Rehydrate check green; no Pages publish from shadow dir

### Automated library rehearsal (synthetic)

Proves seed → role denial → approve → rehydrate on the host path **without** claiming human UI or live-cohort sign-off:

```bash
python -m impact_relay --shadow-rehearsal \
  --data-dir .impact-relay/shadow-rehearsal \
  --write-findings docs/pilot/FINDINGS.md
```

Still run the human UI checklist above before live cohort.

## Findings

Structured log: **[FINDINGS.md](./FINDINGS.md)**  
Live cohort procedure (host): Hacker-Dojo `docs/IMPACT-RELAY-LIVE-COHORT.md`

