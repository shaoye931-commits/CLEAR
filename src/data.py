from __future__ import annotations

import ast
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.models import (
    DatasetReport,
    EvaluationDataset,
    EvaluationTask,
    FunctionMetadata,
    GenerationDataset,
    GenerationTask,
    TaskId,
    TestCase,
)


_FUNCTION_RE = re.compile(
    r"(?ms)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(?:->\s*[^:\n]+)?\s*:"
)


@dataclass(frozen=True)
class _ParsedTask:
    task_id: TaskId
    base_problem: str | None
    extended_problem: str
    base_functions: tuple[FunctionMetadata, ...]
    extended_functions: tuple[FunctionMetadata, ...]
    tests: tuple[TestCase, ...]


def _source_for_node(source: str, node: ast.AST) -> str:
    lines = source.splitlines(keepends=True)
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    return "".join(lines[start:end]).strip()


def _is_test_statement(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    return any(isinstance(child, ast.Assert) for child in ast.walk(node))


def extract_tests(test_code: str) -> tuple[TestCase, ...]:
    """Extract complete top-level test statements in original source order."""
    tree = ast.parse(test_code)
    setup_nodes: list[ast.stmt] = []
    tests: list[TestCase] = []
    for node in tree.body:
        if _is_test_statement(node):
            setup = "\n\n".join(_source_for_node(test_code, item) for item in setup_nodes)
            tests.append(
                TestCase(
                    ordinal=len(tests) + 1,
                    source=_source_for_node(test_code, node),
                    setup_code=setup,
                )
            )
        else:
            setup_nodes.append(node)
    return tuple(tests)


def extract_function_metadata(problem: str | None) -> tuple[FunctionMetadata, ...]:
    if not problem:
        return ()
    functions: list[FunctionMetadata] = []
    for match in _FUNCTION_RE.finditer(problem):
        name, parameters = match.groups()
        raw_parameters = parameters.strip()
        positional: tuple[str, ...] = ()
        try:
            synthetic = ast.parse(f"def {name}({raw_parameters}):\n    pass\n")
            args = synthetic.body[0].args  # type: ignore[union-attr]
            positional = tuple(arg.arg for arg in (*args.posonlyargs, *args.args))
        except SyntaxError:
            pass
        functions.append(
            FunctionMetadata(
                name=name,
                signature=f"{name}({raw_parameters})",
                positional_parameters=positional,
            )
        )
    return tuple(functions)


def _read_rows(path: Path) -> list[object]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Dataset must be a JSON array: {path}")
    return data


def _parse_dataset(path: Path, dataset: str) -> tuple[DatasetReport, tuple[_ParsedTask, ...]]:
    rows = _read_rows(path)
    filtered: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    parsed: list[_ParsedTask] = []
    seen_ids: set[TaskId] = set()

    for row in rows:
        if not isinstance(row, dict):
            filtered["row_not_object"] += 1
            continue
        task_id = row.get("id")
        if not isinstance(task_id, (int, str)) or isinstance(task_id, bool):
            filtered["missing_or_invalid_id"] += 1
            continue
        if task_id in seen_ids:
            filtered["duplicate_id"] += 1
            continue
        seen_ids.add(task_id)

        extended_problem = str(row.get("new_problem", "")).strip()
        if not extended_problem:
            filtered["missing_extended_problem"] += 1
            continue
        test_code = row.get("test_code")
        if not isinstance(test_code, str) or not test_code.strip():
            filtered["missing_test_code"] += 1
            continue
        try:
            tests = extract_tests(test_code)
        except SyntaxError:
            filtered["invalid_test_syntax"] += 1
            continue
        if not tests:
            filtered["no_recognized_tests"] += 1
            continue
        if len(tests) < 3:
            issues["insufficient_tests_for_two_public_and_held_out"] += 1

        base_problem_value = row.get("raw_problem")
        base_problem = str(base_problem_value).strip() if base_problem_value else None
        if base_problem is None:
            issues["missing_base_problem"] += 1
        base_functions = extract_function_metadata(base_problem)
        extended_functions = extract_function_metadata(extended_problem)
        if base_problem and not base_functions:
            issues["missing_base_function_declaration"] += 1
        if not extended_functions:
            issues["missing_extended_function_declaration"] += 1
        if len(base_functions) > 1:
            issues["multiple_base_function_declarations"] += 1
        if len(extended_functions) > 1:
            issues["multiple_extended_function_declarations"] += 1
        issues["structured_test_statements"] += sum(
            not test.source.lstrip().startswith("assert") for test in tests
        )
        issues["multiline_test_statements"] += sum("\n" in test.source for test in tests)

        parsed.append(
            _ParsedTask(
                task_id=task_id,
                base_problem=base_problem,
                extended_problem=extended_problem,
                base_functions=base_functions,
                extended_functions=extended_functions,
                tests=tests,
            )
        )

    total_tests = sum(len(task.tests) for task in parsed)
    public_test_count = sum(min(2, len(task.tests)) for task in parsed)
    report = DatasetReport(
        dataset=dataset,
        source_path=path.resolve(),
        original_count=len(rows),
        valid_count=len(parsed),
        filtered_reasons=dict(sorted(filtered.items())),
        issues={key: value for key, value in sorted(issues.items()) if value},
        total_tests=total_tests,
        public_tests=public_test_count,
        held_out_tests=total_tests - public_test_count,
    )
    return report, tuple(parsed)


def load_generation_dataset(path: Path, dataset: str) -> GenerationDataset:
    """Return specifications and the first two tests, as required by CLEAR."""
    report, parsed = _parse_dataset(path, dataset)
    tasks = tuple(
        GenerationTask(
            dataset=dataset,
            task_id=task.task_id,
            base_problem=task.base_problem,
            extended_problem=task.extended_problem,
            base_functions=task.base_functions,
            extended_functions=task.extended_functions,
            public_tests=task.tests[:2],
        )
        for task in parsed
    )
    return GenerationDataset(report=report, tasks=tasks)


def load_evaluation_dataset(path: Path, dataset: str) -> EvaluationDataset:
    """Explicit final-evaluation view containing only held-out tests."""
    report, parsed = _parse_dataset(path, dataset)
    tasks = tuple(
        EvaluationTask(
            dataset=dataset,
            task_id=task.task_id,
            held_out_tests=task.tests[2:],
        )
        for task in parsed
    )
    return EvaluationDataset(report=report, tasks=tasks)


def load_evaluation_task(path: Path, dataset: str, task_id: TaskId) -> EvaluationTask:
    """Load the held-out view for one completed task only."""
    _, parsed = _parse_dataset(path, dataset)
    task = next((item for item in parsed if str(item.task_id) == str(task_id)), None)
    if task is None:
        raise ValueError(f"evaluation task not found: {task_id}")
    return EvaluationTask(dataset, task.task_id, task.tests[2:])
