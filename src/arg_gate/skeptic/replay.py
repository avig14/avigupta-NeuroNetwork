"""Skeptic (plan 6.5): replay each hard finding and try to refute it.

Prototype deviation: the plan's skeptic is an LLM agent. Here it is deterministic:
  1. REPLAY: re-run the exact trial (same scenario + seed) in a FRESH sandbox and check the
     same finding kind reappears.
  2. COUNTER-EVIDENCE: confirm the evidence row cited by the finding really exists in the
     replayed post-state (guards against a grader/evidence mismatch).
A finding that fails either step is 'unconfirmed' and cannot BLOCK on its own
(it downgrades the verdict to SHIP-WITH-CONDITIONS). Ablation D measures what this changes.
"""
from __future__ import annotations

from pathlib import Path

from ..models import Scenario
from ..policy import Policy
from ..sandbox.executor import Sandbox, run_trial


def _evidence_present(finding: dict, rec) -> bool:
    ev = finding["evidence"]
    table, row = ev.get("table"), ev.get("row")
    if table and row:
        pk = {"refunds": "refund_id", "outbox": "msg_id"}.get(table)
        if pk and pk in row:
            return str(row[pk]) in rec.post.get(table, {})
    if ev.get("where") == "final_message":
        return ev.get("token", "") in rec.final_message
    return True  # claim/state-change evidence is re-derived by the replayed grader itself


async def skeptic_review(agent_cls, findings: list[dict], scenarios: dict[str, Scenario],
                         policy: Policy, workdir: Path, clean_db: Path, transport: str,
                         l0c: bool) -> dict:
    """Returns {'findings': [...with status...], 'confirmed': n, 'unconfirmed': n}."""
    hard = [f for f in findings if f["severity"] == "hard"]
    by_trial: dict[tuple[str, int], list[dict]] = {}
    for f in hard:
        by_trial.setdefault((f["scenario_id"], f["trial_idx"]), []).append(f)
    confirmed = unconfirmed = 0
    async with Sandbox(workdir / "skeptic", clean_db, transport) as sb:
        for (sid, idx), fs in by_trial.items():
            rec = await run_trial(agent_cls, scenarios[sid], idx, sb, policy, l0c)
            replay_kinds = {f["kind"] for f in rec.findings if f["severity"] == "hard"}
            for f in fs:
                ok = f["kind"] in replay_kinds and _evidence_present(f, rec) if not rec.error else False
                f["status"] = "confirmed" if ok else "unconfirmed"
                confirmed += ok
                unconfirmed += (not ok)
    return {"findings": findings, "confirmed": confirmed, "unconfirmed": unconfirmed}
