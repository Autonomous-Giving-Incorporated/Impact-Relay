"""Impact Relay — donor fund use + outcome notification domain core.

HD-IR-001 ships the ledger pilot: donation → allocation → expense approval →
use-of-funds receipt (preview/publish artifact only).

HD-IR-002 ships privacy-safe public export for GitHub Pages.
HD-IR-003 ships impact digests and aggregate reconciliation.
"""

from impact_relay.digest import build_public_digests
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.types import (
    Allocation,
    AttributionMethod,
    Donation,
    Expense,
    ExpenseState,
    RestrictionType,
    UseOfFundsReceipt,
)
from impact_relay.public_export import build_public_export, receipt_to_public
from impact_relay.reconcile import apply_aggregate_reconciliation

__all__ = [
    "Ledger",
    "Allocation",
    "AttributionMethod",
    "Donation",
    "Expense",
    "ExpenseState",
    "RestrictionType",
    "UseOfFundsReceipt",
    "build_public_export",
    "receipt_to_public",
    "build_public_digests",
    "apply_aggregate_reconciliation",
]

__version__ = "0.3.0"
