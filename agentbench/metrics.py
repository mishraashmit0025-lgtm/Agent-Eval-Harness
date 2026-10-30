"""Scoring: pass@k, per-task summaries, and confidence intervals."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimate of P(at least one of k samples passes) from n samples with c passes.

    1 - C(n-c, k) / C(n, k), computed as a running product so it stays exact for large n
    (Chen et al. 2021, "Evaluating Large Language Models Trained on Code")."""
    if k > n:
        raise ValueError(f"k={k} is larger than the number of samples n={n}")
    if n - c < k:
        return 1.0
    prob_all_fail = 1.0
    for i in range(n - c + 1, n + 1):
        prob_all_fail *= 1.0 - k / i
    return 1.0 - prob_all_fail


@dataclass
class TaskSummary:
    task: str
    n: int
    passes: int
    mean_reward: float
    pass_at: dict[int, float]


def summarize(results: list[dict], ks: tuple[int, ...] = (1, 3, 5)) -> list[TaskSummary]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_task[r["task"]].append(r)
    out = []
    for task, rs in sorted(by_task.items()):
        n = len(rs)
        c = sum(1 for r in rs if r["passed"])
        out.append(TaskSummary(task, n, c, sum(r["reward"] for r in rs) / n,
                               {k: pass_at_k(n, c, k) for k in ks if k <= n}))
    return out


def bootstrap_ci(values: list[float], iters: int = 10_000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap over tasks. Resampling tasks, not trials, because trials of one task are correlated."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(iters))
    return means[int(iters * alpha / 2)], means[min(iters - 1, int(iters * (1 - alpha / 2)))]


def overall(summaries: list[TaskSummary], k: int = 1) -> dict:
    vals = [s.pass_at[k] for s in summaries if k in s.pass_at]
    if not vals:
        return {"k": k, "tasks": 0, "score": 0.0, "ci95": (0.0, 0.0)}
    return {"k": k, "tasks": len(vals), "score": sum(vals) / len(vals), "ci95": bootstrap_ci(vals)}
