from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis.contract import build_dependency_contract
from src.analysis.trace import TestExecutionStatus, _DRIVER, collect_public_trace
from src.data import load_evaluation_dataset, load_generation_dataset
from src.reuse import DockerArtifactResult, SandboxResult


class DataAndTraceTests(unittest.TestCase):
    def test_first_two_tests_are_public_and_rest_are_held_out(self) -> None:
        row = {
            "id": 1,
            "raw_problem": "def base(x):\n    \"\"\"Return x.\"\"\"",
            "new_problem": "def extended(x):\n    \"\"\"Return base(x).\"\"\"",
            "test_code": "\n".join(f"assert extended({i}) == {i}" for i in range(4)),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps([row]), encoding="utf-8")
            generation = load_generation_dataset(path, "test")
            evaluation = load_evaluation_dataset(path, "test")
        self.assertEqual([item.ordinal for item in generation.tasks[0].public_tests], [1, 2])
        self.assertEqual([item.ordinal for item in evaluation.tasks[0].held_out_tests], [3, 4])
        self.assertEqual(generation.report.public_tests, 2)
        self.assertEqual(generation.report.held_out_tests, 2)

    def test_trace_combines_both_public_tests_and_offsets_call_ids(self) -> None:
        row = {
            "id": 1,
            "raw_problem": "def base(x):\n    \"\"\"Return x.\"\"\"",
            "new_problem": "def extended(x):\n    \"\"\"Return base(x).\"\"\"",
            "test_code": "assert extended(1) == 1\nassert extended(2) == 2",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps([row]), encoding="utf-8")
            task = load_generation_dataset(path, "test").tasks[0]
        contract = build_dependency_contract(task).contract
        assert contract is not None
        artifacts = [
            json.dumps({
                "version": 1,
                "execution_status": "ok",
                "error_type": None,
                "error_summary": None,
                "calls": [{
                    "call_id": 1, "function_name": "base", "args_summary": "[1]",
                    "kwargs_summary": "{}", "status": "ok", "output_summary": "1",
                    "error_type": None, "error_summary": None,
                }],
            }),
            json.dumps({
                "version": 1,
                "execution_status": "ok",
                "error_type": None,
                "error_summary": None,
                "calls": [{
                    "call_id": 1, "function_name": "base", "args_summary": "[2]",
                    "kwargs_summary": "{}", "status": "ok", "output_summary": "2",
                    "error_type": None, "error_summary": None,
                }],
            }),
        ]
        side_effect = [
            DockerArtifactResult(SandboxResult(True, "", "", 0), artifact)
            for artifact in artifacts
        ]
        with mock.patch(
            "src.analysis.trace.run_untrusted_python_with_artifact",
            side_effect=side_effect,
        ) as runner:
            trace = collect_public_trace(
                task,
                contract,
                "def base(x): return x\ndef extended(x): return base(x)",
            )
        self.assertEqual(trace.execution_status, TestExecutionStatus.PASS)
        self.assertEqual([item.call_id for item in trace.calls], [1, 2])
        self.assertEqual(runner.call_count, 2)

    def test_proxy_assigns_call_id_before_invocation(self) -> None:
        template = _DRIVER.template
        self.assertLess(template.index("_next_call_id += 1"), template.index("_original(*args"))
        self.assertLess(template.index("_original(*args"), template.index("_calls.append"))

    def test_public_timeout_is_failure_feedback_not_infrastructure_error(self) -> None:
        row = {
            "id": 1,
            "raw_problem": "def base(x):\n    pass",
            "new_problem": "def extended(x):\n    pass",
            "test_code": "assert extended(1) == 1",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps([row]), encoding="utf-8")
            task = load_generation_dataset(path, "test").tasks[0]
        contract = build_dependency_contract(task).contract
        assert contract is not None
        timed_out = DockerArtifactResult(SandboxResult(False, "", "", 124), None)
        with mock.patch(
            "src.analysis.trace.run_untrusted_python_with_artifact",
            return_value=timed_out,
        ):
            trace = collect_public_trace(
                task,
                contract,
                "def base(x): return x\ndef extended(x): return base(x)",
            )
        self.assertEqual(trace.execution_status, TestExecutionStatus.FAIL)
        self.assertEqual(trace.test_outcomes[0].error_type, "TimeoutError")


if __name__ == "__main__":
    unittest.main()
