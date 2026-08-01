"""Hacker Dojo host entrypoints — canonical pilot integration."""

from __future__ import annotations

from pathlib import Path

from impact_relay.host.session import HostSession, open_host_session
from impact_relay.storage.template import (
    CANONICAL_DISPLAY_NAME,
    CANONICAL_PILOT_TENANT_ID,
    CANONICAL_POLICY_SLUG,
    CANONICAL_POLICY_VERSION,
)

# Default local data-dir for Hacker-Dojo app / library demos
DEFAULT_HACKER_DOJO_DATA_DIR = Path(".impact-relay/hacker-dojo")


def open_hacker_dojo_session(
    data_dir: Path | str | None = None,
    *,
    ensure_registered: bool = True,
) -> HostSession:
    """Open the canonical Hacker Dojo host session.

    This is what the Hacker-Dojo application repo should call. Other nonprofits
    use ``open_host_session(tenant_id=..., display_name=...)`` instead — same
    class, different tenant identity.
    """
    return open_host_session(
        data_dir or DEFAULT_HACKER_DOJO_DATA_DIR,
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        display_name=CANONICAL_DISPLAY_NAME,
        ensure_registered=ensure_registered,
    )


def hacker_dojo_identity() -> dict[str, str]:
    """Stable constants for host config / CI."""
    return {
        "tenant_id": CANONICAL_PILOT_TENANT_ID,
        "policy_slug": CANONICAL_POLICY_SLUG,
        "policy_version": CANONICAL_POLICY_VERSION,
        "display_name": CANONICAL_DISPLAY_NAME,
        "default_data_dir": str(DEFAULT_HACKER_DOJO_DATA_DIR),
    }
