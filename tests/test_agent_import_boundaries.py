"""Architecture guard: agent modules must not call ledger mutations directly.

Only LedgerCommandExecutor (expense_workflow) may import Ledger mutation APIs.
"""

from __future__ import annotations

import ast
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parents[1] / "src" / "impact_relay" / "agents"

# Files allowed to import Ledger / call domain mutations.
ALLOWED_LEDGER_IMPORT = frozenset({"expense_workflow.py"})

FORBIDDEN_ATTRS = frozenset(
    {
        "approve_expense",
        "import_expense",
        "allocate_expense",
        "allocate_expense_splits",
        "publish_use_of_funds_receipt",
        "attribute_donor_to_expense",
        "import_donation",
        "reconcile_expense",
    }
)


def test_non_executor_agents_do_not_import_ledger() -> None:
    for path in AGENTS_DIR.glob("*.py"):
        if path.name in ALLOWED_LEDGER_IMPORT or path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.endswith("domain.ledger") or mod == "impact_relay.domain.ledger":
                    raise AssertionError(
                        f"{path.name} must not import ledger; use LedgerCommandExecutor"
                    )
                for alias in node.names:
                    if alias.name == "Ledger":
                        raise AssertionError(f"{path.name} imports Ledger")


def test_authority_and_privacy_have_no_mutation_calls() -> None:
    for name in ("authority.py", "privacy.py", "types.py", "base.py"):
        path = AGENTS_DIR / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
                raise AssertionError(f"{name} references forbidden mutation {node.attr}")
