"""Runs trials: (task, attempt) pairs, in parallel, each in a fresh sandbox."""

from __future__ import annotations

import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from .agents import Agent, AgentRun
from .sandbox import LocalSandbox, Sandbox
from .task import Task
from .verify import verify

SandboxFactory = Callable[[Task], Sandbox]
GRACE_SECONDS = 30.0  # extra time an agent gets after its timeout before the trial is abandoned


def local_sandbox(task: Task) -> Sandbox:
    return LocalSandbox(task.environment)


def _run_agent(agent: Agent, task: Task, sandbox: Sandbox, timeout: float) -> tuple[AgentRun | None, bool]:
    """Runs the agent in a worker thread so in-process agents get a deadline too.

    Subprocess agents are killed by the sandbox at the timeout; the extra grace here
    covers agents that ignore it. Returns (run, still_running)."""
    box: dict = {}

    def target():
        try:
            box["run"] = agent.run(task, sandbox, timeout)
        except Exception:
            box["error"] = traceback.format_exc()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout + GRACE_SECONDS)
    if t.is_alive():
        return None, True
    if "error" in box:
        return AgentRun(1, "agent raised:\n" + box["error"]), False
    return box["run"], False


def run_trial(task: Task, agent: Agent, attempt: int, make_sandbox: SandboxFactory = local_sandbox) -> dict:
    rec = {"task": task.name, "agent": agent.name, "attempt": attempt, "reward": 0.0, "passed": False,
           "error": None, "started": time.time()}
    try:
        with make_sandbox(task) as sb:
            t0 = time.monotonic()
            run, hung = _run_agent(agent, task, sb, task.agent_timeout)
            rec["agent_seconds"] = round(time.monotonic() - t0, 2)
            if hung:
                # the agent may still be writing to the workspace, so verifying now would be meaningless
                rec.update(agent_timed_out=True, error="agent did not stop after its timeout")
                return rec
            rec.update(agent_exit=run.exit_code, agent_timed_out=run.exit_code is None, cost_usd=run.cost_usd,
                       agent_log=run.log[-4000:], **run.extra)
            v = verify(task, sb)
            rec.update(reward=v.reward, passed=v.passed, verifier_exit=v.exit_code,
                       verify_seconds=round(v.seconds, 2), tests_passed=v.tests_passed, tests_failed=v.tests_failed,
                       verifier_log=v.output[-4000:])
    except Exception as e:  # infrastructure failure: recorded, never counted as a pass
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec


def run(tasks: list[Task], agent: Agent, attempts: int = 1, concurrency: int = 4,
        make_sandbox: SandboxFactory = local_sandbox, out: Path | None = None,
        progress: Callable[[dict], None] | None = None) -> list[dict]:
    """Runs every task `attempts` times. With `out`, results stream to a JSONL file and
    a rerun with the same file skips trials that already finished, so long runs can resume."""
    done: dict[tuple[str, int], dict] = {}
    if out is not None and out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("agent") == agent.name and not r.get("error"):
                done[(r["task"], r["attempt"])] = r
    todo = [(t, a) for t in tasks for a in range(attempts) if (t.name, a) not in done]
    lock = threading.Lock()
    results = list(done.values())

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(run_trial, t, agent, a, make_sandbox) for t, a in todo]
        for fut in as_completed(futures):
            rec = fut.result()
            with lock:
                results.append(rec)
                if out is not None:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with open(out, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec) + "\n")
            if progress:
                progress(rec)
    return sorted(results, key=lambda r: (r["task"], r["attempt"]))
