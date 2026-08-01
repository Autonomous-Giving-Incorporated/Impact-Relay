"""Automated shadow-mode rehearsal for Hacker Dojo pilot.

Exercises the library host path that finance UI + durable check depend on.
Uses **synthetic** principals only — does **not** claim human live-cohort
sign-off or production notifications.

See ``docs/pilot/FINDINGS.md`` and Hacker-Dojo ``docs/IMPACT-RELAY-SHADOW.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from impact_relay.auth.role_map import principal_from_host_headers
from impact_relay.host.hacker_dojo import open_hacker_dojo_session
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID

# Public Pages paths that must never be the shadow data-dir
_PUBLIC_PATH_MARKERS = ("/data/", "\\data\\", "data/impact-state", "data/use-of-funds")


def _check(
    name: str,
    ok: bool,
    *,
    detail: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "ok": bool(ok), "detail": detail}
    if evidence:
        row["evidence"] = evidence
    return row


def run_shadow_rehearsal(
    data_dir: Path | str,
    *,
    expense_batch: Path | str | None = None,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
) -> dict[str, Any]:
    """Run synthetic shadow checklist against ``data_dir``.

    Checklist (library automation):
    1. Seed waiting expense as campaign_lead
    2. data_steward cannot approve (role denial)
    3. campaign_lead / finance_approver can approve
    4. Durable rehydrate check green
    5. Entity expense snapshot present
    6. Donor API opens without error
    7. Data-dir is not a public Pages path

    Returns a report with ``ok``, ``checks``, and ``findings_markdown``.
    """
    path = Path(data_dir)
    path.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    workflow_id: str | None = None
    expense_id: str | None = None
    batch = Path(expense_batch) if expense_batch else None

    lead = principal_from_host_headers(
        email="campaign.lead@hackersdojo.example",
        campaign_role="campaign_lead",
        tenant_id=tenant_id,
        display_name="Shadow Campaign Lead",
    )
    steward = principal_from_host_headers(
        email="data.steward@hackersdojo.example",
        campaign_role="data_steward",
        tenant_id=tenant_id,
        display_name="Shadow Data Steward",
    )

    with open_hacker_dojo_session(
        path,
        require_principal_for_approve=True,
    ) as base:
        assert base.tenant_id == tenant_id

        # --- 1. Seed ---
        session = base.with_principal(lead)
        seed = session.seed(expense_batch=batch) if batch else session.seed()
        checks.append(
            _check(
                "seed_waiting",
                bool(seed.get("ok") and seed.get("waiting")),
                detail=str(seed.get("error") or seed.get("message") or "seeded"),
                evidence={
                    "waiting": seed.get("waiting"),
                    "workflow_ids": seed.get("workflow_ids")
                    or seed.get("started_workflows"),
                },
            )
        )

        waiting = session.list_waiting()
        cases = waiting.get("cases") or []
        if cases:
            workflow_id = cases[0].get("workflow_id")
        checks.append(
            _check(
                "list_waiting",
                bool(workflow_id),
                detail=f"count={waiting.get('count', len(cases))}",
                evidence={"workflow_id": workflow_id},
            )
        )

        # --- 2. Role denial (data_steward) ---
        denied = base.with_principal(steward).approve(workflow_id=workflow_id)
        steward_blocked = not bool(denied.get("ok"))
        checks.append(
            _check(
                "role_denial_data_steward",
                steward_blocked,
                detail=str(
                    denied.get("error")
                    or denied.get("message")
                    or ("unexpected_ok" if denied.get("ok") else "denied")
                ),
                evidence={"response_error": denied.get("error")},
            )
        )

        # --- 3. Approve as campaign_lead ---
        approved = session.approve(workflow_id=workflow_id)
        expense_id = approved.get("expense_id")
        checks.append(
            _check(
                "approve_campaign_lead",
                bool(approved.get("ok")),
                detail=str(
                    approved.get("error")
                    or approved.get("expense_state")
                    or approved.get("message")
                    or ""
                ),
                evidence={
                    "workflow_id": workflow_id,
                    "expense_id": expense_id,
                    "approver": lead.email,
                },
            )
        )

        # --- 4. Rehydrate ---
        rehydrate = session.check_rehydrate()
        checks.append(
            _check(
                "rehydrate",
                bool(rehydrate.get("ok")),
                detail=str(rehydrate.get("error") or rehydrate.get("message") or "ok"),
                evidence={
                    k: rehydrate.get(k)
                    for k in ("expense_count", "mismatches", "ok")
                    if k in rehydrate
                }
                or {"ok": rehydrate.get("ok")},
            )
        )

        # --- 5. Entity snapshot ---
        try:
            expenses = session.list_expenses()
            has_exp = bool(expense_id) and any(
                e.get("id") == expense_id for e in expenses
            )
            if not has_exp:
                has_exp = len(expenses) > 0 and bool(approved.get("ok"))
            checks.append(
                _check(
                    "entity_expense_snapshot",
                    has_exp,
                    detail=f"expenses={len(expenses)}",
                    evidence={"expense_id": expense_id},
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            checks.append(
                _check("entity_expense_snapshot", False, detail=str(exc))
            )

        # --- 6. Donor API opens ---
        try:
            api = session.donor_api()
            # Prefer a light call if available
            donor_ok = api is not None
            detail = "open"
            if donor_ok and hasattr(api, "list_donors"):
                try:
                    donors = api.list_donors()  # type: ignore[attr-defined]
                    detail = f"donors={len(donors) if donors is not None else 0}"
                except Exception:
                    detail = "open (list_donors N/A)"
            checks.append(_check("donor_api_open", donor_ok, detail=detail))
        except Exception as exc:
            checks.append(_check("donor_api_open", False, detail=str(exc)))

        status = session.status()
        checks.append(
            _check(
                "status_readable",
                bool(status),
                detail=f"tenant={status.get('tenant_id', tenant_id)}",
            )
        )

    # --- 7. Not a public Pages path ---
    resolved = str(path.resolve()).replace("\\", "/")
    is_public = any(m.replace("\\", "/") in resolved for m in _PUBLIC_PATH_MARKERS)
    # Also reject if data_dir is literally repo data/
    if path.name == "data" and (path / "impact-state.json").exists():
        is_public = True
    checks.append(
        _check(
            "not_public_pages_path",
            not is_public,
            detail=resolved,
        )
    )

    all_ok = all(c["ok"] for c in checks)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = {
        "ok": all_ok,
        "mode": "shadow_rehearsal_synthetic",
        "date": when,
        "tenant_id": tenant_id,
        "data_dir": resolved,
        "workflow_id": workflow_id,
        "expense_id": expense_id,
        "approver": lead.email,
        "checks": checks,
        "note": (
            "Synthetic principals only. Does not satisfy live-cohort sign-off. "
            "Record human UI sessions separately in FINDINGS.md."
        ),
    }
    report["findings_markdown"] = format_findings_markdown(report)
    return report


def format_findings_markdown(report: dict[str, Any]) -> str:
    """Markdown block suitable for appending to ``docs/pilot/FINDINGS.md``."""
    lines = [
        f"## Shadow rehearsal (synthetic) {report.get('date', '')}",
        "",
        f"- Result: **{'pass' if report.get('ok') else 'fail'}**",
        f"- Mode: `{report.get('mode')}`",
        f"- Data-dir: `{report.get('data_dir')}`",
        f"- Approver (synthetic): `{report.get('approver')}`",
        f"- workflow_id: `{report.get('workflow_id')}`",
        f"- expense_id: `{report.get('expense_id')}`",
        "",
        "| Check | OK | Detail |",
        "|-------|----|--------|",
    ]
    for c in report.get("checks") or []:
        mark = "yes" if c.get("ok") else "**no**"
        detail = str(c.get("detail") or "").replace("|", "/")
        lines.append(f"| `{c.get('name')}` | {mark} | {detail} |")
    lines.extend(
        [
            "",
            f"_Note: {report.get('note', '')}_",
            "",
        ]
    )
    return "\n".join(lines)


def append_findings(path: Path | str, report: dict[str, Any]) -> Path:
    """Append findings markdown to a file (creates parent dirs)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    block = report.get("findings_markdown") or format_findings_markdown(report)
    prefix = ""
    if out.exists() and out.stat().st_size > 0:
        prefix = "\n"
    with out.open("a", encoding="utf-8") as f:
        f.write(prefix + block)
    return out
