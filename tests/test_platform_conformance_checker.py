from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_platform_conformance.py"
SPEC = importlib.util.spec_from_file_location("check_platform_conformance", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


REQUIRED_ARTIFACTS = [
    "docs/PLATFORM-CONFORMANCE.md",
    "docs/DOMAIN-MODEL.md",
    "docs/AGENT-CONTRACTS.md",
]


def _write_manifest(root: Path, data: dict) -> Path:
    manifest_path = root / "docs" / "platform-conformance.yml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest_path


def _write_required_files(root: Path) -> None:
    for relpath in REQUIRED_ARTIFACTS:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")


def _base_manifest(command: str = "python3 -c \"print('ok')\"") -> dict:
    return {
        "schema_version": 1,
        "platform": "Impact Relay",
        "revision": "0.9.1",
        "required_artifacts": REQUIRED_ARTIFACTS,
        "checks": [
            {
                "id": "SPEC-TEST.01",
                "title": "Synthetic check",
                "requirement": "Synthetic requirement",
                "required": True,
                "scope": ["src/example.py"],
                "evidence": {
                    "artifacts": ["docs/PLATFORM-CONFORMANCE.md"],
                    "tests": ["tests/test_platform_conformance_checker.py"],
                    "commands": [command],
                    "evidence_fields": ["synthetic evidence"],
                },
            }
        ],
    }


def test_validate_manifest_accepts_valid_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_required_files(tmp_path)
    data = _base_manifest()
    _write_manifest(tmp_path, data)

    checks = MODULE.validate_manifest(data)

    assert len(checks) == 1
    assert checks[0]["id"] == "SPEC-TEST.01"


def test_validate_manifest_rejects_empty_command_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_required_files(tmp_path)
    data = _base_manifest(command="   ")
    _write_manifest(tmp_path, data)

    with pytest.raises(
        SystemExit, match=r"check\[0\]\.evidence\.commands contains empty string entries"
    ):
        MODULE.validate_manifest(data)


def test_validate_manifest_rejects_missing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    data = _base_manifest()
    _write_manifest(tmp_path, data)

    with pytest.raises(SystemExit) as exc_info:
        MODULE.validate_manifest(data)

    assert exc_info.value.code == 1
    captured = capsys.readouterr().out
    assert "Missing required platform conformance artifacts:" in captured


def test_collect_unique_commands_deduplicates_and_tracks_owners() -> None:
    checks = [
        {
            "id": "SPEC-TEST.01",
            "evidence": {
                "commands": [
                    "pytest -q tests/test_alpha.py",
                    "pytest -q tests/test_beta.py",
                ]
            },
        },
        {
            "id": "SPEC-TEST.02",
            "evidence": {"commands": ["pytest -q tests/test_beta.py"]},
        },
    ]

    command_map = MODULE.collect_unique_commands(checks)

    assert list(command_map) == [
        "pytest -q tests/test_alpha.py",
        "pytest -q tests/test_beta.py",
    ]
    assert command_map["pytest -q tests/test_beta.py"] == [
        "SPEC-TEST.01",
        "SPEC-TEST.02",
    ]


def test_run_evidence_commands_executes_unique_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    counter = tmp_path / "counter.txt"
    command = (
        "python3 -c "
        f"\"from pathlib import Path; p=Path(r'{counter}'); "
        "n=int(p.read_text() or '0') if p.exists() else 0; "
        "p.write_text(str(n+1))\""
    )
    command_map = MODULE.collect_unique_commands(
        [
            {"id": "SPEC-TEST.01", "evidence": {"commands": [command]}},
            {"id": "SPEC-TEST.02", "evidence": {"commands": [command]}},
        ]
    )

    MODULE.run_evidence_commands(command_map, cwd=tmp_path)

    assert counter.read_text(encoding="utf-8") == "1"
    captured = capsys.readouterr().out
    assert "Executing 1 unique evidence command(s)" in captured
    assert "checks: SPEC-TEST.01, SPEC-TEST.02" in captured


def test_run_evidence_commands_surfaces_failing_check_ids(tmp_path: Path) -> None:
    command_map = MODULE.collect_unique_commands(
        [
            {
                "id": "SPEC-TEST.01",
                "evidence": {"commands": ['python3 -c "raise SystemExit(7)"']},
            }
        ]
    )

    with pytest.raises(SystemExit, match=r"checks \[SPEC-TEST\.01\] with exit code 7"):
        MODULE.run_evidence_commands(command_map, cwd=tmp_path)
