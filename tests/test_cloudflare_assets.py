"""Workers static-asset staging copies only the public aggregate tracker."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_JSON = (
    "impact-state.json",
    "use-of-funds-public.json",
    "impact-digests-public.json",
    "public-evidence.json",
    "public-impact.json",
)
FORBIDDEN_TOP_LEVEL = ("src", "tests", "fixtures", "policies", "schemas", "docs")


def _stage(tmp_path: Path) -> Path:
    env = os.environ.copy()
    env["CLOUDFLARE_ASSETS_DIR"] = str(tmp_path)
    subprocess.run(
        [str(ROOT / "scripts" / "stage_cloudflare_assets.sh")],
        check=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return tmp_path


def test_wrangler_toml_is_assets_only() -> None:
    config = tomllib.loads((ROOT / "wrangler.toml").read_text(encoding="utf-8"))
    assert config["name"] == "impact-relay"
    assert "main" not in config
    assert config["assets"]["directory"] == "./.cloudflare-assets"
    assert config["assets"]["not_found_handling"] == "none"


def test_stage_cloudflare_assets_copies_public_tracker_only(tmp_path: Path) -> None:
    out = _stage(tmp_path)
    site = out / "impact-relay"
    for name in ("index.html", "app.js", "styles.css", "tokens.css"):
        assert (site / name).is_file(), name
    for name in PUBLIC_JSON:
        assert (site / "data" / name).is_file(), name
    assert (site / "assets" / "brand" / "agi-mark.png").is_file()
    assert (out / "_headers").is_file()
    assert (out / "_redirects").is_file()
    assert (out / "index.html").is_file()
    staged_top = {path.name for path in out.iterdir()}
    assert staged_top.isdisjoint(FORBIDDEN_TOP_LEVEL)
    assert not (out / "src").exists()
    blob = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="/impact-relay/"' in blob
    headers = (out / "_headers").read_text(encoding="utf-8")
    assert "X-Frame-Options: DENY" in headers
    assert "X-Content-Type-Options: nosniff" in headers
    assert "/impact-relay/data/*" in headers
    redirects = (out / "_redirects").read_text(encoding="utf-8")
    assert "/ /impact-relay/ 302" in redirects


def test_stage_cloudflare_assets_does_not_rewrite_aggregates(tmp_path: Path) -> None:
    out = _stage(tmp_path)
    for name in PUBLIC_JSON:
        original = (ROOT / "data" / name).read_bytes()
        staged = (out / "impact-relay" / "data" / name).read_bytes()
        assert staged == original
