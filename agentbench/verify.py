"""Runs a task's hidden verifier after the agent is done."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from .sandbox import Sandbox
from .task import Task


@dataclass
class Verdict:
    reward: float  # 0..1
    exit_code: int | None
    output: str
    seconds: float
    tests_passed: int = 0
    tests_failed: int = 0

    @property
    def passed(self) -> bool:
        return self.reward >= 1.0


SUMMARY = re.compile(r"(\d+) (passed|failed|error)")


def verify(task: Task, sandbox: Sandbox) -> Verdict:
    tests_dir = f"{sandbox.private}/tests"
    reward_file = f"{sandbox.private}/reward.txt"
    sandbox.put(task.tests, tests_dir)
    q = shlex.quote
    if (task.tests / "test.sh").exists():
        cmd = f"bash {q(tests_dir + '/test.sh')}"
    else:
        # -I keeps the workspace off sys.path and ignores PYTHON* variables; --confcutdir and running from the
        # tests directory keep pytest from loading a conftest.py or pytest.ini the agent left in the workspace
        cmd = (f"{q(sandbox.python)} -I -m pytest -q -p no:cacheprovider --confcutdir={q(tests_dir)} "
               f"--rootdir={q(tests_dir)} {q(tests_dir)}")
    env = {**task.env, "TESTS_DIR": tests_dir, "REWARD_FILE": reward_file, "PYTHON": sandbox.python}
    r = sandbox.exec(cmd, task.verifier_timeout, env=env, cwd=tests_dir)

    passed = failed = 0
    for n, kind in SUMMARY.findall(r.output.splitlines()[-1] if r.output.strip() else ""):
        if kind == "passed":
            passed = int(n)
        else:
            failed += int(n)

    if r.timed_out:
        reward = 0.0
    else:
        reward = 1.0 if r.exit_code == 0 else 0.0
        partial = sandbox.exec(f"cat {q(reward_file)} 2>/dev/null", 10)
        if partial.exit_code == 0 and partial.output.strip():
            try:
                reward = min(1.0, max(0.0, float(partial.output.strip())))
            except ValueError:
                pass  # a malformed reward file falls back to the exit code
    return Verdict(reward, r.exit_code, r.output, r.seconds, passed, failed)
