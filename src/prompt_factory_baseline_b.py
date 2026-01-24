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
    基线B版本：使用简单模糊的反馈提示词，不提供详细的错误分析。
    """
    # --- 基线B：使用简单模糊的反馈 ---
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
        你的代码错了，请修复它。

        ## Your Task
        Provide a complete and corrected version of the Python code.
        Return ONLY one fenced Python code block. Do not add any extra commentary.
        """
    ).strip()

