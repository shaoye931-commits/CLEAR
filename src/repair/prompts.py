from __future__ import annotations

import json
from dataclasses import asdict

from src.agents.diagnosis import DiagnosisRecord
from src.analysis.contract import DependencyContract
from src.analysis.trace import TraceResult
from src.config import REFINEMENT_PROMPT_VERSION
from src.models import GenerationTask
from src.repair.targeting import ModificationConstraints


def build_refinement_prompt(
    task: GenerationTask,
    current_code: str,
    diagnosis: DiagnosisRecord,
    constraints: ModificationConstraints,
    contract: DependencyContract,
    trace: TraceResult,
) -> str:
    supporting = set(diagnosis.supporting_call_ids)
    relevant_calls = [
        asdict(call) for call in trace.calls
        if not supporting or call.call_id in supporting
    ]
    payload = {
        "base_function_specification": task.base_problem,
        "extended_function_specification": task.extended_problem,
        "current_candidate": current_code,
        "diagnosis": asdict(diagnosis),
        "modification_constraints": asdict(constraints),
        "test_level_feedback": [asdict(item) for item in trace.test_outcomes],
        "supporting_call_records": relevant_calls,
        "required_dependency": f"{contract.extended_name}->{contract.base_name}",
    }
    return (
        f"Prompt-Version: {REFINEMENT_PROMPT_VERSION}\n"
        "You are CLEAR's code generation agent. Refine the current candidate under the supplied constraints.\n"
        "Modify only the stated targets according to the diagnostic guidance. Preserve every stated target "
        "and every historically frozen function unless the current constraints explicitly require it to change.\n"
        "Keep both required function definitions and the explicit extended-to-base call.\n"
        "Return one complete Python program in exactly one fenced Python code block and no explanation.\n"
        "BEGIN_REFINEMENT\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}\n"
        "END_REFINEMENT"
    )
