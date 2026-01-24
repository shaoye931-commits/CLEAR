from __future__ import annotations
from textwrap import dedent
import re  # 引入正则表达式库，以便在函数内部进行智能分析


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
) -> str:
    """
    Ask the model to fix the code based on test failures. Request code-only output.
    [优化]: 在函数内部智能分析失败原因，并提供明确的、指导性的修正建议。
    """

    # --- 内部智能分析模块 ---
    # 这部分逻辑在函数内部，不改变外部接口
    guidance = ""
    # 检查是否为 "NameError"
    if "NameError:" in failure_output:
        # 尝试从错误信息中提取测试脚本期望的函数名
        expected_name_match = re.search(r"NameError: name '([a-zA-Z_][a-zA-Z0-9_]*)' is not defined", failure_output)
        expected_name = expected_name_match.group(1) if expected_name_match else None

        # 尝试从上一次的代码中提取模型自己定义的函数名
        actual_name_match = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", previous_code)
        actual_name = actual_name_match.group(1) if actual_name_match else "an unknown name"

        if expected_name:
            guidance = (
                f"**Critical Analysis**: The error was a `NameError`. This is a strong indication of a function naming mismatch. "
                f"The test script was looking for a function named `{expected_name}`, but your code defined a function named `{actual_name}`. "
                f"**To fix this, you MUST rename your function from `{actual_name}` to `{expected_name}`.**"
            )
        else:  # 如果正则没匹配到，提供一个通用的 NameError 指导
            guidance = (
                "**Critical Analysis**: The `NameError` indicates a function or variable was used before it was defined. "
                "This is often due to a typo or a mismatch in the function name expected by the tests."
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
        Return ONLY one fenced Python code block. Do not add any extra commentary.
        """
    ).strip()