from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from .config import DeepSeekConfig


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        })

    def post(self, path: str, payload: Dict[str, Any], timeout_s: int = 60) -> Dict[str, Any]:
        url = self._config.base_url.rstrip("/") + "/" + path.lstrip("/")
        response = self._session.post(url, data=json.dumps(payload), timeout=timeout_s)
        response.raise_for_status()
        return response.json()


