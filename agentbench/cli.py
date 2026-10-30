"""abench: run, validate and report on agent evaluations.

    abench validate tasks/
    abench run tasks/ --agent oracle -k 3 -j 8
    abench run tasks/ --agent "cmd:claude -p {instruction} --dangerously-skip-permissions" -k 5 --sandbox docker
    abench report runs/<run>.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import metrics
from .agents import from_spec
from .runner import local_sandbox, run
from .sandbox import DockerSandbox
from .task import discover
from .validate import validate


def load_results(path: Path) -> list[dict]:
    latest: dict[tuple, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            latest[(r["agent"], r["task"], r["attempt"])] = r  # a resumed run's retry replaces the failed record
    return list(latest.values())


def render(results: list[dict], ks=(1, 3, 5)) -> str:
    sums = metrics.summarize(results, ks)
    shown = [k for k in ks if any(k in s.pass_at for s in sums)]
    lines = ["| task | trials | passed | mean reward | " + " | ".join(f"pass@{k}" for k in shown) + " |",
             "|---|---:|---:|---:|" + "---:|" * len(shown)]
    for s in sums:
        cells = " | ".join(f"{s.pass_at[k]:.2f}" if k in s.pass_at else "" for k in shown)
        lines.append(f"| {s.task} | {s.n} | {s.passes} | {s.mean_reward:.2f} | {cells} |")
    lines.append("")
    for k in shown:
        o = metrics.overall(sums, k)
        lines.append(f"pass@{k}: {o['score']:.3f} over {o['tasks']} tasks (95% CI {o['ci95'][0]:.3f} to "
                     f"{o['ci95'][1]:.3f})")
    errors = sum(1 for r in results if r.get("error"))
    timeouts = sum(1 for r in results if r.get("agent_timed_out"))
    cost = sum(r.get("cost_usd") or 0 for r in results)
    lines.append(f"trials: {len(results)}, infrastructure errors: {errors}, agent timeouts: {timeouts}, "
                 f"cost: ${cost:.2f}")
    return "\n".join(lines)


def cmd_run(a) -> int:
    tasks = discover(a.tasks, a.task)
    agent = from_spec(a.agent)
    factory = (lambda t: DockerSandbox(t.environment, image=a.image)) if a.sandbox == "docker" else local_sandbox
    out = Path(a.out or f"runs/{time.strftime('%Y%m%d-%H%M%S')}-{agent.name.replace('/', '_')}.jsonl")
    print(f"{len(tasks)} tasks x {a.k} attempts with {agent.name}, results in {out}", file=sys.stderr)

    def progress(r):
        mark = "PASS" if r["passed"] else ("ERR " if r["error"] else "fail")
        print(f"  {mark} {r['task']} #{r['attempt']} reward={r['reward']:.2f} agent={r.get('agent_seconds', 0)}s",
              file=sys.stderr)

    run(tasks, agent, a.k, a.jobs, factory, out, progress)
    print(render(load_results(out)))
    return 0


def cmd_validate(a) -> int:
    bad = 0
    for t in discover(a.tasks, a.task):
        rep = validate(t, a.oracle_runs)
        status = "ok " if rep.ok else "BAD"
        print(f"{status} {t.name}: oracle {rep.oracle_rewards}, nop {rep.nop_reward}")
        for p in rep.problems:
            print(f"      - {p}")
        bad += not rep.ok
    return 1 if bad else 0


def cmd_report(a) -> int:
    print(render(load_results(Path(a.results))))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="abench")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="evaluate an agent")
    r.add_argument("tasks")
    r.add_argument("--task", action="append", help="only this task (repeatable)")
    r.add_argument("--agent", default="oracle", help="nop, oracle, cagent[:model], cmd:<template> or script:<dir>")
    r.add_argument("-k", type=int, default=1, help="attempts per task")
    r.add_argument("-j", "--jobs", type=int, default=4, help="trials in parallel")
    r.add_argument("--sandbox", choices=["local", "docker"], default="local")
    r.add_argument("--image", default="agentbench-base:latest")
    r.add_argument("--out", help="JSONL results file; an existing file is resumed")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("validate", help="check that tasks are solvable and not trivially passed")
    v.add_argument("tasks")
    v.add_argument("--task", action="append")
    v.add_argument("--oracle-runs", type=int, default=2)
    v.set_defaults(fn=cmd_validate)

    rp = sub.add_parser("report", help="summarize a results file")
    rp.add_argument("results")
    rp.set_defaults(fn=cmd_report)

    a = p.parse_args(argv)
    return a.fn(a)
