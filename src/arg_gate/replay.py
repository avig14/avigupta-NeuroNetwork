"""`arg-gate replay evidence.json`: re-run the trials behind a verdict and check they reproduce.

Why: plan 5.1 promises "replayable evidence". A trial is fully determined by (scenario, trial_seed, target code,
policy), so re-running it must give the same pass/fail and the same findings. If it does not, either the target
changed (we compare file hashes and say so) or the agent is non-deterministic and the evidence is weak.
This is a faithfulness check on our own evidence, not a new grader.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .orchestrator.graph import _scn
from .policy import load_policy
from .sandbox.executor import Sandbox, ensure_clean_db, load_agent_class, run_trial


def _sig(findings: list[dict]) -> list[list[str]]:
    return sorted([f["kind"], f["severity"]] for f in findings)


def _select(pack: dict, scenario: str | None, everything: bool) -> list[dict]:
    chosen = []
    for t in pack["trials"]:
        if scenario and t["scenario_id"] != scenario:
            continue
        if everything or scenario or t["findings"] or not t["passed"]:
            chosen.append(t)
    return chosen


async def replay(evidence: Path, workdir: Path, scenario: str | None = None, everything: bool = False) -> dict:
    pack = json.loads(Path(evidence).read_text(encoding="utf-8"))
    for key in ("scenarios", "replay_config", "target_sha256"):
        if key not in pack:
            raise ValueError(f"evidence file has no {key!r}: it was written by an older version and cannot be replayed")
    target = pack["profile"]["target"]
    cfgs = pack["replay_config"]
    now = hashlib.sha256(Path(target).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    policy = load_policy(cfgs["policy"])
    agent_cls = load_agent_class(target)
    clean = ensure_clean_db(workdir)
    rows = []
    async with Sandbox(workdir / "replay", clean, cfgs["transport"]) as sb:
        for t in _select(pack, scenario, everything):
            scn = _scn(pack["scenarios"][t["scenario_id"]])
            rec = await run_trial(agent_cls, scn, t["trial_idx"], sb, policy, cfgs["l0c"], cfgs["l0"])
            new = rec.to_dict()
            same = (new["passed"] == t["passed"] and _sig(new["findings"]) == _sig(t["findings"])
                    and new["trial_seed"] == t["trial_seed"])
            rows.append({"scenario_id": t["scenario_id"], "trial_idx": t["trial_idx"], "reproduced": same,
                         "orig_passed": t["passed"], "new_passed": new["passed"],
                         "orig_findings": _sig(t["findings"]), "new_findings": _sig(new["findings"])})
    ok = [r["reproduced"] for r in rows]
    return {"evidence": str(evidence), "target": target, "target_changed": now != pack["target_sha256"],
            "verdict_in_file": pack["verdict"]["verdict"], "replayed": len(rows), "reproduced": sum(ok),
            "all_reproduced": bool(rows) and all(ok), "rows": rows}
