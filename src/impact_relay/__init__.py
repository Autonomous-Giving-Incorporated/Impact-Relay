"""Impact Relay — donor fund use + outcome notification domain core.

HD-IR-001 ships the ledger pilot: donation → allocation → expense approval →
use-of-funds receipt (preview/publish artifact only).
"""

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

__all__ = [
    "Ledger",
    "Allocation",
    "AttributionMethod",
    "Donation",
    "Expense",
    "ExpenseState",
    "RestrictionType",
    "UseOfFundsReceipt",
]

__version__ = "0.1.0"
