from __future__ import annotations

import re
import unittest

from src.agents.diagnosis import DiagnosisRecord, FaultCategory, build_diagnosis_prompt
from src.agents.generation import build_generation_prompt
from src.analysis.ast_checks import StaticCheckStatus, check_candidate
from src.analysis.contract import build_dependency_contract
from src.analysis.trace import FunctionCallRecord, PublicTestOutcome, TestExecutionStatus, TraceResult
from src.models import FunctionMetadata, GenerationTask, TestCase
from src.repair.prompts import build_refinement_prompt
from src.repair.targeting import build_constraints, update_frozen_functions


def task() -> GenerationTask:
    return GenerationTask(
        "test",
        1,
        "Implement def base(x): return twice x.",
        "Implement def extended(xs): call base for every value.",
        (FunctionMetadata("base", "base(x)", ("x",)),),
        (FunctionMetadata("extended", "extended(xs)", ("xs",)),),
        (TestCase(1, "assert extended([1]) == [2]"), TestCase(2, "assert extended([]) == []")),
    )


class ClearCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = task()
        self.contract = build_dependency_contract(self.task).contract
        assert self.contract is not None

    def test_ast_check_matches_paper_equation(self) -> None:
        valid = "def base(x):\n    return x * 2\n\ndef extended(xs):\n    return [base(x) for x in xs]\n"
        self.assertTrue(check_candidate(valid, self.contract).passed)
        missing_call = valid.replace("return [base(x) for x in xs]", "return [x * 2 for x in xs]")
        result = check_candidate(missing_call, self.contract)
        self.assertEqual(result.status, StaticCheckStatus.MISSING_DEPENDENCY)
        syntax = check_candidate("def base(:", self.contract)
        self.assertEqual(syntax.status, StaticCheckStatus.SYNTAX_ERROR)

    def test_initial_prompt_is_english_and_hides_public_tests(self) -> None:
        prompt = build_generation_prompt(self.task, self.contract)
        self.assertNotIn("assert extended", prompt)
        self.assertNotRegex(prompt, re.compile(r"[\u4e00-\u9fff]"))
        self.assertIn("explicitly call the base function", prompt)

    def test_diagnosis_and_refinement_prompts_are_english(self) -> None:
        trace = TraceResult(
            TestExecutionStatus.FAIL,
            (PublicTestOutcome(1, "fail", "AssertionError", ""),),
            (FunctionCallRecord(1, "base", "[1]", "{}", "ok", "0", None, None),),
        )
        diagnosis = DiagnosisRecord(FaultCategory.BASE, (1,), "The observed output is inconsistent.")
        frozen = update_frozen_functions(set(), diagnosis, self.contract)
        constraints = build_constraints(diagnosis, self.contract, frozen)
        diagnosis_prompt = build_diagnosis_prompt(
            self.task,
            self.contract,
            "def base(x): return 0\ndef extended(xs): return [base(x) for x in xs]",
            trace,
        )
        refinement_prompt = build_refinement_prompt(
            self.task,
            "def base(x): return 0\ndef extended(xs): return [base(x) for x in xs]",
            diagnosis,
            constraints,
            self.contract,
            trace,
        )
        self.assertNotRegex(diagnosis_prompt + refinement_prompt, re.compile(r"[\u4e00-\u9fff]"))
        self.assertEqual(constraints.modification_targets, ("base",))
        self.assertEqual(constraints.preservation_targets, ("extended",))

    def test_constraint_mapping_covers_all_four_categories(self) -> None:
        expected = {
            FaultCategory.BASE: (("base",), ("extended",)),
            FaultCategory.CALL: (("call sites extended->base", "interface definitions"), ("unrelated function logic",)),
            FaultCategory.EXT: (("extended",), ("base",)),
            FaultCategory.UNDETERMINED: (("base", "extended"), ()),
        }
        for category, (modified, preserved) in expected.items():
            with self.subTest(category=category):
                diagnosis = DiagnosisRecord(category, (), "guidance")
                constraints = build_constraints(diagnosis, self.contract, set())
                self.assertEqual(constraints.modification_targets, modified)
                self.assertEqual(constraints.preservation_targets, preserved)

    def test_contract_uses_final_declared_functions_after_helpers(self) -> None:
        helper_task = GenerationTask(
            "test",
            2,
            "def helper(x): pass\ndef base(x): pass",
            "def other(x): pass\ndef extended(xs): pass",
            (
                FunctionMetadata("helper", "helper(x)", ("x",)),
                FunctionMetadata("base", "base(x)", ("x",)),
            ),
            (
                FunctionMetadata("other", "other(x)", ("x",)),
                FunctionMetadata("extended", "extended(xs)", ("xs",)),
            ),
            (TestCase(1, "assert extended([]) == []"),),
        )
        contract = build_dependency_contract(helper_task).contract
        self.assertIsNotNone(contract)
        self.assertEqual(contract.dependency, ("extended", "base"))


if __name__ == "__main__":
    unittest.main()
