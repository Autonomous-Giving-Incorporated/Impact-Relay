"""Thin host-app adapter for Impact Relay.

The Hacker-Dojo application (and future nonprofit hosts) should prefer this
API over wiring durable + storage internals by hand.

Canonical pilot::

    from impact_relay.host import open_hacker_dojo_session

    with open_hacker_dojo_session("./hd-pilot") as session:
        session.seed()
        session.approve(approver_id="finance@hackersdojo.org")
        expenses = session.list_expenses()
"""

from impact_relay.host.hacker_dojo import (
    DEFAULT_HACKER_DOJO_DATA_DIR,
    open_hacker_dojo_session,
)
from impact_relay.host.session import HostSession, open_host_session
from impact_relay.storage.template import (
    CANONICAL_DISPLAY_NAME,
    CANONICAL_PILOT_TENANT_ID,
    CANONICAL_POLICY_SLUG,
    CANONICAL_POLICY_VERSION,
)

__all__ = [
    "CANONICAL_DISPLAY_NAME",
    "CANONICAL_PILOT_TENANT_ID",
    "CANONICAL_POLICY_SLUG",
    "CANONICAL_POLICY_VERSION",
    "DEFAULT_HACKER_DOJO_DATA_DIR",
    "HostSession",
    "open_hacker_dojo_session",
    "open_host_session",
]
