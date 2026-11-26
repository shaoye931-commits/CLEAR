from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum

from src.analysis.contract import DependencyContract


class StaticCheckStatus(str, Enum):
    PASS = "pass"
    SYNTAX_ERROR = "syntax_error"
    MISSING_BASE_FUNCTION = "missing_base_function"
    MISSING_EXTENDED_FUNCTION = "missing_extended_function"
    MISSING_DEPENDENCY = "missing_dependency"


@dataclass(frozen=True)
class StaticIssue:
    code: str
    message: str


@dataclass(frozen=True)
class StaticCheckResult:
    status: StaticCheckStatus
    passed: bool
    issues: tuple[StaticIssue, ...]


class _DirectCallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.names.add(node.func.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef


def _calls_in(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    collector = _DirectCallCollector()
    for statement in function.body:
        collector.visit(statement)
    return collector.names


def check_candidate(code: str, contract: DependencyContract) -> StaticCheckResult:
    """Implement the paper's V(c): Parse, required definitions, and fB in Callc(fE)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        issue = StaticIssue("syntax_error", f"{error.msg} at line {error.lineno}")
        return StaticCheckResult(StaticCheckStatus.SYNTAX_ERROR, False, (issue,))

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if contract.base_name not in functions:
        issue = StaticIssue(
            "missing_base_function",
            f"required base function {contract.base_name!r} is not defined",
        )
        return StaticCheckResult(StaticCheckStatus.MISSING_BASE_FUNCTION, False, (issue,))
    if contract.extended_name not in functions:
        issue = StaticIssue(
            "missing_extended_function",
            f"required extended function {contract.extended_name!r} is not defined",
        )
        return StaticCheckResult(StaticCheckStatus.MISSING_EXTENDED_FUNCTION, False, (issue,))
    if contract.base_name not in _calls_in(functions[contract.extended_name]):
        issue = StaticIssue(
            "missing_dependency",
            f"{contract.extended_name!r} does not explicitly call {contract.base_name!r}",
        )
        return StaticCheckResult(StaticCheckStatus.MISSING_DEPENDENCY, False, (issue,))
    return StaticCheckResult(StaticCheckStatus.PASS, True, ())
