#!/usr/bin/env python3
"""Validate the platform conformance manifest.

The manifest is intentionally lightweight. This script validates that:
- the file is valid JSON/YAML-lite content,
- required top-level keys are present,
- all declared artifacts exist,
- optional check objects are structurally sane,
- and, when requested, declared evidence commands execute successfully.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any

CHECK_REQUIRED_KEYS = ["id", "title", "requirement", "required", "scope", "evidence"]
EVIDENCE_REQUIRED_KEYS = ["artifacts", "tests", "commands", "evidence_fields"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Impact Relay platform conformance manifest and required artifacts."
    )
    parser.add_argument(
        "--manifest",
        default="docs/platform-conformance.yml",
        help="Path to platform-conformance manifest",
    )
    parser.add_argument(
        "--run-commands",
        action="store_true",
        help=(
            "Execute unique evidence commands declared in the manifest "
            "after structural validation succeeds."
        ),
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse manifest as JSON: {path} ({exc})") from exc


def _require_keys(data: dict[str, Any], *, location: str, keys: list[str]) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise SystemExit(f"{location} missing keys: {', '.join(missing)}")


def _is_list_of_strs(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_nonempty_strings(values: list[str], *, location: str) -> None:
    empty_indexes = [idx for idx, item in enumerate(values) if not item.strip()]
    if empty_indexes:
        joined = ", ".join(str(idx) for idx in empty_indexes)
        raise SystemExit(f"{location} contains empty string entries at indexes: {joined}")


def _validate_checks(checks: Any) -> list[dict[str, Any]]:
    if not isinstance(checks, list):
        raise SystemExit("top-level `checks` must be a list")

    normalized_checks: list[dict[str, Any]] = []
    for idx, check in enumerate(checks):
        if not isinstance(check, dict):
            raise SystemExit(f"check[{idx}] must be an object")
        _require_keys(check, location=f"check[{idx}]", keys=CHECK_REQUIRED_KEYS)
        if not isinstance(check["required"], bool):
            raise SystemExit(f"check[{idx}].required must be bool")
        if not _is_list_of_strs(check["scope"]):
            raise SystemExit(f"check[{idx}].scope must be a list of strings")
        _validate_nonempty_strings(check["scope"], location=f"check[{idx}].scope")
        ev = check["evidence"]
        if not isinstance(ev, dict):
            raise SystemExit(f"check[{idx}].evidence must be an object")
        for field in EVIDENCE_REQUIRED_KEYS:
            if field not in ev:
                raise SystemExit(f"check[{idx}].evidence missing {field}")
            if not _is_list_of_strs(ev[field]):
                raise SystemExit(f"check[{idx}].evidence.{field} must be a list of strings")
            _validate_nonempty_strings(ev[field], location=f"check[{idx}].evidence.{field}")
        normalized_checks.append(check)
    return normalized_checks


def collect_unique_commands(checks: list[dict[str, Any]]) -> OrderedDict[str, list[str]]:
    command_map: OrderedDict[str, list[str]] = OrderedDict()
    for check in checks:
        check_id = str(check["id"])
        for command in check["evidence"]["commands"]:
            owners = command_map.setdefault(command, [])
            if check_id not in owners:
                owners.append(check_id)
    return command_map


def run_evidence_commands(command_map: OrderedDict[str, list[str]], *, cwd: Path) -> None:
    if not command_map:
        print("No evidence commands declared. Skipping command execution.")
        return

    total = len(command_map)
    print(f"Executing {total} unique evidence command(s) from {cwd}")
    for idx, (command, check_ids) in enumerate(command_map.items(), start=1):
        owner_text = ", ".join(check_ids)
        print(f"[{idx}/{total}] {command} (checks: {owner_text})")
        result = subprocess.run(command, shell=True, cwd=cwd, check=False)
        if result.returncode != 0:
            raise SystemExit(
                "evidence command failed "
                f"for checks [{owner_text}] with exit code {result.returncode}: {command}"
            )
    print(f"Executed {total} unique evidence command(s) successfully.")


def validate_manifest(data: dict[str, Any]) -> list[dict[str, Any]]:
    _require_keys(
        data,
        location="root",
        keys=[
            "schema_version",
            "platform",
            "revision",
            "required_artifacts",
            "checks",
        ],
    )

    if not _is_list_of_strs(data["required_artifacts"]):
        raise SystemExit("required_artifacts must be a list of strings")
    _validate_nonempty_strings(data["required_artifacts"], location="required_artifacts")

    missing: list[str] = []
    for artifact in data["required_artifacts"]:
        if not Path(artifact).exists():
            missing.append(artifact)

    if missing:
        print("Missing required platform conformance artifacts:")
        for artifact in missing:
            print(f"- {artifact}")
        raise SystemExit(1)

    return _validate_checks(data["checks"])


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")

    data = _load_json(manifest_path)
    checks = validate_manifest(data)
    print(
        f"platform conformance manifest OK: {manifest_path} ("
        f"platform={data.get('platform')}, revision={data.get('revision')}, "
        f"checks={len(data.get('checks', []))})"
    )
    if args.run_commands:
        command_map = collect_unique_commands(checks)
        run_evidence_commands(command_map, cwd=Path.cwd())


if __name__ == "__main__":
    main()
