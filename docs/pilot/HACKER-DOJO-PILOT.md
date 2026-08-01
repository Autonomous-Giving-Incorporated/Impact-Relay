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

- **Shadow:** run durable + donor API against copy of aggregates; no donor notifications (`deliver=False`).
- **Live cohort:** enable fixture→email only after consent records; start with staff donors.

## Findings

_Record sign-off here when pilot completes._
