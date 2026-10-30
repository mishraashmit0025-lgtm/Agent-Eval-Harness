"""Agents the harness can evaluate.

An agent gets the task instruction and a sandbox, and changes the workspace.
The harness does not care how: a shell script, a CLI coding agent, or a Python
object driving a model API all fit the same interface."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .sandbox import Sandbox
from .task import Task


@dataclass
class AgentRun:
    exit_code: int | None = 0  # None means the agent hit its time limit
    log: str = ""
    cost_usd: float = 0.0
    extra: dict = field(default_factory=dict)


class Agent:
    name = "agent"

    def run(self, task: Task, sandbox: Sandbox, timeout: float) -> AgentRun:
        raise NotImplementedError


class NopAgent(Agent):
    """Does nothing. Every task must fail under it, or its verifier is too weak."""

    name = "nop"

    def run(self, task, sandbox, timeout):
        return AgentRun(0, "did nothing")


class OracleAgent(Agent):
    """Runs the task's reference solution. Every task must pass under it."""

    name = "oracle"

    def run(self, task, sandbox, timeout):
        dest = f"{sandbox.private}/solution/solve.sh"
        sandbox.put(task.solution, dest)
        r = sandbox.exec(f"bash {shlex.quote(dest)}", timeout, env=task.env)
        return AgentRun(r.exit_code, r.output)


class CommandAgent(Agent):
    """Any CLI agent: a command template run in the workspace.

    `{instruction}` is replaced with the shell-quoted instruction, and the
    instruction is also in $TASK_INSTRUCTION. For example:

        claude -p {instruction} --dangerously-skip-permissions
        cagent run --mode yolo {instruction}
    """

    def __init__(self, template: str, name: str | None = None, env: dict[str, str] | None = None):
        self.template = template
        self.name = name or template.split()[0]
        self.env = env or {}

    def run(self, task, sandbox, timeout):
        cmd = self.template.replace("{instruction}", shlex.quote(task.instruction))
        r = sandbox.exec(cmd, timeout, env={**task.env, **self.env, "TASK_INSTRUCTION": task.instruction})
        return AgentRun(r.exit_code, r.output)


class ScriptAgent(Agent):
    """Replays a stored per-task script, `<dir>/<task name>.sh`, run in the workspace.

    Useful for baselines, for recorded agent solutions, and for checking that a
    plausible but wrong solution really fails a task's verifier."""

    def __init__(self, directory: str, name: str | None = None):
        self.dir = Path(directory).resolve()
        self.name = name or f"script:{self.dir.name}"

    def run(self, task, sandbox, timeout):
        script = self.dir / f"{task.name}.sh"
        if not script.exists():
            return AgentRun(0, f"no script for {task.name}")
        dest = f"{sandbox.private}/agent/{script.name}"
        sandbox.put(script, dest)
        r = sandbox.exec(f"bash {shlex.quote(dest)}", timeout, env=task.env)
        return AgentRun(r.exit_code, r.output)


class FunctionAgent(Agent):
    """Wraps a Python callable f(task, sandbox, timeout) -> AgentRun | None, for in-process agents and tests."""

    def __init__(self, fn: Callable[[Task, Sandbox, float], AgentRun | None], name: str = "function"):
        self.fn = fn
        self.name = name

    def run(self, task, sandbox, timeout):
        return self.fn(task, sandbox, timeout) or AgentRun()


class CodingAgent(Agent):
    """Adapter for the Terminal-Coding-Agent project (pip install coding-agent). Local sandbox only."""

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "high", max_cost_usd: float = 2.0):
        self.model, self.effort, self.max_cost = model, effort, max_cost_usd
        self.name = f"cagent-{model}"

    def run(self, task, sandbox, timeout):
        from coding_agent import Agent as Inner, Approver, Workspace

        inner = Inner(Workspace(sandbox.workspace), model=self.model, effort=self.effort,
                      approver=Approver("yolo"), max_cost_usd=self.max_cost, command_timeout=min(timeout, 300),
                      transcript=False)
        res = inner.run(task.instruction)
        return AgentRun(0 if res.status == "done" else 1, res.final_text, res.usage.cost(self.model),
                        {"status": res.status, "turns": res.usage.turns})


def from_spec(spec: str) -> Agent:
    """Build an agent from a CLI spec: nop, oracle, cagent[:model], cmd:<template> or script:<dir>."""
    if spec == "nop":
        return NopAgent()
    if spec == "oracle":
        return OracleAgent()
    if spec.startswith("cagent"):
        _, _, model = spec.partition(":")
        return CodingAgent(model or "claude-opus-5-5")
    if spec.startswith("cmd:"):
        return CommandAgent(spec[4:])
    if spec.startswith("script:"):
        return ScriptAgent(spec[7:])
    raise ValueError(f"unknown agent {spec!r}; use nop, oracle, cagent[:model], cmd:<command> or script:<dir>")
