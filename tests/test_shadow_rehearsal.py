"""Automated synthetic shadow-mode rehearsal."""

from __future__ import annotations

from pathlib import Path

from impact_relay.host.rehearsal import (
    append_findings,
    format_findings_markdown,
    run_shadow_rehearsal,
)

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def test_shadow_rehearsal_passes(tmp_path: Path) -> None:
    data_dir = tmp_path / "shadow"
    report = run_shadow_rehearsal(data_dir, expense_batch=BATCH)
    assert report["ok"] is True
    assert report["mode"] == "shadow_rehearsal_synthetic"
    names = {c["name"] for c in report["checks"]}
    assert "seed_waiting" in names
    assert "role_denial_data_steward" in names
    assert "approve_campaign_lead" in names
    assert "rehydrate" in names
    assert "not_public_pages_path" in names
    assert all(c["ok"] for c in report["checks"])
    assert report["workflow_id"]
    assert report["expense_id"]
    md = report["findings_markdown"]
    assert "Shadow rehearsal" in md
    assert "pass" in md


def test_shadow_rehearsal_append_findings(tmp_path: Path) -> None:
    data_dir = tmp_path / "shadow2"
    findings = tmp_path / "FINDINGS.md"
    findings.write_text("# Pilot findings\n\n", encoding="utf-8")
    report = run_shadow_rehearsal(data_dir, expense_batch=BATCH)
    append_findings(findings, report)
    text = findings.read_text(encoding="utf-8")
    assert "Shadow rehearsal (synthetic)" in text
    assert "role_denial_data_steward" in text


def test_format_findings_markdown_fail_shape() -> None:
    md = format_findings_markdown(
        {
            "ok": False,
            "date": "2026-08-01",
            "mode": "shadow_rehearsal_synthetic",
            "data_dir": "/tmp/x",
            "approver": "a@b",
            "workflow_id": None,
            "expense_id": None,
            "checks": [{"name": "seed_waiting", "ok": False, "detail": "boom"}],
            "note": "test",
        }
    )
    assert "fail" in md
    assert "seed_waiting" in md
