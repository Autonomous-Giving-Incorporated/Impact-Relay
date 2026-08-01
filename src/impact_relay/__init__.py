"""Impact Relay — donor fund use + impact notification domain core.

HD-IR-001: use-of-funds ledger pilot
HD-IR-002: privacy-safe public export for GitHub Pages
HD-IR-003: impact digests + aggregate reconciliation for Pages
Phases 2–6: donor reads, notifications, impact, multi-tenant fixture pilot
"""

from impact_relay.digest import build_public_digests
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import Platform, TenantWorkspace
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
    "apply_aggregate_reconciliation",
]

__version__ = "0.3.0"
