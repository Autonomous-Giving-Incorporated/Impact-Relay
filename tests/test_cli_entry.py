"""Entry-path tests: CLI and pilot module drive shipped domain code."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from impact_relay.cli import main
from impact_relay.pilot import run_pilot

ROOT = Path(__file__).resolve().parents[1]


def test_run_pilot_twice_consistent_structure() -> None:
    _, r1 = run_pilot()
    _, r2 = run_pilot()
    d1, d2 = r1[0].to_dict(), r2[0].to_dict()
    for key in (
        "type",
        "remaining_designated_balance",
    ):
        assert d1[key] == d2[key]
    assert d1["allocation"]["name"] == d2["allocation"]["name"]
    assert d1["expenditure"]["gross_amount"] == d2["expenditure"]["gross_amount"]
    assert d1["expenditure"]["verification_state"] in {"APPROVED", "RECONCILED"}
    assert d1["attribution"]["method"]
    assert d1["provenance"]["receipt_hash"]
    assert d1["receipt_id"]
    assert d2["receipt_id"]


def test_cli_main_prints_json_receipt(capsys) -> None:
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["receipt_count"] >= 1
    receipt = payload["receipts"][0]
    assert receipt["allocation"]["name"]
    assert receipt["expenditure"]["gross_amount"]
    assert receipt["expenditure"]["verification_state"] in {"APPROVED", "RECONCILED"}
    assert receipt["remaining_designated_balance"]
    assert receipt["attribution"]["method"]
    assert receipt["receipt_id"]
    assert receipt["provenance"]["receipt_hash"]


def test_module_entry_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "impact_relay", "--fixture", str(ROOT / "fixtures" / "pilot_hd_ir_001.json")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**dict(**__import__("os").environ), "PYTHONPATH": str(ROOT / "src")},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["receipts"][0]["type"] == "USE_OF_FUNDS"
