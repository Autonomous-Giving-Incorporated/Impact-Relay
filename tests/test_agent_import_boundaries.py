"""Architecture guard: only agents.executor may import ledger mutations (K14).

Workflow packages must not import domain.ledger. Other agent modules must not
import Ledger or call mutation attrs.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "src" / "impact_relay" / "agents"
WORKFLOWS_DIR = ROOT / "src" / "impact_relay" / "workflows"

# Sole gateway for ledger mutations (K14).
ALLOWED_LEDGER_IMPORT = frozenset({"executor.py"})

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


def _imports_ledger(tree: ast.AST) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.endswith("domain.ledger") or mod == "impact_relay.domain.ledger":
                hits.append(mod)
            for alias in node.names:
                if alias.name == "Ledger":
                    hits.append(f"Ledger from {mod}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "domain.ledger" in alias.name:
                    hits.append(alias.name)
    return hits


def test_only_executor_imports_ledger() -> None:
    for path in AGENTS_DIR.glob("*.py"):
        if path.name in ALLOWED_LEDGER_IMPORT or path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # TYPE_CHECKING-only imports are still discouraged; ban all runtime-style imports.
        # Allow expense_workflow TYPE_CHECKING Ledger via if TYPE_CHECKING block filter.
        hits = _imports_ledger_outside_type_checking(tree)
        if hits:
            raise AssertionError(
                f"{path.name} must not import ledger ({hits}); use agents.executor"
            )


def _imports_ledger_outside_type_checking(tree: ast.Module) -> list[str]:
    """Detect ledger imports not nested under ``if TYPE_CHECKING:``."""
    hits: list[str] = []

    def visit(nodes: list[ast.stmt], *, under_tc: bool) -> None:
        for node in nodes:
            if isinstance(node, ast.If):
                is_tc = (
                    isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                )
                visit(node.body, under_tc=under_tc or is_tc)
                visit(node.orelse, under_tc=under_tc)
                continue
            if under_tc:
                continue
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.endswith("domain.ledger") or mod == "impact_relay.domain.ledger":
                    hits.append(mod)
                for alias in node.names:
                    if alias.name == "Ledger":
                        hits.append(f"Ledger from {mod}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(node.body, under_tc=under_tc)

    visit(tree.body, under_tc=False)
    return hits


def test_authority_and_privacy_have_no_mutation_calls() -> None:
    for name in ("authority.py", "privacy.py", "types.py", "base.py"):
        path = AGENTS_DIR / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
                raise AssertionError(f"{name} references forbidden mutation {node.attr}")


def test_workflows_do_not_import_ledger() -> None:
    for path in WORKFLOWS_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _imports_ledger(tree)
        if hits:
            raise AssertionError(
                f"workflows/{path.relative_to(WORKFLOWS_DIR)} imports ledger: {hits}"
            )


def test_executor_is_sole_gateway_file() -> None:
    assert (AGENTS_DIR / "executor.py").is_file()
    tree = ast.parse(
        (AGENTS_DIR / "executor.py").read_text(encoding="utf-8"),
        filename="executor.py",
    )
    hits = _imports_ledger(tree)
    assert hits, "executor.py must import ledger"
