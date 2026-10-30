"""Task format.

A task is a directory:

    my-task/
      task.toml          name, difficulty, tags, timeouts
      instruction.md     what the agent is told, nothing more
      environment/       files the agent starts with (copied into a fresh workspace)
      solution/solve.sh  reference solution, used to prove the task is solvable
      tests/             hidden verifier; copied in only after the agent has finished

The verifier runs `tests/test.sh` if present, otherwise pytest on `tests/`. It
passes when it exits 0. A verifier can also write a fractional score between 0
and 1 to $REWARD_FILE for partial credit."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class TaskError(ValueError):
    pass


@dataclass(frozen=True)
class Task:
    name: str
    path: Path
    instruction: str
    difficulty: str = "medium"
    tags: tuple[str, ...] = ()
    agent_timeout: float = 600.0
    verifier_timeout: float = 120.0
    env: dict[str, str] = field(default_factory=dict)

    @property
    def environment(self) -> Path:
        return self.path / "environment"

    @property
    def tests(self) -> Path:
        return self.path / "tests"

    @property
    def solution(self) -> Path:
        return self.path / "solution" / "solve.sh"

    @classmethod
    def load(cls, path: str | Path) -> "Task":
        path = Path(path).resolve()
        meta_file, instr_file = path / "task.toml", path / "instruction.md"
        for f in (meta_file, instr_file):
            if not f.is_file():
                raise TaskError(f"{path.name}: missing {f.name}")
        if not (path / "tests").is_dir():
            raise TaskError(f"{path.name}: missing tests/")
        meta = tomllib.loads(meta_file.read_text(encoding="utf-8"))
        instruction = instr_file.read_text(encoding="utf-8").strip()
        if not instruction:
            raise TaskError(f"{path.name}: instruction.md is empty")
        return cls(
            name=meta.get("name", path.name),
            path=path,
            instruction=instruction,
            difficulty=meta.get("difficulty", "medium"),
            tags=tuple(meta.get("tags", ())),
            agent_timeout=float(meta.get("agent_timeout", 600)),
            verifier_timeout=float(meta.get("verifier_timeout", 120)),
            env={str(k): str(v) for k, v in meta.get("env", {}).items()},
        )


def discover(root: str | Path, names: list[str] | None = None) -> list[Task]:
    root = Path(root)
    if (root / "task.toml").exists():
        return [Task.load(root)]
    tasks = [Task.load(d) for d in sorted(root.iterdir()) if (d / "task.toml").exists()]
    if names:
        wanted = set(names)
        tasks = [t for t in tasks if t.name in wanted]
        missing = wanted - {t.name for t in tasks}
        if missing:
            raise TaskError(f"unknown tasks: {', '.join(sorted(missing))}")
    return tasks
