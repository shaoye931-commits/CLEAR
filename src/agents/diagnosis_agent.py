from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Dict, Optional

from ..config import ExperimentConfig, load_environment
from ..deepseek_client import DeepSeekClient


def _strip_json(text: str) -> str:
    """
    Remove common wrappers (like markdown fences) around JSON snippets.
    """
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # After stripping backticks, remove leading json/python labels if present
        if text.lower().startswith("json"):
            text = text[4:]
        elif text.lower().startswith("python"):
            text = text[6:]
    return text.strip()


class DiagnosisAgent:
    """
    Thin wrapper around DeepSeek chat completion API that provides targeted
    reasoning about dual-task assertion failures.
    """

    SYSTEM_PROMPT_TEMPLATE = dedent(
        """\
        You are a Code Logic Expert debugging a Python script with a "Dual-Task" structure (Helper Function + Main Function).
        Analyze the provided Test Failure.

        Task 1 (Helper): {raw_problem}
        Task 2 (Main): {new_problem}

        Output JSON only:
        {{
            "root_cause": "Brief explanation (e.g., Helper function logic is inverted)",
            "fix_suggestion": "Actionable instruction for the coder (e.g., Change x > 0 to x >= 0)"
        }}
        """
    )

    def __init__(
        self,
        client: DeepSeekClient,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 300,
    ) -> None:
        load_environment()
        self._client = client
        self._model = model or ExperimentConfig.from_env().model_to_test
        self._temperature = temperature
        self._max_tokens = max_tokens

    def diagnose(
        self,
        task_context: Dict[str, Any],
        code: str,
        stderr: str,
        failed_test_info: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Ask DeepSeek to summarize the root cause and suggested fix.
        """
        raw_problem = task_context.get("raw_problem") or "N/A"
        new_problem = task_context.get("new_problem") or "N/A"
        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            raw_problem=raw_problem,
            new_problem=new_problem,
        )

        failed_test_json = json.dumps(failed_test_info or {}, ensure_ascii=False, indent=2)
        user_prompt = dedent(
            f"""\
            ### Code Under Test
            ```python
            {code.strip() if code else "# code unavailable"}
            ```

            ### Test Failure Output
            {stderr or "No stderr captured."}

            ### Failed Test Info
            {failed_test_json}
            """
        ).strip()

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        response = self._client.post("/chat/completions", payload)
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        ).strip()

        parsed = self._parse_response(content)
        if not parsed:
            # Fall back to a minimal structure to avoid KeyErrors upstream.
            return {
                "root_cause": "Unable to extract agent analysis.",
                "fix_suggestion": "Re-run diagnostics manually.",
            }
        return parsed

    def _parse_response(self, content: str) -> Dict[str, str]:
        candidate = _strip_json(content)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            # Try to salvage JSON between braces.
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    return {}
            else:
                return {}

        root_cause = str(data.get("root_cause", "")).strip()
        fix = str(data.get("fix_suggestion", "")).strip()
        if not root_cause and not fix:
            return {}
        return {"root_cause": root_cause, "fix_suggestion": fix or "Provide a fix suggestion."}


