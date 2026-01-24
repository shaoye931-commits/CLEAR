from __future__ import annotations
from textwrap import dedent
import re  # 引入正则表达式库，以便在函数内部进行智能分析
from typing import List, Dict, Any, Optional
from difflib import SequenceMatcher


def _ensure_typing_imports(code: str) -> str:
    """
    检查代码中是否使用了 typing 类型注解，如果使用了但没有导入，自动添加导入语句。
    
    Args:
        code: 原始代码字符串
        
    Returns:
        添加了必要 import 的代码字符串
    """
    # 检查是否已经有 typing import
    has_typing_import = re.search(r'from\s+typing\s+import', code, re.IGNORECASE)
    
    if has_typing_import:
        # 已经有 import，不需要添加
        return code
    
    # 检查代码中使用了哪些 typing 类型
    typing_types = {
        'List', 'Dict', 'Tuple', 'Set', 'Optional', 'Union', 
        'Any', 'Callable', 'Iterable', 'Iterator', 'Sequence'
    }
    
    used_types = set()
    for typing_type in typing_types:
        # 检查是否在类型注解中使用（如 List[...], Dict[...] 等）
        if re.search(rf'\b{typing_type}\[', code):
            used_types.add(typing_type)
    
    if not used_types:
        # 没有使用 typing 类型，不需要添加 import
        return code
    
    # 生成 import 语句
    imports_str = ', '.join(sorted(used_types))
    import_line = f"from typing import {imports_str}\n"
    
    # 找到第一个非注释、非空行的位置
    lines = code.split('\n')
    insert_pos = 0
    
    # 跳过开头的注释和空行
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            insert_pos = i
            break
    
    # 在第一个非注释行之前插入 import
    lines.insert(insert_pos, import_line)
    return '\n'.join(lines)


def extract_function_name_from_test(test_str: str) -> str | None:
    """
    从测试用例中提取函数名。
    例如：从 "assert function_name(...) == ..." 中提取 "function_name"
    """
    if not test_str:
        return None
    
    # 尝试匹配 assert 语句中的函数调用
    match = re.search(r"assert\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", test_str)
    if match:
        return match.group(1)
    
    # 如果没有匹配到，尝试匹配赋值语句
    match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\(", test_str)
    if match:
        return match.group(1)
    
    return None


def extract_function_name_from_problem(problem_text: str) -> Optional[str]:
    """
    从问题描述中提取函数名。
    常见模式："Write a function `func_name` that..." 或 "def func_name(...):"
    """
    if not problem_text:
        return None
    
    # 模式1: `func_name`
    match = re.search(r'`(\w+)`', problem_text)
    if match:
        return match.group(1)
    
    # 模式2: def func_name(
    match = re.search(r'def\s+(\w+)\s*\(', problem_text)
    if match:
        return match.group(1)
    
    # 模式3: function func_name
    match = re.search(r'function\s+(\w+)', problem_text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None


def extract_function_body(code: str, function_name: str) -> Optional[str]:
    """
    提取指定函数的完整代码（包括函数头和函数体）。
    """
    if not code or not function_name:
        return None
    
    # 匹配 def function_name(...): 开始到下一个非缩进行或文件结束
    pattern = rf"(def\s+{re.escape(function_name)}\s*\([^)]*\):[^\n]*\n(?:\s+[^\n]*\n)*)"
    match = re.search(pattern, code)
    if match:
        return match.group(1)
    return None


def is_similar_name(name1: str, name2: str, threshold: float = 0.7) -> bool:
    """
    检查两个名称是否相似（用于拼写错误检测）。
    """
    if not name1 or not name2:
        return False
    ratio = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
    return ratio >= threshold


def estimate_code_complexity(code: Optional[str]) -> int:
    """
    估算代码复杂度（简单的启发式方法）。
    """
    if not code:
        return 0
    
    complexity = 0
    # 控制流语句增加复杂度
    complexity += len(re.findall(r'\bif\b', code)) * 2
    complexity += len(re.findall(r'\bfor\b', code)) * 3
    complexity += len(re.findall(r'\bwhile\b', code)) * 3
    complexity += len(re.findall(r'\belif\b', code)) * 1
    complexity += len(re.findall(r'\belse\b', code)) * 1
    complexity += len(re.findall(r'\btry\b', code)) * 2
    
    # 代码行数（非空非注释）
    lines = [l.strip() for l in code.split('\n') if l.strip() and not l.strip().startswith('#')]
    complexity += len(lines)
    
    return complexity


def detect_structure_errors(code: str, helper_name: Optional[str], main_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    检测双任务代码的结构性问题（缺少函数、未调用辅助函数等）。
    """
    if not helper_name or not main_name:
        return None
    
    # 检查1：是否缺少辅助函数
    helper_pattern = rf"def\s+{re.escape(helper_name)}\s*\("
    if not re.search(helper_pattern, code):
        return {
            "error_type": "MissingHelperFunction",
            "error_category": "structure",
            "error_location": "helper",
            "analysis": (
                f"❌ Critical Error: The helper function `{helper_name}` is not defined.\n"
                f"This is a dual-task problem requiring both functions.\n"
                f"You must implement:\n"
                f"  1. Helper function: {helper_name}(...)\n"
                f"  2. Main function: {main_name}(...)"
            )
        }
    
    # 检查2：是否缺少主函数
    main_pattern = rf"def\s+{re.escape(main_name)}\s*\("
    if not re.search(main_pattern, code):
        return {
            "error_type": "MissingMainFunction",
            "error_category": "structure",
            "error_location": "main",
            "analysis": f"❌ Critical Error: The main function `{main_name}` is not defined."
        }
    
    # 检查3：主函数是否调用了辅助函数
    main_body = extract_function_body(code, main_name)
    if main_body:
        helper_call_pattern = rf"\b{re.escape(helper_name)}\s*\("
        if not re.search(helper_call_pattern, main_body):
            return {
                "error_type": "HelperNotCalled",
                "error_category": "structure",
                "error_location": "main",
                "analysis": (
                    f"⚠️ Dual-Task Violation: `{main_name}` does NOT call `{helper_name}`.\n\n"
                    f"Status:\n"
                    f"  ✓ Both functions are defined\n"
                    f"  ✗ But `{main_name}` doesn't use `{helper_name}`\n\n"
                    f"Requirement: The New Problem MUST call the Raw Problem's function."
                )
            }
    
    return None


def analyze_failure(previous_code: str, failure_output: str, test_list: List[str]) -> str:
    """
    分析失败原因，返回指导性建议。
    这是之前智能分析逻辑的封装版本。
    """
    guidance = ""
    # 检查是否为 "NameError"
    if "NameError:" in failure_output:
        # 尝试从错误信息中提取未定义的名称
        expected_name_match = re.search(r"NameError: name '([a-zA-Z_][a-zA-Z0-9_]*)' is not defined", failure_output)
        undefined_name = expected_name_match.group(1) if expected_name_match else None

        # 尝试从上一次的代码中提取模型自己定义的函数名
        actual_name_match = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", previous_code)
        actual_name = actual_name_match.group(1) if actual_name_match else "an unknown name"

        # 判断是否是缺少 typing import
        typing_types = {'List', 'Dict', 'Tuple', 'Set', 'Optional', 'Union', 'Any', 'Callable', 'Iterable', 'Iterator'}
        is_typing_type = undefined_name in typing_types if undefined_name else False
        
        # 检查错误是否发生在类型注解中（通常在 solution.py 的函数定义行）
        is_in_type_annotation = False
        if undefined_name and "solution.py" in failure_output:
            # 检查错误行是否包含类型注解模式
            error_line_match = re.search(r'File\s+"[^"]*solution\.py",\s+line\s+\d+', failure_output)
            if error_line_match:
                # 检查代码中是否使用了该类型注解
                if re.search(rf':\s*{undefined_name}\[', previous_code) or \
                   re.search(rf'->\s*{undefined_name}\[', previous_code) or \
                   re.search(rf'\([^)]*{undefined_name}\[', previous_code):
                    is_in_type_annotation = True
        
        # 检查是否是函数名不匹配（错误发生在 assert 语句中）
        is_function_name_error = False
        if undefined_name and not is_typing_type:
            # 检查测试用例中是否使用了这个名称
            for test in test_list:
                if re.search(rf'\b{undefined_name}\s*\(', test):
                    is_function_name_error = True
                    break

        if is_typing_type or is_in_type_annotation:
            # 缺少 typing import
            imports_needed = []
            if undefined_name:
                imports_needed.append(undefined_name)
            # 检查代码中还使用了哪些 typing 类型
            for typing_type in typing_types:
                if typing_type != undefined_name and re.search(rf'\b{typing_type}\[', previous_code):
                    imports_needed.append(typing_type)
            
            imports_str = ', '.join(sorted(set(imports_needed)))
            guidance = (
                f"**Critical Analysis**: The error was a `NameError: name '{undefined_name}' is not defined`. "
                f"This indicates that you used type annotations (like `{undefined_name}[...]`) but forgot to import the necessary types from the `typing` module. "
                f"**To fix this, you MUST add `from typing import {imports_str}` at the top of your code, before the function definition.**"
            )
        elif is_function_name_error and undefined_name:
            # 函数名不匹配
            guidance = (
                f"**Critical Analysis**: The error was a `NameError`. This is a strong indication of a function naming mismatch. "
                f"The test script was looking for a function named `{undefined_name}`, but your code defined a function named `{actual_name}`. "
                f"**To fix this, you MUST rename your function from `{actual_name}` to `{undefined_name}`.**"
            )
        elif undefined_name:
            # 其他 NameError（可能是变量名错误等）
            guidance = (
                f"**Critical Analysis**: The `NameError: name '{undefined_name}' is not defined` indicates that a name was used before it was defined. "
                f"This could be due to a typo, missing import, or incorrect variable/function name. "
                f"Please check if `{undefined_name}` should be imported, defined, or if there's a typo in the name."
            )
        else:
            guidance = (
                "**Critical Analysis**: The `NameError` indicates a function or variable was used before it was defined. "
                "This is often due to a typo, missing import, or a mismatch in the function name expected by the tests."
            )
    # 检查是否为 "AssertionError"
    elif "AssertionError" in failure_output:
        guidance = (
            "**Critical Analysis**: The code raised an `AssertionError`. This means your function ran without crashing but returned an incorrect result for a specific test case. "
            "Please re-examine your algorithm's logic and consider edge cases (e.g., empty inputs, single-element inputs, etc.)."
        )
    # 其他类型的错误
    else:
        guidance = (
            "**Critical Analysis**: The code failed with a runtime error. Please carefully read the traceback provided in the test feedback to understand the exact line and reason for the failure, then correct the underlying bug."
        )
    
    return guidance


def _format_failure_history(failure_history: List[Dict[str, Any]], previous_code: str) -> str:
    """
    Render a structured view of the recent failed attempts to help the model focus on targeted fixes.
    """
    if not failure_history:
        return ""

    max_entries = 3
    recent = failure_history[-max_entries:]
    start_index = len(failure_history) - len(recent) + 1

    lines: List[str] = [
        "## Failure History Snapshot",
        "Review the recent attempts below. Identify the minimal changes required instead of rewriting working code.",
        "| Attempt | Error Type | Details |",
        "| --- | --- | --- |",
    ]

    for offset, entry in enumerate(recent):
        attempt_no = start_index + offset
        err = entry.get("error_type", "Unknown")
        failed_assert = entry.get("failed_assert")
        expected = entry.get("expected_output")
        actual = entry.get("actual_output")

        details: List[str] = []
        if failed_assert:
            details.append(f"`{failed_assert}`")
        if expected is not None or actual is not None:
            details.append(f"expected={expected}, actual={actual}")
        if not details:
            details.append("See stderr for more context.")

        lines.append(f"| #{attempt_no} | {err} | {'; '.join(details)} |")

    lines.extend(
        [
            "",
            "Your latest submitted code:",
            "```python",
            previous_code,
            "```",
            "",
            "Guidelines:",
            "- **Do not rename or delete helper functions** defined for the Raw Problem.",
            "- Apply **targeted adjustments** only to the logic responsible for the failing asserts.",
            "- Reuse existing helper logic instead of rewriting from scratch.",
        ]
    )

    return "\n".join(lines) + "\n"


def _format_agent_analysis_section(error_diagnostics: Dict[str, Any]) -> str:
    """
    Render the agent-driven diagnosis details if available.
    """
    agent_payload = error_diagnostics.get("agent_analysis") or {}
    root_cause = agent_payload.get("root_cause") or error_diagnostics.get("root_cause")
    fix = agent_payload.get("fix_suggestion") or error_diagnostics.get("fix_suggestion")

    if not (root_cause or fix):
        return ""

    root_cause = root_cause or "Root cause unavailable."
    fix = fix or "Review the helper and main function logic carefully."

    return dedent(
        f"""
        ### 💡 Intelligent Diagnosis

        The analysis suggests: {root_cause}

        **Fix Recommendation:** {fix}
        """
    ).strip()


def build_initial_prompt(problem_description: str) -> str:
    """
    Compose the initial prompt requesting ONLY Python code in a fenced block.
    [优化]: 增强了对函数命名的警示，以提高首次成功率。
    """
    return dedent(
        f"""
        You are an expert Python programmer solving a coding challenge.
        Your goal is to write a Python solution that will be verified by automated tests.

        ## Problem Description
        {problem_description}

        ## Critical Requirements
        - Write clean, correct, and efficient Python code.
        - **Pay extremely close attention to the function name and signature required by the problem, as the automated tests are strict and case-sensitive.** A common reason for failure is a simple naming mismatch.
        - Your final output MUST be a single, complete Python code block enclosed in ```python ... ```.
        - Do not include any explanations, comments, or example usage outside the code block.

        Example format:
        ```python
        def required_function_name(param1, param2):
            # your code here
            pass
        ```
        """
    ).strip()


def build_feedback_prompt(
        problem_description: str,
        previous_code: str,
        failure_output: str,
        test_list: List[str] = None,
) -> str:
    """
    Ask the model to fix the code based on test failures. Request code-only output.
    [优化]: 在函数内部智能分析失败原因，并提供明确的、指导性的修正建议。
    """

    # --- 内部智能分析模块 ---
    # 这部分逻辑在函数内部，不改变外部接口
    # 使用 analyze_failure 函数来保持逻辑一致
    if test_list is None:
        test_list = []
    guidance = analyze_failure(previous_code, failure_output, test_list)

    # --- 动态构造最终的提示词 ---
    return dedent(
        f"""
        You are an expert Python programmer debugging a solution that has failed automated tests.

        ## Problem Description
        {problem_description}

        ## Your Previous Code (which failed)
        ```python
        {previous_code}
        ```

        ## Test Execution Feedback (Error Log)
        ```
        {failure_output}
        ```

        ## Guidance for Correction
        {guidance}

        ## Your Task
        Based on the feedback and the critical analysis provided above, provide a complete and corrected version of the Python code.
        - Preserve any helper functions defined previously and ensure the main function still calls them.
        - Make **surgical fixes** to the affected logic rather than rewriting everything from scratch.
        Return ONLY one fenced Python code block. Do not add any extra commentary.
        """
    ).strip()


def build_initial_prompt_with_cot(problem_description: str, test_list: List[str]) -> str:
    """
    优化后的初始提示词, 强制模型先输出算法思路 (Chain of Thought)。
    使用新的 @@ Instruction / @@ Response 格式。
    """
    function_name = extract_function_name_from_test(test_list[0]) if test_list else None
    naming_requirement = f"The primary function MUST be named `{function_name}`." if function_name else "Pay close attention to the required function name."

    return dedent(
        f"""
        You are an exceptionally intelligent coding assistant that consistently delivers accurate and reliable responses to user instructions. Write a solution of python file to the following problems, the solution of the second problem requires single or multiple calls to the first.
        
        @@ Instruction
        {problem_description}
        
        Requirements:
        - {naming_requirement}
        - **Do not rename or remove any helper functions described in the Raw Problem.** The main solution must call them exactly as specified.
        - Provide complete, working Python code.
        - Ensure your code passes all test cases.
        
        @@ Response
        Let's think step by step.
        """
    ).strip()


def build_initial_prompt_zero_shot(
    problem_description: str,
    helper_name: str,
    main_name: str,
    test_list: List[str],
) -> str:
    """
    Zero-Shot Protocol 初始提示词生成器。
    不提供示例，只提供架构规则和约束。
    
    Args:
        problem_description: 完整的问题描述（包含 Raw Problem 和 New Problem）
        helper_name: 辅助函数名称
        main_name: 主函数名称
        test_list: 测试用例列表
        
    Returns:
        Zero-Shot Protocol 格式的提示词
    """
    return dedent(
        f"""
        # TD-IR Zero-Shot Protocol

        You are a strict **Dual-Task Implementation Agent**. 

        You do not need examples; you follow architectural rules.

        ## 🏛️ THE ARCHITECTURE

        You are building a solution with two distinct components that must interact:

        1.  **COMPONENT A (Helper)**: The `Raw Problem`. Think of this as a **Frozen API** or **Library Function**.
           - Function Name: `{helper_name}`

        2.  **COMPONENT B (Main)**: The `New Problem`. Think of this as the **Client Code**.
           - Function Name: `{main_name}`

        ## 📜 THE RULES OF ENGAGEMENT (Absolute Constraints)

        ### Rule 1: The "Black Box" Mandate

        - You are **FORBIDDEN** from knowing the internal logic of the Helper when writing the Main function.
        - You **MUST** assume the Helper works perfectly.
        - **Action**: In the Main function, you **MUST** call `{helper_name}(arguments)` to process data.
        - **Violation**: Writing logic like `x * x` inside Main when the Helper is `square(x)` is a **CRITICAL FAILURE**.

        ### Rule 2: Signature Compliance

        - **Helper Definition**: Implement the Helper EXACTLY as described (same name `{helper_name}`, same arguments).
        - **Main Definition**: Implement the Main function name exactly as `{main_name}`.

        ### Rule 3: Data Flow Discipline

        - **Input Mapping**: Your job in the Main function is ONLY to prepare data, **CALL** the Helper, and aggregate results.
        - **Type Safety**: Check the Helper's return type description. If it returns a single value, do not iterate over it.

        ## 🏗️ REQUIRED CODE SKELETON

        You must fill in this abstract structure. Do not deviate.

        ```python
        import ... # Add all necessary imports here

        # --- COMPONENT A: THE HELPER ---
        def {helper_name}([args]):
            # Implement the specific logic for the Raw Problem here.
            pass

        # --- COMPONENT B: THE CLIENT ---
        def {main_name}([input_data]):
            # 1. Initialize container (list/sum/etc)
            # 2. Iterate through input_data
            # 3. >>> MANDATORY API CALL: val = {helper_name}(item) <<<
            # 4. Store or accumulate 'val'
            # 5. Return result
            pass
        ```

        ## 🧠 THINKING PROCESS (Internal Monologue)

        Before outputting code, verify:

        "Did I define the helper?" -> YES.
        "Did I call the helper inside the main function?" -> YES.
        "Did I avoid re-writing the helper's logic inside main?" -> YES.

        Now, generate the solution for the following task.

        ## Task Description

        {problem_description}

        ## Test Cases

        {chr(10).join(test_list[:3]) if len(test_list) > 0 else "No test cases provided."}

        **Output:** Provide the FULL Python code following the architecture rules above.
        """
    ).strip()


def build_feedback_prompt_with_reflection(
    problem_description: str,
    previous_code: str,
    failure_output: str,
    test_list: List[str],
) -> str:
    """
    优化后的反馈提示词, 强制模型先进行自我反思, 再修正代码。
    """
    guidance = analyze_failure(previous_code, failure_output, test_list)

    return dedent(
        f"""
        You are an expert Python programmer debugging your own code. Your previous solution failed the automated tests. Your task is to reflect on the error, explain the root cause, and then provide a corrected solution.

        ## Problem Description

        {problem_description}

        ## Your Previous Code (Failed)

        ```python
        {previous_code}
        ```

        ## Test Execution Feedback (Error Log)

        ```
        {failure_output}
        ```

        ## Your Task (Follow these steps precisely):

        ### Step 1: Root Cause Analysis (Self-Reflection)

        First, in a single sentence, explain the fundamental reason why your previous code failed based on the error log.

        (Example: "The code failed because I used the wrong function name, `my_func` instead of the required `correct_func`.")

        ### Step 2: Corrected Python Code

        Second, based on your analysis, provide the complete and corrected Python code.
        - Retain the helper function(s) defined in the Raw Problem and ensure the New Problem implementation calls them.
        - Apply **minimal, targeted** modifications that directly resolve the failing tests instead of rewriting the entire solution.

        ## Guidance to assist your analysis:

        {guidance}

        ## Your Response Format:

        **Root Cause Analysis:**

        [Your single-sentence analysis here]

        **Corrected Python Code:**

        ```python
        # your corrected code here
        ```
        """
    ).strip()


def parse_error_diagnostics(failure_output: str, exit_code: int) -> Dict[str, Any]:
    """
    解析错误输出，提取结构化的诊断信息。
    
    Returns:
        Dict with keys: error_type, failed_assert, actual_output, expected_output, error_message
    """
    diagnostics: Dict[str, Any] = {
        "error_type": "Unknown",
        "failed_assert": None,
        "actual_output": None,
        "expected_output": None,
        "error_message": failure_output,
    }
    
    if not failure_output:
        return diagnostics
    
    # 检查超时错误
    if "TIMEOUT" in failure_output or exit_code == 124:
        diagnostics["error_type"] = "TimeoutError"
        return diagnostics
    
    # 检查 AssertionError
    if "AssertionError" in failure_output:
        diagnostics["error_type"] = "AssertionError"
        
        # 尝试从错误信息中提取实际输出和期望输出
        # 格式可能是: AssertionError: expected X, got Y
        expected_match = re.search(r"expected[:\s]+([^\n,]+)", failure_output, re.IGNORECASE)
        actual_match = re.search(r"(?:got|actual)[:\s]+([^\n,]+)", failure_output, re.IGNORECASE)
        
        if expected_match:
            diagnostics["expected_output"] = expected_match.group(1).strip().strip("'\"")
        if actual_match:
            diagnostics["actual_output"] = actual_match.group(1).strip().strip("'\"")
        
        # 如果没有找到，尝试从 assert 语句中提取
        # 格式: assert func(...) == expected_value
        assert_eq_match = re.search(r"assert\s+([^\n]+)", failure_output)
        if assert_eq_match:
            assert_line = assert_eq_match.group(1).strip()
            diagnostics["failed_assert"] = assert_line
            
            # 尝试提取等号两边的值
            if "==" in assert_line:
                parts = assert_line.split("==", 1)
                if len(parts) == 2:
                    # 左边是函数调用，右边是期望值
                    diagnostics["expected_output"] = parts[1].strip().strip("'\"")
                    # 尝试从函数调用中提取实际值（这需要执行，暂时留空）
                    # 实际值应该从测试运行的输出中获取
        
        # 如果没有找到，尝试从 Traceback 中提取断言语句
        if not diagnostics["failed_assert"]:
            # 查找文件中的 assert 语句
            assert_in_file = re.search(r'File\s+"[^"]+",\s+line\s+\d+,\s+in\s+<module>\s+assert\s+([^\n]+)', failure_output)
            if assert_in_file:
                diagnostics["failed_assert"] = assert_in_file.group(1).strip()
        
        return diagnostics
    
    # 检查 NameError
    if "NameError:" in failure_output:
        diagnostics["error_type"] = "NameError"
        return diagnostics
    
    # 检查 TypeError
    if "TypeError:" in failure_output:
        diagnostics["error_type"] = "TypeError"
        return diagnostics
    
    # 检查 IndexError
    if "IndexError:" in failure_output:
        diagnostics["error_type"] = "IndexError"
        return diagnostics
    
    # 检查其他运行时错误
    if "Error:" in failure_output or "Traceback" in failure_output:
        # 尝试提取错误类型
        error_match = re.search(r"(\w+Error):", failure_output)
        if error_match:
            diagnostics["error_type"] = error_match.group(1)
        else:
            diagnostics["error_type"] = "RuntimeError"
    
    return diagnostics


def build_guided_diagnostics_prompt(
    problem_description: str,
    previous_code: str,
    error_diagnostics: Dict[str, Any],
    failure_history: List[Dict[str, Any]],
    test_list: List[str],
) -> str:
    """
    构建引导式诊断提示词，根据错误类型动态生成不同的诊断模板。
    """
    error_type = error_diagnostics.get("error_type", "Unknown")
    
    # 如果有失败历史，注入历史信息
    history_section = _format_failure_history(failure_history, previous_code)
    has_history = bool(history_section.strip())
    intelligent_section = _format_agent_analysis_section(error_diagnostics)
    context_sections = []
    if has_history:
        context_sections.append(history_section.strip())
    if intelligent_section:
        context_sections.append(intelligent_section)
    context_block = "\n\n".join(context_sections)
    if context_block:
        context_block = context_block + "\n\n"
    
    # 根据错误类型选择不同的模板
    if error_type == "AssertionError":
        failed_assert = error_diagnostics.get("failed_assert", "N/A")
        actual_output = error_diagnostics.get("actual_output", "N/A")
        expected_output = error_diagnostics.get("expected_output", "N/A")
        
        if has_history:
            # 如果有历史，使用历史注入版本
            # 预先构造智能诊断片段，避免在 f-string 表达式中出现反斜杠（会导致语法错误）
            intelligent_block = ""
            if intelligent_section:
                intelligent_block = intelligent_section + "\n\n"

            return dedent(
                f"""
                You are an expert Python programmer debugging your code. Your code failed a specific test.
                
                ## Problem Description
                
                {problem_description}
                
                {context_block}
                
                ## Your Task (Follow these steps precisely):
                
                ### Step 1: Root Cause Analysis (Self-Reflection)
                
                First, explain step-by-step why your code produced the actual output instead of the expected one. Analyze all past failures to identify the pattern.
                
                ### Step 2: Corrected Python Code
                
                Second, provide the complete and corrected Python code that satisfies all test cases.
                - Keep every helper function defined for the Raw Problem intact and ensure the New Problem implementation still calls them.
                - Apply **focused edits** only to the logic responsible for the failing assertions; do not rewrite unrelated code.
                
                ## Your Response Format:
                
                **Root Cause Analysis:**
                
                [Your step-by-step analysis here]
                
                **Corrected Python Code:**
                
                ```python
                # your corrected code here
                ```
                """
            ).strip()
        else:
            # 单次失败，使用标准诊断版本
            return dedent(
                f"""
                You are an expert Python programmer debugging your code. Your code failed a specific test.
                
                ## Problem Description
                
                {problem_description}
                
                ## Your Code (Failed)
                
                ```python
                {previous_code}
                ```
                
                ## Test Failure Details
                
                - Failed Assertion: `{failed_assert}`
                - Your code produced: `{actual_output}`
                - Expected output: `{expected_output}`
                {intelligent_block}
                
                ## Your Task (Follow these steps precisely):
                
                ### Step 1: Root Cause Analysis (Self-Reflection)
                
                First, explain step-by-step why your code produced the actual output instead of the expected one.
                
                ### Step 2: Corrected Python Code
                
                Second, provide the complete and corrected Python code.
                - Preserve helper function signatures and keep the New Problem solution calling them.
                - Modify only the necessary logic to resolve the failing assertion instead of rewriting everything.
                
                ## Your Response Format:
                
                **Root Cause Analysis:**
                
                [Your step-by-step analysis here]
                
                **Corrected Python Code:**
                
                ```python
                # your corrected code here
                ```
                """
            ).strip()
    
    elif error_type == "TimeoutError":
        return dedent(
            f"""
            You are an expert Python programmer debugging your code. Your code failed due to a timeout. This suggests an inefficient algorithm.
            
            ## Problem Description
            
            {problem_description}
            
            ## Your Code (Failed)
            
            ```python
            {previous_code}
            ```
            
            {context_block}
            
            ## Your Task (Follow these steps precisely):
            
            ### Step 1: Time Complexity Analysis
            
            First, analyze the time complexity of your current algorithm. Explain why it might be too slow.
            
            ### Step 2: Efficient Solution
            
            Second, propose a more efficient approach and implement the corrected, faster code.
            - Retain helper functions from the Raw Problem and reuse them in the optimized solution.
            - Limit your edits to the slow portions; avoid rewriting logic that already works correctly.
            
            ## Your Response Format:
            
            **Time Complexity Analysis:**
            
            [Your analysis here]
            
            **Corrected Python Code:**
            
            ```python
            # your corrected, efficient code here
            ```
            """
        ).strip()
    
    else:
        # 其他错误类型，使用通用诊断模板（回退到原有的反思提示词）
        error_message = error_diagnostics.get("error_message", "")
        guidance = analyze_failure(previous_code, error_message, test_list)
        
        return dedent(
            f"""
            You are an expert Python programmer debugging your own code. Your previous solution failed the automated tests. Your task is to reflect on the error, explain the root cause, and then provide a corrected solution.
            
            ## Problem Description
            
            {problem_description}
            
            ## Your Previous Code (Failed)
            
            ```python
            {previous_code}
            ```
            
            ## Test Execution Feedback (Error Log)
            
            ```
            {error_message}
            ```
            
            {context_block}
            
            ## Your Task (Follow these steps precisely):
            
            ### Step 1: Root Cause Analysis (Self-Reflection)
            
            First, in a single sentence, explain the fundamental reason why your previous code failed based on the error log.
            
            ### Step 2: Corrected Python Code
            
            Second, based on your analysis, provide the complete and corrected Python code.
            - Preserve all helper functions and ensure the main solution continues to call them.
            - Make focused edits to the problematic logic rather than rewriting the entire module.
            
            ## Guidance to assist your analysis:
            
            {guidance}
            
            ## Your Response Format:
            
            **Root Cause Analysis:**
            
            [Your single-sentence analysis here]
            
            **Corrected Python Code:**
            
            ```python
            # your corrected code here
            ```
            """
        ).strip()


def build_sanity_check_prompt(
    problem_description: str,
    actual_output: str,
    expected_output: str,
) -> str:
    """
    构建测试用例审查提示词，让LLM判断哪个输出是正确的。
    """
    return dedent(
        f"""
        You are a senior test engineer reviewing a discrepancy.
        
        ## Requirement
        
        {problem_description}
        
        ## Output Comparison
        
        - Output A (Code Output): `{actual_output}`
        - Output B (Test's Expected Output): `{expected_output}`
        
        ## Your Task
        
        Based *strictly* on the original requirement, which output is correct: A or B?
        
        Your answer must start with either "Output A is correct" or "Output B is correct", followed by a brief justification.
        
        ## Your Response Format:
        
        Output [A/B] is correct. [Your justification here]
        """
    ).strip()


# ========== 双任务场景增强提示词模板 ==========

def build_guided_diagnostics_prompt_enhanced(
    problem_description: str,
    previous_code: str,
    error_diagnostics: Dict[str, Any],
    failure_history: List[Dict[str, Any]],
    test_list: List[str],
) -> str:
    """
    增强版引导式诊断提示词，针对双任务场景的细化错误类型。
    支持基于执行追踪的精准修复策略。
    """
    error_type = error_diagnostics.get("error_type", "Unknown")
    helper_name = error_diagnostics.get("helper_function_name")
    main_name = error_diagnostics.get("main_function_name")
    targeted_repair_strategy = error_diagnostics.get("targeted_repair_strategy", "global")
    contract_verification_result = error_diagnostics.get("contract_verification_result")
    
    # 构建失败历史部分（复用通用格式化逻辑）
    history_section = _format_failure_history(failure_history, previous_code)
    
    # 返回类型不匹配（最高优先级）
    type_mismatch = error_diagnostics.get("type_mismatch")
    if type_mismatch:
        actual_type = type_mismatch.get("actual_type", "unknown")
        expected_type = type_mismatch.get("expected_type", "desired type")
        evidence_lines = "\n".join(f"- {item}" for item in type_mismatch.get("evidence", []) if item)
        if not evidence_lines:
            evidence_lines = "- Inferred from tests/problem description."

        return dedent(
            f"""
            ⚠️ **RETURN TYPE MISMATCH DETECTED**

            The tests/description require the main function `{main_name}` to return a `{expected_type}`, but the current implementation returns `{actual_type}`.

            ## Evidence

            {evidence_lines}

            ## Your Task

            - Update `{main_name}` so that it **returns a `{expected_type}` object** that satisfies the tests.
            - Keep the helper function `{helper_name}` intact unless it directly prevents the correct return type.
            - Provide the full corrected code. Focus on adjusting the output structure/constructors so the final `return` value has the expected type.
            """
        ).strip()

    # 结构性错误模板
    if error_type == "MissingHelperFunction":
        return dedent(
            f"""
            You are an expert Python programmer. Your submission is missing the helper function.
            
            ## Problem Description (Dual-Task)
            
            {problem_description}
            
            ## Critical Error Detected
            
            ❌ **The helper function `{helper_name}` is NOT defined.**
            
            This is a **dual-task problem** requiring TWO functions:
            1. **Helper Function** (Raw Problem): `{helper_name}(...)`
            2. **Main Function** (New Problem): `{main_name}(...)`
            
            ## Your Task
            
            Implement BOTH functions. The main function should use the helper function.
            
            ```python
            def {helper_name}(...):
                # Implement the Raw Problem here
                pass
            
            def {main_name}(...):
                # Use {helper_name} to solve the New Problem
                pass
            ```
            """
        ).strip()
    
    elif error_type == "HelperNotCalled":
        actual_out = error_diagnostics.get("actual_output", "N/A")
        expected_out = error_diagnostics.get("expected_output", "N/A")
        return dedent(
            f"""
            You are an expert Python programmer. Your code violates the dual-task requirement.
            
            ## Problem Description
            
            {problem_description}
            
            ## Your Previous Code
            
            ```python
            {previous_code}
            ```
            
            {history_section}
            
            ## Dual-Task Violation
            
            ⚠️ Status Check:
            - ✅ Helper function `{helper_name}` is defined
            - ✅ Main function `{main_name}` is defined
            - ❌ **BUT**: `{main_name}` does NOT call `{helper_name}`
            
            Test Result:
            - Your output: `{actual_out}`
            - Expected: `{expected_out}`
            
            **Requirement**: The New Problem's function MUST use the Raw Problem's function.
            
            ## Your Task
            
            Refactor `{main_name}` to call `{helper_name}` appropriately.
            
            **Corrected Python Code:**
            
            ```python
            def {helper_name}(...):
                # Keep as is (it's correct)
                pass
            
            def {main_name}(...):
                # Now calling {helper_name}!
                result = {helper_name}(...)
                pass
            ```
            """
        ).strip()
    
    # 逻辑错误（细化到辅助函数 or 主函数）
    elif error_type == "AssertionError_Helper" or targeted_repair_strategy == "helper_only":
        actual_out = error_diagnostics.get("actual_output", "N/A")
        expected_out = error_diagnostics.get("expected_output", "N/A")
        helper_violations = error_diagnostics.get("helper_violations", [])
        
        # 构建契约违反详情
        violation_details = ""
        if helper_violations:
            violation_details = "\n## Helper Function Contract Violations\n\n"
            violation_details += "The helper function's actual behavior does NOT match its specification:\n\n"
            for i, violation in enumerate(helper_violations[:3], 1):  # 最多显示3个
                violation_details += f"**Violation {i}:**\n"
                violation_details += f"- Input: `{violation.get('input', 'N/A')}`\n"
                violation_details += f"- Expected output: `{violation.get('expected_output', 'N/A')}`\n"
                violation_details += f"- Actual output: `{violation.get('actual_output', 'N/A')}`\n"
                violation_details += f"- Reason: {violation.get('reason', 'N/A')}\n\n"
        
        return dedent(
            f"""
            ⚠️ **DIAGNOSIS: HELPER FUNCTION FAULT**
            
            You are an expert Python programmer. The helper function has a logic bug.
            
            ## Problem Description
            
            {problem_description}
            
            ## Your Previous Code
            
            ```python
            {previous_code}
            ```
            
            {history_section}
            
            ## Test Failure
            
            - Your output: `{actual_out}`
            - Expected output: `{expected_out}`
            
            {violation_details}
            
            ## 🔍 Hierarchical Diagnosis Result
            
            **Fault Location: Helper Function `{helper_name}`**
            
            Through execution trace analysis, we verified that:
            - ✅ The main function `{main_name}` is calling `{helper_name}` correctly
            - ❌ **The helper function `{helper_name}` violates its contract** (Raw Problem specification)
            
            The helper function is returning incorrect results for certain inputs, which causes the main function to produce wrong output.
            
            ## ⚠️ **ACTION: Fix ONLY the helper function. Do NOT modify the main function.**
            
            **CRITICAL INSTRUCTIONS:**
            - ❌ **DO NOT** modify `{main_name}` - it is calling the helper correctly
            - ✅ **ONLY** fix `{helper_name}` to match the Raw Problem specification
            - ✅ Return the complete code with both functions, but **ONLY** modify `{helper_name}`
            
            ## Your Task
            
            ### Step 1: Root Cause Analysis
            
            Analyze why `{helper_name}` is returning wrong results:
            - Review the Raw Problem specification for `{helper_name}`
            - Compare expected vs actual outputs from the violations above
            - Identify the logic error in `{helper_name}`
            
            ### Step 2: Corrected Python Code
            
            Provide the complete code with **ONLY** the helper function fixed:
            
            ```python
            def {helper_name}(...):
                # FIXED: Correct the logic to match Raw Problem specification
                # Example: If input X should return Y but returned Z, fix the condition/logic
                pass
            
            def {main_name}(...):
                # KEEP UNCHANGED - Do not modify this function
                # The main function is calling the helper correctly
                pass
            ```
            
            **Remember: Only modify `{helper_name}`. Keep `{main_name}` exactly as it is.**
            """
        ).strip()
    
    elif error_type == "AssertionError_Main" or targeted_repair_strategy == "main_only":
        actual_out = error_diagnostics.get("actual_output", "N/A")
        expected_out = error_diagnostics.get("expected_output", "N/A")
        helper_contract_valid = error_diagnostics.get("helper_contract_valid", False)
        
        # 构建契约验证结果详情
        contract_verification = ""
        if contract_verification_result:
            violations = contract_verification_result.get("violations", [])
            if not violations and helper_contract_valid:
                contract_verification = (
                    "\n## ✅ Helper Function Contract Verification\n\n"
                    f"Through execution trace analysis, we verified that:\n"
                    f"- ✅ The helper function `{helper_name}` **correctly implements** the Raw Problem specification\n"
                    f"- ✅ All helper function calls returned expected results according to its contract\n"
                    f"- ❌ **The error is in the main function `{main_name}`**\n"
                )
        elif helper_contract_valid:
            contract_verification = (
                "\n## ✅ Helper Function Contract Verification\n\n"
                f"Through execution trace analysis, we verified that:\n"
                f"- ✅ The helper function `{helper_name}` **correctly implements** the Raw Problem specification\n"
                f"- ❌ **The error is in the main function `{main_name}`**\n"
            )
        
        return dedent(
            f"""
            ✅ **DIAGNOSIS: HELPER VERIFIED CORRECT**
            
            You are an expert Python programmer. The main function has a logic bug.
            
            ## Problem Description
            
            {problem_description}
            
            ## Your Previous Code
            
            ```python
            {previous_code}
            ```
            
            {history_section}
            
            ## Test Failure
            
            - Your output: `{actual_out}`
            - Expected output: `{expected_out}`
            
            {contract_verification}
            
            ## 🔍 Hierarchical Diagnosis Result
            
            **Fault Location: Main Function `{main_name}`**
            
            The helper function `{helper_name}` is working correctly. The problem is in:
            - How `{main_name}` calls `{helper_name}` (wrong arguments?)
            - How `{main_name}` processes the helper's return value
            - Additional logic in `{main_name}` that combines helper results incorrectly
            
            ## ⚠️ **ACTION: Fix ONLY the main function logic. Do NOT modify the helper function.**
            
            **CRITICAL INSTRUCTIONS:**
            - ❌ **DO NOT** modify `{helper_name}` - it correctly implements the Raw Problem
            - ✅ **ONLY** fix `{main_name}` logic or how it uses the helper
            - ✅ Return the complete code with both functions, but **ONLY** modify `{main_name}`
            
            ## Your Task
            
            ### Step 1: Root Cause Analysis
            
            Analyze why `{main_name}` is producing wrong output:
            - The helper `{helper_name}` is correct (verified by contract check)
            - Check: Are you passing correct arguments to `{helper_name}`?
            - Check: Are you processing its return value correctly?
            - Check: Is there additional logic in `{main_name}` that's wrong?
            
            ### Step 2: Corrected Python Code
            
            Provide the complete code with **ONLY** the main function fixed:
            
            ```python
            def {helper_name}(...):
                # KEEP UNCHANGED - Do not modify this function
                # The helper function correctly implements the Raw Problem
                pass
            
            def {main_name}(...):
                # FIXED: Correct the logic or how you use {helper_name}
                # Example: Fix argument passing, return value processing, or additional logic
                pass
            ```
            
            **Remember: Only modify `{main_name}`. Keep `{helper_name}` exactly as it is.**
            """
        ).strip()
    
    # 运行时错误（拼写错误）
    elif error_type == "NameError_HelperTypo":
        error_msg = error_diagnostics.get("error_message", "")
        undefined_match = re.search(r"name '([^']+)' is not defined", error_msg)
        undefined_name = undefined_match.group(1) if undefined_match else "unknown"
        
        return dedent(
            f"""
            You are an expert Python programmer. You have a typo in the function name.
            
            ## Problem Description
            
            {problem_description}
            
            ## Your Previous Code
            
            ```python
            {previous_code}
            ```
            
            ## Error: Typo Detected! 🔤
            
            ```
            NameError: name '{undefined_name}' is not defined
            ```
            
            You tried to call `{undefined_name}`, but the helper function is named `{helper_name}`.
            
            Comparison:
            - ❌ You wrote: `{undefined_name}`
            - ✅ Should be: `{helper_name}`
            
            ## Your Task
            
            Simple fix: Change `{undefined_name}` to `{helper_name}` in `{main_name}`.
            
            ```python
            def {helper_name}(...):
                # No changes needed
                pass
            
            def {main_name}(...):
                # FIXED: Changed {undefined_name} to {helper_name}
                result = {helper_name}(...)
                pass
            ```
            """
        ).strip()
    
    # 回退到原有的 build_guided_diagnostics_prompt
    else:
        return build_guided_diagnostics_prompt(
            problem_description,
            previous_code,
            error_diagnostics,
            failure_history,
            test_list
        )


def build_third_iteration_complete_rethink_prompt(raw_problem: str, failure_history: list) -> str:
    """
    构建第三次迭代的'彻底重思'提示词。
    包含启发式规则来检测 Set/List 类型错误和 TypeError。
    """
    error_analysis = []
    for i, fail in enumerate(failure_history):
        failed_assert = str(fail.get("failed_assert", "N/A"))
        stderr = str(fail.get("stderr_tail") or fail.get("error_message", "N/A"))
        
        hints = []
        # 启发式规则 1: 集合 vs 列表
        if "== set(" in failed_assert or "== {" in failed_assert:
            hints.append("CRITICAL: The test expects a SET result (e.g. {1,2}), but you likely returned a LIST.")
            hints.append("ACTION: Ensure your function returns a `set`.")
            
        # 启发式规则 2: 类型错误 (int vs list)
        if "TypeError" in stderr and "list" in stderr and "int" in stderr:
            hints.append("CRITICAL: TypeError detected (list vs int). Check your accumulators.")
            
        hint_str = "\n   ".join([f"- {h}" for h in hints]) if hints else "- Review logic carefully."
        
        analysis_block = (
            f"--- Attempt {i+1} Failure ---\n"
            f"Failed Assertion: {failed_assert}\n"
            f"Error Log:\n{stderr}\n"
            f"Analysis & Hints:\n   {hint_str}"
        )
        error_analysis.append(analysis_block)

    error_report = "\n".join(error_analysis)

    return f"""
You are an expert Python Algorithm Engineer. 
You have failed this task {len(failure_history)} times. 
This is the FINAL attempt. Do NOT try to patch the old code. Rewrite it entirely.

=== 1. THE TASK ===
{raw_problem}

=== 2. AUTOPSY OF PREVIOUS FAILURES ===
{error_report}

=== 3. STRICT RULES ===
1. **Return Type**: If the failed assertion expects a `set`, you MUST return a `set`.
2. **Clean Slate**: Do not look at previous code.
3. **Output Format**: Output ONLY raw Python code. NO markdown blocks, NO "Root Cause Analysis" text.
"""
