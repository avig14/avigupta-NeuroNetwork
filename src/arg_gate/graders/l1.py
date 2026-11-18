"""L1: statistics. pass^k and Wilson confidence intervals (plan 6.4 L1, 2.3 claim C10)."""
from __future__ import annotations

import math
from collections import defaultdict


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion. Returns (lo, hi). n=0 -> (0, 1)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def pass_hat_k(trials: list[dict]) -> dict:
    """pass^k = share of scenarios where ALL k trials passed (tau-bench style).
    Also reports per-scenario pass rates and the trial-level pass rate with a Wilson CI."""
    by_scn: dict[str, list[bool]] = defaultdict(list)
    for t in trials:
        by_scn[t["scenario_id"]].append(bool(t["passed"]))
    if not by_scn:
        return {"pass_hat_k": 1.0, "k": 0, "scenarios": 0, "per_scenario": {}, "trial_pass_rate": 1.0,
                "trial_ci": (0.0, 1.0), "trials": 0}
    per = {s: sum(v) / len(v) for s, v in by_scn.items()}
    all_pass = sum(1 for v in by_scn.values() if all(v))
    n_trials = sum(len(v) for v in by_scn.values())
    n_pass = sum(sum(v) for v in by_scn.values())
    return {
        "pass_hat_k": all_pass / len(by_scn),
        "k": max(len(v) for v in by_scn.values()),
        "scenarios": len(by_scn),
        "per_scenario": per,
        "trial_pass_rate": n_pass / n_trials,
        "trial_ci": wilson(n_pass, n_trials),
        "trials": n_trials,
    }
