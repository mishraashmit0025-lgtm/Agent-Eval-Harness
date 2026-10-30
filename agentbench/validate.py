"""Checks that a task measures what it claims to.

A task is valid when the reference solution passes, doing nothing fails, and the
agent cannot see the verifier or the solution. A task that fails these checks
produces scores that mean nothing, so `abench validate` is meant to run in CI
for every task change."""

from __future__ import annotations

from dataclasses import dataclass, field

from .agents import NopAgent, OracleAgent
from .runner import SandboxFactory, local_sandbox, run_trial
from .task import Task


@dataclass
class Report:
    task: str
    problems: list[str] = field(default_factory=list)
    oracle_rewards: list[float] = field(default_factory=list)
    nop_reward: float | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def static_checks(task: Task) -> list[str]:
    problems = []
    if not task.solution.is_file():
        problems.append("no solution/solve.sh, so nothing proves the task is solvable")
    if not any(task.tests.iterdir()):
        problems.append("tests/ is empty")
    if task.environment.is_dir():
        env_files = {p.name for p in task.environment.rglob("*") if p.is_file()}
        leaked = sorted(env_files & {p.name for p in task.tests.rglob("*") if p.is_file()} - {"__init__.py"})
        if leaked:
            problems.append(f"verifier files also present in environment/: {', '.join(leaked)}")
        if any(p.name == "solve.sh" for p in task.environment.rglob("*")):
            problems.append("environment/ contains solve.sh")
    lower = task.instruction.lower()
    if "solve.sh" in lower or "/tests/" in lower:
        problems.append("instruction refers to the hidden solution or tests")
    return problems


def validate(task: Task, oracle_runs: int = 2, make_sandbox: SandboxFactory = local_sandbox) -> Report:
    rep = Report(task.name, static_checks(task))
    if not task.solution.is_file():
        return rep
    for i in range(oracle_runs):
        r = run_trial(task, OracleAgent(), i, make_sandbox)
        rep.oracle_rewards.append(r["reward"])
        if r["error"]:
            rep.problems.append(f"oracle run {i}: {r['error']}")
        elif not r["passed"]:
            tail = (r.get("verifier_log") or "").strip().splitlines()[-3:]
            rep.problems.append(f"oracle run {i} failed (reward {r['reward']}): {' | '.join(tail)}")
    if len(set(rep.oracle_rewards)) > 1:
        rep.problems.append(f"oracle is not deterministic: rewards {rep.oracle_rewards}")
    r = run_trial(task, NopAgent(), 0, make_sandbox)
    rep.nop_reward = r["reward"]
    if r["error"]:
        rep.problems.append(f"nop run: {r['error']}")
    elif r["reward"] > 0:
        rep.problems.append(f"doing nothing scores {r['reward']}; the verifier must fail an untouched workspace")
    return rep
