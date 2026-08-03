"""Impact Relay — donor fund use + impact notification domain core.

HD-IR-001: use-of-funds ledger pilot
HD-IR-002: privacy-safe public export for GitHub Pages
HD-IR-003: impact digests + aggregate reconciliation for Pages
HD-IR-004: domain digests + Every.org aggregate adapter
Phases 2–6: donor reads, notifications, impact, multi-tenant fixture pilot
"""

from impact_relay.accounting import (
    AccountingExpenseSource,
    AccountingSourceError,
    HTTPSJSONAccountingConfig,
    HTTPSJSONAccountingExpenseSource,
    open_accounting_expense_source,
)
from impact_relay.digest import build_public_digests, digests_from_workspace
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
from impact_relay.donor import open_donor_api
from impact_relay.every_org import every_org_to_reconcile_aggregate
from impact_relay.host import open_hacker_dojo_session, open_host_session
from impact_relay.pilot import run_all_phases_pilot, run_pilot
from impact_relay.privacy_ops import (
    DonorNotificationEraseReceipt,
    erase_donor_notification_state,
    export_donor_data,
    export_donor_data_json,
)
from impact_relay.public_export import build_public_export, receipt_to_public
from impact_relay.reconcile import apply_aggregate_reconciliation
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    CANONICAL_POLICY_SLUG,
)

__all__ = [
    "CANONICAL_PILOT_TENANT_ID",
    "CANONICAL_POLICY_SLUG",
    "AccountingExpenseSource",
    "AccountingSourceError",
    "Allocation",
    "AttributionMethod",
    "Donation",
    "DonorNotificationEraseReceipt",
    "Expense",
    "ExpenseState",
    "HTTPSJSONAccountingConfig",
    "HTTPSJSONAccountingExpenseSource",
    "Ledger",
    "Platform",
    "RestrictionType",
    "TenantWorkspace",
    "UseOfFundsReceipt",
    "apply_aggregate_reconciliation",
    "build_public_digests",
    "build_public_export",
    "digests_from_workspace",
    "erase_donor_notification_state",
    "every_org_to_reconcile_aggregate",
    "export_donor_data",
    "export_donor_data_json",
    "open_accounting_expense_source",
    "open_donor_api",
    "open_hacker_dojo_session",
    "open_host_session",
    "receipt_to_public",
    "run_all_phases_pilot",
    "run_pilot",
]

__version__ = "0.9.1"
