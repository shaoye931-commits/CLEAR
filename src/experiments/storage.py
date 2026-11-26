from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.experiments.records import TaskRunRecord, to_jsonable


class StorageConflictError(RuntimeError):
    pass


def _task_key(task_id: object) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id))
    if not value or value in {".", ".."}:
        raise ValueError("invalid task id")
    return value


def _atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(to_jsonable(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@dataclass(frozen=True)
class RunStorage:
    run_dir: Path

    @classmethod
    def create(cls, output_root: Path, run_id: str, metadata: dict[str, Any]) -> "RunStorage":
        run_dir = output_root / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise StorageConflictError(f"run already exists: {run_id}") from error
        storage = cls(run_dir)
        _atomic_json(run_dir / "metadata.json", metadata)
        return storage

    def append_event(self, event: str, payload: dict[str, Any]) -> None:
        line = json.dumps(
            {"event": event, "payload": to_jsonable(payload)},
            ensure_ascii=False,
            sort_keys=True,
        )
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def save_task(self, record: TaskRunRecord) -> Path:
        path = self.run_dir / f"task_{_task_key(record.task_id)}.json"
        _atomic_json(path, record.as_dict())
        return path

    def save_evaluation(self, task_id: object, result: Any) -> Path:
        path = self.run_dir / f"task_{_task_key(task_id)}.evaluation.json"
        if path.exists():
            raise StorageConflictError(f"evaluation already exists for task {task_id}")
        _atomic_json(path, result)
        return path

    def mark_task_complete(self, record: TaskRunRecord) -> None:
        self.save_task(record)
        key = _task_key(record.task_id)
        sealed_hash = None
        if record.sealed_candidate is not None:
            sealed_hash = record.sealed_candidate.content_hash
            _atomic_json(self.run_dir / f"task_{key}.sealed.json", record.sealed_candidate)
        _atomic_json(
            self.run_dir / f"task_{key}.complete.json",
            {"task_id": record.task_id, "sealed_hash": sealed_hash},
        )
