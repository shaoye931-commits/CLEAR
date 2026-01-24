# 双任务场景的分层故障定位诊断功能
from __future__ import annotations
from typing import Dict, Any, Optional, List
import re
import json
from .prompt_factory import (
    extract_function_name_from_problem,
    extract_function_name_from_test,
    extract_function_body,
    detect_structure_errors,
    is_similar_name,
)
from .agents.diagnosis_agent import DiagnosisAgent
from .config import DeepSeekConfig, ExperimentConfig, load_environment
from .deepseek_client import DeepSeekClient
from .llm_handler import generate_code

load_environment()
_deepseek_client = DeepSeekClient(DeepSeekConfig.from_env())
_experiment_config = ExperimentConfig.from_env()
diagnosis_agent = DiagnosisAgent(
    client=_deepseek_client,
    model=_experiment_config.model_to_test,
)


TYPE_SIGNATURES: Dict[str, Dict[str, Any]] = {
    "set": {
        "python_type": "set",
        "test_patterns": [
            r"==\s*set\(",
            r"isinstance\([^,]+,\s*set\)",
            r"\bset\(",
        ],
        "desc_keywords": [
            "return a set",
            "as a set",
            "set of",
            "集合",
        ],
    },
    "list": {
        "python_type": "list",
        "test_patterns": [
            r"\[[^\]]*\]",
            r"isinstance\([^,]+,\s*list\)",
        ],
        "desc_keywords": [
            "return a list",
            "list of",
            "列表",
        ],
    },
    "tuple": {
        "python_type": "tuple",
        "test_patterns": [
            r"\(\s*[^\(\)]+\s*,\s*[^\(\)]+\s*\)",
            r"isinstance\([^,]+,\s*tuple\)",
        ],
        "desc_keywords": [
            "return a tuple",
            "tuple of",
        ],
    },
    "dict": {
        "python_type": "dict",
        "test_patterns": [
            r"isinstance\([^,]+,\s*dict\)",
            r"\{[^:]+:[^}]+\}",
        ],
        "desc_keywords": [
            "return a dictionary",
            "mapping",
            "键值对",
        ],
    },
    "str": {
        "python_type": "str",
        "test_patterns": [
            r"isinstance\([^,]+,\s*str\)",
            r"\"[^\"]*\"",
            r"'[^']*'",
        ],
        "desc_keywords": [
            "return a string",
            "as text",
            "字符串",
        ],
    },
    "bool": {
        "python_type": "bool",
        "test_patterns": [
            r"isinstance\([^,]+,\s*bool\)",
            r"==\s*(True|False)",
        ],
        "desc_keywords": [
            "return true or false",
            "boolean",
            "布尔",
        ],
    },
}


def _extract_actual_return_type(execution_trace: List[Dict[str, Any]]) -> Optional[str]:
    """
    从执行追踪中提取主函数的实际返回类型。
    兼容多种可能的字段（function/tag/is_main_return）。
    """
    if not execution_trace:
        return None

    for record in execution_trace:
        if not isinstance(record, dict):
            continue

        is_main_record = False
        if record.get("function") == "main":
            is_main_record = True
        if record.get("tag") == "main_return":
            is_main_record = True
        if record.get("is_main_return"):
            is_main_record = True

        if not is_main_record:
            continue

        # 优先使用显式记录的类型
        explicit_type = record.get("python_type") or record.get("return_type") or record.get("output_type")
        if explicit_type:
            return str(explicit_type)

        if "output" in record:
            value = record.get("output")
            return type(value).__name__ if value is not None else "NoneType"

    return None


def detect_return_type_mismatch(
    execution_trace: List[Dict[str, Any]],
    failed_test_code: str,
    problem_description: str,
) -> Optional[Dict[str, Any]]:
    """
    基于执行追踪和测试/题目描述，检测返回类型不匹配。
    """
    actual_type = _extract_actual_return_type(execution_trace)
    if not actual_type:
        return None

    expected_type = None
    evidence: List[str] = []
    tests_text = failed_test_code or ""
    desc_text = (problem_description or "").lower()

    for signature in TYPE_SIGNATURES.values():
        py_type = signature.get("python_type")
        matched = False

        for pattern in signature.get("test_patterns", []):
            if not pattern:
                continue
            if tests_text and re.search(pattern, tests_text, re.IGNORECASE):
                expected_type = py_type
                evidence.append(f"Matched test pattern `{pattern}`")
                matched = True
                break

        if matched:
            break

        for keyword in signature.get("desc_keywords", []):
            if not keyword:
                continue
            if keyword.lower() in desc_text:
                expected_type = py_type
                evidence.append(f"Found description keyword \"{keyword}\"")
                matched = True
                break

        if matched:
            break

    if expected_type and actual_type != expected_type:
        return {
            "actual_type": actual_type,
            "expected_type": expected_type,
            "evidence": evidence,
        }

    return None


def verify_helper_contract(
    helper_code: str,
    helper_trace: List[Dict[str, Any]],
    raw_problem: str,
) -> Dict[str, Any]:
    """
    验证辅助函数的实际 I/O 是否符合 raw_problem 的描述。
    使用 LLM 判断 Helper 的实际行为是否符合规范。
    
    Args:
        helper_code: 辅助函数的代码
        helper_trace: 执行追踪记录列表，格式为 [{"input": {...}, "output": ..., "error": ...}, ...]
        raw_problem: 辅助函数的原始问题描述
    
    Returns:
        {
            "is_valid": bool,
            "violations": List[Dict],  # 违反契约的具体案例
            "analysis": str,  # LLM的分析结果
        }
    """
    if not helper_trace:
        return {
            "is_valid": False,
            "violations": [],
            "analysis": "No execution trace found. Helper function may not have been called.",
        }
    
    # 过滤出有效的追踪记录（排除错误记录）
    valid_traces = [
        trace for trace in helper_trace
        if "error" not in trace or trace.get("error") is None
    ]
    
    if not valid_traces:
        return {
            "is_valid": False,
            "violations": [],
            "analysis": "All helper function calls resulted in errors. Cannot verify contract.",
        }
    
    # 构建验证提示词（最多5个示例）
    trace_examples = []
    for trace_data in valid_traces[:5]:
        trace_examples.append({
            "input": trace_data.get("input", {}),
            "output": trace_data.get("output"),
        })
    
    verification_prompt = f"""
You are a code contract verifier. Your task is to check if a helper function's behavior matches its specification.

## Helper Function Specification (Raw Problem)

{raw_problem}

## Helper Function Implementation

```python
{helper_code}
```

## Actual Execution Trace

The helper function was called with the following inputs and produced these outputs:

{json.dumps(trace_examples, indent=2)}

## Your Task

Analyze whether the helper function's actual behavior matches the specification.

For each trace entry:
1. What should the function return for the given input according to the specification?
2. What did it actually return?
3. Are they consistent?

Output JSON only:
{{
    "is_valid": true/false,
    "violations": [
        {{
            "input": "...",
            "expected_output": "...",
            "actual_output": "...",
            "reason": "Brief explanation"
        }}
    ],
    "analysis": "Overall analysis of the helper function's correctness"
}}
"""
    
    try:
        response = generate_code(verification_prompt, use_cot=False)
        response_text = response.get("raw_response", "") or response.get("code", "")
        
        # 尝试提取JSON
        json_match = re.search(r'\{[^{}]*"is_valid"[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            return {
                "is_valid": result.get("is_valid", False),
                "violations": result.get("violations", []),
                "analysis": result.get("analysis", ""),
            }
        
        # 如果无法解析JSON，进行简单判断
        if "is_valid" in response_text.lower() and "true" in response_text.lower():
            return {
                "is_valid": True,
                "violations": [],
                "analysis": response_text,
            }
        else:
            return {
                "is_valid": False,
                "violations": [],
                "analysis": response_text,
            }
    except Exception as e:
        return {
            "is_valid": False,
            "violations": [],
            "analysis": f"Verification failed: {str(e)}",
        }


def hierarchical_diagnosis(
    failure_output: str,
    exit_code: int,
    code: str,
    helper_name: str,
    main_name: str,
    execution_trace: List[Dict[str, Any]],
    raw_problem: str,
    task_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    分层故障定位：先验证辅助函数契约，再定位主函数问题。
    
    Returns:
        diagnostics dict with:
        - fault_location: "helper" | "main" | "unknown"
        - helper_contract_valid: bool
        - helper_violations: List[Dict]
        - targeted_repair_strategy: "helper_only" | "main_only"
    """
    diagnostics = {
        "error_type": "AssertionError",
        "error_category": "logic",
        "fault_location": "unknown",
        "helper_contract_valid": None,
        "helper_violations": [],
        "targeted_repair_strategy": None,
        "helper_function_name": helper_name,
        "main_function_name": main_name,
        "failed_assert": None,
        "actual_output": None,
        "expected_output": None,
        "error_message": failure_output,
        "analysis": "",
    }
    
    # 提取失败信息
    expected_match = re.search(r"expected[:\s]+([^\n,]+)", failure_output, re.IGNORECASE)
    actual_match = re.search(r"(?:got|actual)[:\s]+([^\n,]+)", failure_output, re.IGNORECASE)
    assert_match = re.search(r"assert\s+([^\n]+)", failure_output)
    
    if expected_match:
        diagnostics["expected_output"] = expected_match.group(1).strip().strip("'\"")
    if actual_match:
        diagnostics["actual_output"] = actual_match.group(1).strip().strip("'\"")
    if assert_match:
        diagnostics["failed_assert"] = assert_match.group(1).strip()
    
    # 步骤1：检查结构性错误
    structure_error = detect_structure_errors(code, helper_name, main_name)
    if structure_error:
        diagnostics.update(structure_error)
        diagnostics["fault_location"] = structure_error.get("error_location", "unknown")
        return diagnostics
    
    # 步骤2：分层诊断 - 先验证辅助函数契约
    helper_body = extract_function_body(code, helper_name)
    if helper_body and execution_trace:
        contract_result = verify_helper_contract(helper_body, execution_trace, raw_problem)
        diagnostics["helper_contract_valid"] = contract_result["is_valid"]
        diagnostics["helper_violations"] = contract_result.get("violations", [])
        diagnostics["contract_verification_result"] = contract_result
        
        if not contract_result["is_valid"]:
            # 情况A：辅助函数违反契约
            diagnostics["fault_location"] = "helper"
            diagnostics["error_type"] = "AssertionError_Helper"
            diagnostics["targeted_repair_strategy"] = "helper_only"
            diagnostics["analysis"] = (
                f"🔍 Hierarchical Diagnosis: Helper function `{helper_name}` violates its contract.\n"
                f"Contract violations:\n"
            )
            for violation in contract_result.get("violations", []):
                diagnostics["analysis"] += (
                    f"  - Input: {violation.get('input')} → "
                    f"Expected: {violation.get('expected_output')}, "
                    f"Got: {violation.get('actual_output')}\n"
                )
            diagnostics["analysis"] += contract_result.get("analysis", "")
            return diagnostics
    
    # 步骤3：辅助函数契约通过，问题在主函数
    diagnostics["fault_location"] = "main"
    diagnostics["error_type"] = "AssertionError_Main"
    diagnostics["targeted_repair_strategy"] = "main_only"
    diagnostics["helper_contract_valid"] = True
    # 如果没有执行追踪，创建一个空的验证结果
    if not diagnostics.get("contract_verification_result"):
        diagnostics["contract_verification_result"] = {
            "is_valid": True,
            "violations": [],
            "analysis": "Helper function contract verified (no trace available, assuming valid)."
        }
    diagnostics["analysis"] = (
        f"🔍 Hierarchical Diagnosis: Helper function `{helper_name}` contract is valid.\n"
        f"The error is in the main function `{main_name}` logic or how it uses the helper's results."
    )
    
    return diagnostics


def analyze_name_error_dual_task(
    failure_output: str,
    code: str,
    helper_name: str,
    main_name: str,
) -> Dict[str, Any]:
    """
    分析NameError，特别检测辅助函数名拼写错误。
    """
    result = {
        "error_type": "NameError",
        "error_category": "runtime",
        "fault_location": "unknown",
        "analysis": "",
    }
    
    # 提取未定义的名称
    undefined_match = re.search(r"name '([^']+)' is not defined", failure_output)
    if not undefined_match:
        return result
    
    undefined_name = undefined_match.group(1)
    
    # 检查是否是辅助函数名的拼写错误
    if is_similar_name(undefined_name, helper_name):
        result["fault_location"] = "main"
        result["error_type"] = "NameError_HelperTypo"
        result["analysis"] = (
            f"🔤 Typo Detected!\n\n"
            f"You tried to call: `{undefined_name}`\n"
            f"But the helper function is: `{helper_name}`\n\n"
            f"This is a spelling mistake. Fix: Change `{undefined_name}` to `{helper_name}`"
        )
        return result
    
    # 从Traceback中提取出错位置
    traceback_match = re.search(rf'File "[^"]+", line (\d+), in (\w+)', failure_output)
    if traceback_match:
        error_function = traceback_match.group(2)
        
        if error_function == helper_name:
            result["fault_location"] = "helper"
            result["error_type"] = "NameError_Helper"
            result["analysis"] = f"`{undefined_name}` is not defined in `{helper_name}`."
        elif error_function == main_name:
            result["fault_location"] = "main"
            result["error_type"] = "NameError_Main"
            result["analysis"] = f"`{undefined_name}` is not defined in `{main_name}`."
    
    return result


def parse_error_diagnostics_enhanced(
    failure_output: str,
    exit_code: int,
    code: str,
    helper_name: str,
    main_name: str,
    execution_trace: List[Dict[str, Any]],
    raw_problem: str,
    task_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    增强版错误诊断，基于执行追踪的分层故障定位。
    强制双任务场景，移除所有单任务兼容逻辑。
    
    Args:
        failure_output: 测试失败的stderr输出
        exit_code: 进程退出码
        code: LLM生成的完整代码
        helper_name: 辅助函数名（必须提供）
        main_name: 主函数名（必须提供）
        execution_trace: 执行追踪记录
        raw_problem: 辅助函数的原始问题描述
        task_context: 任务上下文
    
    Returns:
        包含详细诊断信息的字典
    """
    diagnostics = {
        "error_type": "Unknown",
        "error_category": "unknown",
        "fault_location": "unknown",
        "helper_function_name": helper_name,
        "main_function_name": main_name,
        "failed_assert": None,
        "actual_output": None,
        "expected_output": None,
        "error_message": failure_output,
        "traceback_line": None,
        "analysis": "",
        "helper_contract_valid": None,
        "helper_violations": [],
        "targeted_repair_strategy": None,
        "contract_verification_result": None,
    }
    
    if not failure_output:
        return diagnostics

    # 准备辅助文本信息（测试用例/题目描述）
    tests_text = ""
    if task_context:
        tests_source = task_context.get("tests_source")
        if isinstance(tests_source, str):
            tests_text = tests_source
        elif isinstance(task_context.get("test_list"), list):
            tests_text = "\n".join(task_context.get("test_list", []))
    problem_description = ""
    if task_context:
        problem_description = task_context.get("prompt") or task_context.get("new_problem") or ""

    # 类型不匹配检测（若有输出则记录，供提示词使用）
    type_mismatch = detect_return_type_mismatch(execution_trace, tests_text, problem_description)
    if type_mismatch:
        diagnostics["type_mismatch"] = type_mismatch
    
    # 步骤1：检测结构性错误
    structure_error = detect_structure_errors(code, helper_name, main_name)
    if structure_error:
        diagnostics.update(structure_error)
        diagnostics["fault_location"] = structure_error.get("error_location", "unknown")
        return diagnostics
    
    # 步骤2：检测超时错误
    if "TIMEOUT" in failure_output or exit_code == 124:
        diagnostics["error_type"] = "TimeoutError"
        diagnostics["error_category"] = "performance"
        diagnostics["fault_location"] = "overall"
        return diagnostics
    
    # 步骤3：检测AssertionError - 使用分层诊断
    if "AssertionError" in failure_output:
        hierarchical_result = hierarchical_diagnosis(
            failure_output,
            exit_code,
            code,
            helper_name,
            main_name,
            execution_trace,
            raw_problem,
            task_context,
        )
        diagnostics.update(hierarchical_result)
        
        # 如果诊断代理可用，获取额外分析
        actual_output = hierarchical_result.get("actual_output")
        expected_output = hierarchical_result.get("expected_output")
        failed_assert = hierarchical_result.get("failed_assert")
        if (
            actual_output is not None
            and expected_output is not None
            and diagnosis_agent is not None
        ):
            agent_payload = {
                "failed_assert": failed_assert,
                "actual_output": actual_output,
                "expected_output": expected_output,
                "helper_function": helper_name,
                "main_function": main_name,
                "fault_location": hierarchical_result.get("fault_location"),
            }
            try:
                agent_result = diagnosis_agent.diagnose(
                    task_context or {},
                    code,
                    failure_output,
                    agent_payload,
                )
            except Exception:
                agent_result = None
            if agent_result:
                diagnostics["agent_analysis"] = agent_result
                diagnostics["root_cause"] = agent_result.get("root_cause")
                diagnostics["fix_suggestion"] = agent_result.get("fix_suggestion")
        
        return diagnostics
    
    # 步骤4：检测NameError
    if "NameError:" in failure_output:
        name_error_info = analyze_name_error_dual_task(
            failure_output, code, helper_name, main_name
        )
        diagnostics.update(name_error_info)
        return diagnostics
    
    # 步骤5：检测TypeError
    if "TypeError:" in failure_output:
        diagnostics["error_type"] = "TypeError"
        diagnostics["error_category"] = "runtime"
        diagnostics["fault_location"] = "unknown"
        return diagnostics
    
    # 步骤6：检测SyntaxError
    if "SyntaxError:" in failure_output:
        diagnostics["error_type"] = "SyntaxError"
        diagnostics["error_category"] = "syntax"
        diagnostics["fault_location"] = "unknown"
        return diagnostics
    
    # 步骤7：其他错误类型
    if "Error:" in failure_output or "Traceback" in failure_output:
        error_match = re.search(r"(\w+Error):", failure_output)
        if error_match:
            diagnostics["error_type"] = error_match.group(1)
        else:
            diagnostics["error_type"] = "RuntimeError"
        diagnostics["error_category"] = "runtime"
        diagnostics["fault_location"] = "unknown"
    
    return diagnostics
