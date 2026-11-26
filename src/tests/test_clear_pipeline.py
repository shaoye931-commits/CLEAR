from __future__ import annotations

import unittest

from src.analysis.trace import FunctionCallRecord, PublicTestOutcome, TestExecutionStatus, TraceResult
from src.config import DATRConfig
from src.llm import LLMResponse
from src.models import FunctionMetadata, GenerationTask, TestCase
from src.pipeline import run_clear_task


class ClearPipelineTests(unittest.TestCase):
    def test_algorithm_uses_two_refinements_then_context_reset(self) -> None:
        task = GenerationTask(
            "test",
            7,
            "Implement def base(x): return twice x.",
            "Implement def extended(xs): call base for every value.",
            (FunctionMetadata("base", "base(x)", ("x",)),),
            (FunctionMetadata("extended", "extended(xs)", ("xs",)),),
            (TestCase(1, "assert extended([1]) == [2]"), TestCase(2, "assert extended([]) == []")),
        )
        bad_codes = iter((
            "def base(x):\n    return x + 0\n\ndef extended(xs):\n    return [base(x) for x in xs]\n",
            "def base(x):\n    return x + 1\n\ndef extended(xs):\n    return [base(x) for x in xs]\n",
            "def base(x):\n    return x + 2\n\ndef extended(xs):\n    return [base(x) for x in xs]\n",
        ))
        reset_prompts: list[str] = []
        temperatures: list[float] = []

        def llm(prompt, config):
            temperatures.append(config.temperature)
            if "fault diagnosis agent" in prompt:
                return LLMResponse(
                    '{"fault_category":"UNDETERMINED","supporting_call_ids":[1],'
                    '"explanation":"The evidence does not isolate one source."}',
                    1,
                    1,
                )
            if "Mode: context reset" in prompt:
                reset_prompts.append(prompt)
                return LLMResponse(
                    "```python\ndef base(x):\n    return x * 2\n\ndef extended(xs):\n    return [base(x) for x in xs]\n```",
                    1,
                    1,
                )
            return LLMResponse(f"```python\n{next(bad_codes)}```", 1, 1)

        def trace_collector(task, contract, code, **kwargs):
            passed = "x * 2" in code
            return TraceResult(
                TestExecutionStatus.PASS if passed else TestExecutionStatus.FAIL,
                (PublicTestOutcome(1, "ok" if passed else "fail", None if passed else "AssertionError", None),),
                () if passed else (FunctionCallRecord(1, "base", "[1]", "{}", "ok", "1", None, None),),
            )

        result = run_clear_task(
            task,
            DATRConfig(model_name="mock", run_id="pipeline-test"),
            llm,
            trace_collector=trace_collector,
        )
        self.assertEqual(
            [item.action for item in result.record.iterations],
            ["constrained_refinement", "constrained_refinement", "context_reset", "pass"],
        )
        self.assertEqual(result.sealed_candidate.refinement_iterations, 3)
        self.assertEqual(len(reset_prompts), 1)
        self.assertNotIn("return x + 2", reset_prompts[0])
        self.assertEqual(temperatures[-1], 0.6)
        self.assertEqual(sum(item.diagnosis is not None for item in result.record.iterations), 3)


if __name__ == "__main__":
    unittest.main()
