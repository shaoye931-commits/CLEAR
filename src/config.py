from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


DATR_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DATR_ROOT.parent
CLEAR_METHOD_VERSION = "CLEAR-v1"
INITIAL_PROMPT_VERSION = "CLEAR-Initial-v1"
DIAGNOSIS_PROMPT_VERSION = "CLEAR-Diagnosis-v1"
REFINEMENT_PROMPT_VERSION = "CLEAR-Refinement-v1"


@dataclass(frozen=True)
class DATRConfig:
    humaneval_path: Path = PROJECT_ROOT / "data" / "humaneval_pro.json"
    mbpp_path: Path = PROJECT_ROOT / "data" / "mbpp_pro.json"
    model_name: str = ""
    temperature: float = 0.0
    reset_temperature: float = 0.6
    top_p: float = 1.0
    max_tokens: int = 4096
    refinement_budget: int = 3
    allow_real_api: bool = False
    api_endpoint: str = ""
    api_key_env: str = "CLEAR_API_KEY"
    request_timeout_s: float = 60.0
    request_retries: int = 1
    docker_image: str = "clear-sandbox:latest"
    public_test_timeout_s: int = 3
    run_id: str = field(default_factory=lambda: time.strftime("%Y%m%d_%H%M%S"))
    output_root: Path = PROJECT_ROOT / "results"
    method_version: str = CLEAR_METHOD_VERSION

    @classmethod
    def from_environment(cls, **overrides: object) -> "DATRConfig":
        values: dict[str, object] = {
            "humaneval_path": Path(
                os.getenv(
                    "CLEAR_HUMANEVAL_PATH",
                    PROJECT_ROOT / "data" / "humaneval_pro.json",
                )
            ),
            "mbpp_path": Path(
                os.getenv(
                    "CLEAR_MBPP_PATH",
                    PROJECT_ROOT / "data" / "mbpp_pro.json",
                )
            ),
            "model_name": os.getenv("CLEAR_MODEL", "").strip(),
            "api_endpoint": os.getenv("CLEAR_API_ENDPOINT", "").strip(),
            "api_key_env": os.getenv("CLEAR_API_KEY_ENV", "CLEAR_API_KEY").strip(),
            "docker_image": os.getenv("CLEAR_DOCKER_IMAGE", "clear-sandbox:latest").strip(),
            "output_root": Path(
                os.getenv("CLEAR_OUTPUT_ROOT", PROJECT_ROOT / "results")
            ),
        }
        values.update(overrides)
        return cls(**values)

    def __post_init__(self) -> None:
        if not self.run_id or Path(self.run_id).name != self.run_id or self.run_id in {".", ".."}:
            raise ValueError("run_id must be a plain directory name")
        if self.refinement_budget < 1:
            raise ValueError("refinement_budget must be positive")
        if self.public_test_timeout_s <= 0:
            raise ValueError("public_test_timeout_s must be positive")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.request_timeout_s <= 0 or not math.isfinite(self.request_timeout_s):
            raise ValueError("request_timeout_s must be positive and finite")
        if self.request_retries < 0:
            raise ValueError("request_retries must not be negative")
        if not 0 <= self.temperature <= 2 or not 0 <= self.reset_temperature <= 2:
            raise ValueError("temperatures must be between 0 and 2")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
