from __future__ import annotations

import json
import math
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class LLMResponse:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost: float | None = None
    request_attempts: int = 1
    finish_reason: str | None = None
    reasoning_tokens: int | None = None
    reasoning_content_present: bool = False
    truncated: bool = False


class ModelRequestConfig(Protocol):
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int


class LLMRequestError(RuntimeError):
    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class APIBudgetExceededError(LLMRequestError):
    pass


@dataclass
class APICallBudget:
    max_requests: int
    max_tokens: int
    requests_used: int = 0
    tokens_used: int = 0
    usage_missing: bool = False

    def __post_init__(self) -> None:
        if self.max_requests <= 0 or self.max_tokens <= 0:
            raise ValueError("API request and token budgets must be positive")

    def begin_request(self) -> None:
        if self.requests_used >= self.max_requests:
            raise APIBudgetExceededError("API request budget exhausted", 0)
        if self.tokens_used >= self.max_tokens or self.usage_missing:
            reason = "Token usage was missing" if self.usage_missing else "API token budget exhausted"
            raise APIBudgetExceededError(reason, 0)
        self.requests_used += 1

    def record_usage(self, prompt_tokens: int | None, completion_tokens: int | None) -> None:
        if prompt_tokens is None or completion_tokens is None:
            self.usage_missing = True
            return
        self.tokens_used += prompt_tokens + completion_tokens

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "max_requests": self.max_requests,
            "max_tokens": self.max_tokens,
            "requests_used": self.requests_used,
            "tokens_used": self.tokens_used,
            "usage_missing": self.usage_missing,
        }


Transport = Callable[[urllib.request.Request, float], bytes]
AuditHook = Callable[[str, dict[str, object]], None]


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                raise ValueError("response content contains a non-text segment")
            parts.append(part["text"])
        return "".join(parts)
    raise ValueError("response content is not text")


class OpenAICompatibleClient:
    """Small explicit opt-in adapter for OpenAI-compatible chat endpoints."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        allow_real_api: bool = False,
        timeout_s: float = 60.0,
        max_retries: int = 1,
        transport: Transport | None = None,
        audit_hook: AuditHook | None = None,
        budget: APICallBudget | None = None,
    ) -> None:
        if timeout_s <= 0 or not math.isfinite(timeout_s) or max_retries < 0:
            raise ValueError("invalid timeout or retry limit")
        self.endpoint = endpoint
        self.api_key = api_key
        self.allow_real_api = allow_real_api
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transport = transport or _urlopen_transport
        self.audit_hook = audit_hook
        self.budget = budget

    def __call__(self, prompt: str, config: ModelRequestConfig) -> LLMResponse:
        if not self.allow_real_api:
            raise LLMRequestError("real API requests are disabled", 0)
        if not self.api_key:
            raise LLMRequestError("API key is missing", 0)
        payload = json.dumps(
            {
                "model": config.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": config.temperature,
                "top_p": config.top_p,
                "max_tokens": config.max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            if self.budget:
                self.budget.begin_request()
            if self.audit_hook:
                self.audit_hook("llm_request_started", {"attempt": attempt, "model": config.model_name})
            started = time.perf_counter()
            try:
                raw = self.transport(request, self.timeout_s)
                data = json.loads(raw.decode("utf-8"))
                choice = data["choices"][0]
                message = choice["message"]
                content = _message_text(message["content"])
                if not content:
                    raise ValueError("response content is empty")
                finish_reason = choice.get("finish_reason")
                if finish_reason is not None and not isinstance(finish_reason, str):
                    raise ValueError("finish_reason is not text")
                usage = data.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                if not isinstance(prompt_tokens, int):
                    prompt_tokens = None
                if not isinstance(completion_tokens, int):
                    completion_tokens = None
                details = usage.get("completion_tokens_details") or {}
                reasoning_tokens = details.get("reasoning_tokens", usage.get("reasoning_tokens"))
                if not isinstance(reasoning_tokens, int):
                    reasoning_tokens = None
                reasoning_present = bool(message.get("reasoning_content"))
                if self.budget:
                    self.budget.record_usage(prompt_tokens, completion_tokens)
                    if self.audit_hook:
                        self.audit_hook("api_budget_updated", self.budget.as_dict())
                result = LLMResponse(
                    content,
                    prompt_tokens,
                    completion_tokens,
                    request_attempts=attempt,
                    finish_reason=finish_reason,
                    reasoning_tokens=reasoning_tokens,
                    reasoning_content_present=reasoning_present,
                    truncated=finish_reason == "length",
                )
                if self.audit_hook:
                    self.audit_hook(
                        "llm_request_completed",
                        {
                            "attempt": attempt,
                            "elapsed_seconds": time.perf_counter() - started,
                            "finish_reason": finish_reason,
                            "truncated": finish_reason == "length",
                            "reasoning_tokens": reasoning_tokens,
                            "reasoning_content_present": reasoning_present,
                        },
                    )
                return result
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")[:2000]
                detail = body.replace(self.api_key, "<redacted>")
                trace_id = error.headers.get("x-siliconcloud-trace-id") if error.headers else None
                message = f"HTTP {error.code}: {detail}"
                if trace_id:
                    message += f"; trace_id={trace_id}"
                if self.audit_hook:
                    self.audit_hook(
                        "llm_request_failed",
                        {"attempt": attempt, "error": message},
                    )
                if error.code not in {408, 429} and error.code < 500:
                    raise LLMRequestError(message, attempt) from error
                if attempt == attempts:
                    raise LLMRequestError(message, attempt) from error
            except (TimeoutError, socket.timeout, OSError, urllib.error.URLError) as error:
                if self.audit_hook:
                    self.audit_hook(
                        "llm_request_failed",
                        {"attempt": attempt, "error": f"{type(error).__name__}: {error}"},
                    )
                if attempt == attempts:
                    raise LLMRequestError(str(error), attempt) from error
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as error:
                if self.audit_hook:
                    self.audit_hook(
                        "llm_request_failed",
                        {"attempt": attempt, "error": f"invalid_response: {error}"},
                    )
                raise LLMRequestError(f"invalid response: {error}", attempt) from error
        raise AssertionError("unreachable")
