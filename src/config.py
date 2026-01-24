from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional

from dotenv import load_dotenv


def load_environment(env_file_path: Optional[str] = None) -> None:
    """
    Load environment variables from a .env file if present.
    If env_file_path is None, python-dotenv will search up the tree.
    """
    if env_file_path is None:
        # Try to find .env in project root (assuming src/ is inside project root)
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent
        project_root = src_dir.parent
        env_file_path = str(project_root / ".env")
    load_dotenv(dotenv_path=env_file_path, override=False)


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = ""

    @staticmethod
    def from_env() -> "DeepSeekConfig":
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "")
        if not api_key:
            raise RuntimeError(
                "Missing DEEPSEEK_API_KEY. Set it in your environment or .env file."
            )
        return DeepSeekConfig(api_key=api_key, base_url=base_url)


@dataclass(frozen=True)
class ExperimentConfig:
    model_to_test: str = ""
    use_openrouter: bool = False 

    @staticmethod
    def from_env() -> "ExperimentConfig":
        model = os.getenv("MODEL_TO_TEST", "")
        use_openrouter = os.getenv("USE_OPENROUTER", "false").lower() in ("true", "1", "yes")
        return ExperimentConfig(model_to_test=model, use_openrouter=use_openrouter)

@dataclass(frozen=True)
class OpenRouterConfig:
    """
    OpenRouter 配置，从环境变量中读取：
    - OPENROUTER_API_KEY
    - OPENROUTER_BASE_URL
    """

    api_key: str
    base_url: str = ""

    @staticmethod
    def from_env() -> "OpenRouterConfig":
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        base_url = os.getenv("OPENROUTER_BASE_URL", "")
        if not api_key:
            raise RuntimeError(
                "Missing OPENROUTER_API_KEY. Set it in your environment or .env file."
            )
        return OpenRouterConfig(api_key=api_key, base_url=base_url)


