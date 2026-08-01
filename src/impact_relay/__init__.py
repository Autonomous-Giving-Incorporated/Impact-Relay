"""Impact Relay — donor fund use + impact notification domain core.

HD-IR-001: use-of-funds ledger pilot
HD-IR-002: privacy-safe public export for GitHub Pages
HD-IR-003: impact digests + aggregate reconciliation for Pages
HD-IR-004: domain digests + Every.org aggregate adapter
Phases 2–6: donor reads, notifications, impact, multi-tenant fixture pilot
"""

from impact_relay.digest import build_public_digests, digests_from_workspace
from impact_relay.every_org import every_org_to_reconcile_aggregate
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import Platform, TenantWorkspace
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    CANONICAL_POLICY_SLUG,
)
from impact_relay.domain.types import (
    Allocation,
    AttributionMethod,
    Donation,
    Expense,
    ExpenseState,
    RestrictionType,
    UseOfFundsReceipt,
)
from impact_relay.pilot import run_all_phases_pilot, run_pilot
from impact_relay.public_export import build_public_export, receipt_to_public
from impact_relay.reconcile import apply_aggregate_reconciliation

__all__ = [
    "CANONICAL_PILOT_TENANT_ID",
    "CANONICAL_POLICY_SLUG",
    "Ledger",
    "Platform",
    "TenantWorkspace",
    "Allocation",
    "AttributionMethod",
    "Donation",
    "Expense",
    "ExpenseState",
    "RestrictionType",
    "UseOfFundsReceipt",
    "run_pilot",
    "run_all_phases_pilot",
    "build_public_export",
    "receipt_to_public",
    "build_public_digests",
    "digests_from_workspace",
    "apply_aggregate_reconciliation",
    "every_org_to_reconcile_aggregate",
]

__version__ = "0.5.0"
