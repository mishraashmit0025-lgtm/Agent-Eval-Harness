import dataclasses
import json
import os
import tempfile
import time
from math import comb
from pathlib import Path

import pytest

from agentbench import metrics, runner
from agentbench.agents import AgentRun, CommandAgent, FunctionAgent, NopAgent, OracleAgent, ScriptAgent
from agentbench.cli import load_results, render
from agentbench.sandbox import DockerSandbox, LocalSandbox, docker_available
from agentbench.task import Task, TaskError, discover
from agentbench.validate import validate

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"


def make_task(tmp_path, test_body, env_files=None, solve="true", **meta):
    d = Path(tempfile.mkdtemp(dir=tmp_path))
    (d / "environment").mkdir()
    (d / "tests").mkdir()
    (d / "solution").mkdir()
    lines = [f'name = "{meta.pop("name", "toy")}"'] + [f"{k} = {v!r}" for k, v in meta.items()]
    (d / "task.toml").write_text("\n".join(lines) + "\n")
    (d / "instruction.md").write_text("Write ok.txt containing ok.")
    for name, text in (env_files or {}).items():
        (d / "environment" / name).write_text(text)
    (d / "tests" / "test_it.py").write_text(test_body)
    (d / "solution" / "solve.sh").write_text(solve + "\n")
    return Task.load(d)


OK_TEST = """import os
from pathlib import Path

def test_ok():
    assert (Path(os.environ["WORKSPACE"]) / "ok.txt").read_text().strip() == "ok"
"""


# ------------------------------------------------------------------ metrics
@pytest.mark.parametrize("n,c,k", [(5, 0, 1), (5, 5, 3), (10, 3, 1), (10, 3, 5), (20, 1, 10), (7, 6, 2), (100, 37, 10)])
def test_pass_at_k_matches_combinatorics(n, c, k):
    exact = 1 - comb(n - c, k) / comb(n, k)
    assert metrics.pass_at_k(n, c, k) == pytest.approx(exact, abs=1e-12)


def test_pass_at_1_is_the_pass_rate():
    assert metrics.pass_at_k(8, 3, 1) == pytest.approx(3 / 8)
    with pytest.raises(ValueError):
        metrics.pass_at_k(3, 1, 5)


def test_summary_and_bootstrap():
    results = [{"task": "a", "passed": i < 2, "reward": float(i < 2)} for i in range(4)]
    results += [{"task": "b", "passed": False, "reward": 0.5} for _ in range(4)]
    a, b = metrics.summarize(results, ks=(1, 3))
    assert (a.n, a.passes, a.pass_at[1]) == (4, 2, 0.5) and a.pass_at[3] == 1.0
    assert b.mean_reward == 0.5 and b.pass_at[1] == 0.0
    lo, hi = metrics.bootstrap_ci([0.0, 1.0, 0.5, 0.25])
    assert 0 <= lo <= 0.4375 <= hi <= 1


# ------------------------------------------------------------------ tasks
def test_task_loading_errors(tmp_path):
    with pytest.raises(TaskError, match="task.toml"):
        Task.load(tmp_path)
    t = make_task(tmp_path, OK_TEST, agent_timeout=5)
    assert t.agent_timeout == 5.0 and t.name == "toy"
    with pytest.raises(TaskError, match="unknown tasks"):
        discover(TASKS, ["no-such-task"])
    assert len(discover(TASKS)) == 5


# ------------------------------------------------------------------ trials and verification
def test_oracle_and_nop(tmp_path):
    t = make_task(tmp_path, OK_TEST, solve="echo ok > ok.txt")
    assert runner.run_trial(t, OracleAgent(), 0)["passed"]
    rec = runner.run_trial(t, NopAgent(), 0)
    assert not rec["passed"] and rec["tests_failed"] == 1


def test_agent_never_sees_the_tests_or_solution(tmp_path):
    t = make_task(tmp_path, OK_TEST, solve="echo ok > ok.txt")
    seen = {}

    def snoop(task, sb, timeout):
        root = Path(sb.workspace).parent
        seen["files"] = sorted(p.name for p in root.rglob("*") if p.is_file())
        (Path(sb.workspace) / "ok.txt").write_text("ok")

    rec = runner.run_trial(t, FunctionAgent(snoop), 0)
    assert rec["passed"]
    assert "test_it.py" not in seen["files"] and "solve.sh" not in seen["files"]


def test_planted_conftest_cannot_fake_a_pass(tmp_path):
    t = make_task(tmp_path, OK_TEST)
    cheat = (
        "import pytest\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_runtest_call(item):\n"
        "    item.runtest = lambda: None\n"
        "def pytest_collection_modifyitems(items):\n"
        "    items.clear()\n"
    )

    def cheater(task, sb, timeout):
        ws = Path(sb.workspace)
        (ws / "conftest.py").write_text(cheat)
        (ws / "pytest.ini").write_text("[pytest]\naddopts = --co\n")
        (Path(sb.private).parent / "conftest.py").write_text(cheat)  # one level above the verifier too

    rec = runner.run_trial(t, FunctionAgent(cheater), 0)
    assert not rec["passed"] and rec["tests_failed"] == 1


def test_secrets_are_not_passed_to_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-very-secret")
    t = make_task(tmp_path, OK_TEST)
    with LocalSandbox(t.environment) as sb:
        r = sb.exec('echo "key=[${ANTHROPIC_API_KEY:-}] ws=$WORKSPACE"', 10)
    assert "key=[]" in r.output and "ws=" in r.output


def test_command_agent_gets_the_instruction(tmp_path):
    t = make_task(tmp_path, OK_TEST)
    agent = CommandAgent('echo {instruction} > said.txt; [ -n "$TASK_INSTRUCTION" ] && echo ok > ok.txt')
    with LocalSandbox(t.environment, keep=True) as sb:
        agent.run(t, sb, 10)
        assert (Path(sb.workspace) / "said.txt").read_text().strip() == t.instruction
    sb.keep = False
    sb.close()
    assert runner.run_trial(t, agent, 0)["passed"]


def test_command_timeout_kills_the_agent(tmp_path):
    t = dataclasses.replace(make_task(tmp_path, OK_TEST), agent_timeout=1)
    start = time.monotonic()
    rec = runner.run_trial(t, CommandAgent("sleep 20; echo ok > ok.txt"), 0)
    assert rec["agent_timed_out"] and not rec["passed"]
    assert time.monotonic() - start < 15


def test_hung_in_process_agent_is_abandoned(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "GRACE_SECONDS", 0.2)
    t = dataclasses.replace(make_task(tmp_path, OK_TEST), agent_timeout=0.3)
    rec = runner.run_trial(t, FunctionAgent(lambda *a: time.sleep(3)), 0)
    assert rec["agent_timed_out"] and rec["error"] and not rec["passed"]


def test_crashing_agent_is_recorded_not_raised(tmp_path):
    t = make_task(tmp_path, OK_TEST)

    def boom(*a):
        raise RuntimeError("model API down")

    rec = runner.run_trial(t, FunctionAgent(boom), 0)
    assert rec["agent_exit"] == 1 and "model API down" in rec["agent_log"] and not rec["passed"]


def test_partial_credit_from_reward_file(tmp_path):
    t = make_task(tmp_path, "")
    (t.tests / "test_it.py").unlink()
    (t.tests / "test.sh").write_text('echo 0.4 > "$REWARD_FILE"\nexit 1\n')
    rec = runner.run_trial(t, NopAgent(), 0)
    assert rec["reward"] == pytest.approx(0.4) and not rec["passed"]


def test_verifier_timeout_scores_zero(tmp_path):
    t = make_task(tmp_path, "")
    t = dataclasses.replace(t, verifier_timeout=1)
    (t.tests / "test_it.py").unlink()
    (t.tests / "test.sh").write_text("sleep 10\n")
    rec = runner.run_trial(t, NopAgent(), 0)
    assert rec["reward"] == 0 and rec["verifier_exit"] is None


# ------------------------------------------------------------------ runs, resume, report
def test_run_is_resumable_and_reports(tmp_path):
    t = make_task(tmp_path, OK_TEST, solve="echo ok > ok.txt")
    out = tmp_path / "res.jsonl"
    calls = []

    def flaky(task, sb, timeout):
        calls.append(1)
        if len(calls) % 2:
            (Path(sb.workspace) / "ok.txt").write_text("ok")

    agent = FunctionAgent(flaky, name="flaky")
    first = runner.run([t], agent, attempts=4, concurrency=1, out=out)
    assert len(first) == 4 and sum(r["passed"] for r in first) == 2
    again = runner.run([t], agent, attempts=4, concurrency=1, out=out)
    assert len(calls) == 4 and len(again) == 4  # nothing re-ran
    table = render(load_results(out), ks=(1, 3))
    assert "| toy | 4 | 2 | 0.50 | 0.50 | 1.00 |" in table


# ------------------------------------------------------------------ validation
def test_validate_flags_weak_and_broken_tasks(tmp_path):
    weak = make_task(tmp_path, "def test_nothing():\n    pass\n", solve="true")
    rep = validate(weak, oracle_runs=1)
    assert not rep.ok and any("doing nothing scores" in p for p in rep.problems)

    broken = make_task(tmp_path, OK_TEST, solve="echo nope > ok.txt")
    rep = validate(broken, oracle_runs=1)
    assert not rep.ok and any("oracle run 0 failed" in p for p in rep.problems)


def test_validate_flags_leaked_tests(tmp_path):
    t = make_task(tmp_path, OK_TEST, env_files={"test_it.py": "leaked"}, solve="echo ok > ok.txt")
    rep = validate(t, oracle_runs=1)
    assert any("verifier files also present" in p for p in rep.problems)


@pytest.mark.parametrize("task", sorted(p.name for p in TASKS.iterdir() if (p / "task.toml").exists()))
def test_bundled_tasks_are_valid(task):
    rep = validate(Task.load(TASKS / task), oracle_runs=1)
    assert rep.ok, rep.problems


def test_naive_baselines_fail_every_bundled_task(tmp_path):
    results = runner.run(discover(TASKS), ScriptAgent(str(ROOT / "baselines" / "naive")), concurrency=5)
    assert [r["passed"] for r in results] == [False] * 5
    assert all(r["error"] is None for r in results)


@pytest.mark.skipif(not (docker_available() and os.environ.get("ABENCH_DOCKER_TESTS")),
                    reason="needs Docker and ABENCH_DOCKER_TESTS=1 (the image is built in CI)")
def test_docker_sandbox_runs_a_task():
    task = Task.load(TASKS / "pagination-bug")
    rep = validate(task, oracle_runs=1, make_sandbox=lambda t: DockerSandbox(t.environment))
    assert rep.ok, rep.problems
    with DockerSandbox(task.environment) as sb:
        r = sb.exec("curl -sS https://example.com || python3 -c 'import urllib.request as u; u.urlopen(\"https://example.com\", timeout=5)'", 20)
        assert r.exit_code != 0  # no network inside the sandbox
