#!/usr/bin/env python3
"""Validate the platform conformance manifest.

The manifest is intentionally lightweight. This script validates that:
- the file is valid JSON/YAML-lite content,
- required top-level keys are present,
- all declared artifacts exist,
- optional check objects are structurally sane.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Impact Relay platform conformance manifest and required artifacts."
    )
    parser.add_argument(
        "--manifest",
        default="docs/platform-conformance.yml",
        help="Path to platform-conformance manifest",
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


def _validate_checks(checks: Any) -> None:
    if not isinstance(checks, list):
        raise SystemExit("top-level `checks` must be a list")

    for idx, check in enumerate(checks):
        if not isinstance(check, dict):
            raise SystemExit(f"check[{idx}] must be an object")
        _require_keys(
            check,
            location=f"check[{idx}]",
            keys=["id", "title", "requirement", "required", "scope", "evidence"],
        )
        if not isinstance(check["required"], bool):
            raise SystemExit(f"check[{idx}].required must be bool")
        if not _is_list_of_strs(check["scope"]):
            raise SystemExit(f"check[{idx}].scope must be a list of strings")
        ev = check["evidence"]
        if not isinstance(ev, dict):
            raise SystemExit(f"check[{idx}].evidence must be an object")
        for field in ["artifacts", "tests", "commands", "evidence_fields"]:
            if field not in ev:
                raise SystemExit(f"check[{idx}].evidence missing {field}")
            if not _is_list_of_strs(ev[field]):
                raise SystemExit(f"check[{idx}].evidence.{field} must be a list of strings")


def validate_manifest(data: dict[str, Any]) -> list[str]:
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

    missing: list[str] = []
    for artifact in data["required_artifacts"]:
        if not Path(artifact).exists():
            missing.append(artifact)

    if missing:
        print("Missing required platform conformance artifacts:")
        for artifact in missing:
            print(f"- {artifact}")
        raise SystemExit(1)

    _validate_checks(data["checks"])
    return missing


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")

    data = _load_json(manifest_path)
    validate_manifest(data)
    print(
        f"platform conformance manifest OK: {manifest_path} ("
        f"platform={data.get('platform')}, revision={data.get('revision')}, "
        f"checks={len(data.get('checks', []))})"
    )


if __name__ == "__main__":
    main()
