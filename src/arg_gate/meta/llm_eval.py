"""Meta-eval with a real LLM (plan 8.3 #1 Baseline 1, and 8.2 B-lite): the whole 24-agent fleet through
  (a) the deterministic gate,
  (b) the L3 LLM judge (sees tool calls + DB diff + reply),
  (c) a real LLM text-only baseline (sees only the request and the reply; plan Baseline 1).

Agent-level flag = "at least one trial flagged". Ground truth = fleet label (defect/clean) from fleet/manifest.json.

HONEST LABELS:
  * Judge and baseline are an open-weight model on Groq (gpt-oss-120b). The fleet agents are scripts, so family bias is untested.
  * Fleet agents are scripted by the gate's author, so recall here measures the judge on KNOWN, simple defects.
  * k=1 trial per scenario (cost). pass^k flakiness (d06, h06) is not what this measures.
  * 5 clean agents -> the false-flag Wilson interval is wide. A judge flag on a clean agent is an extra
    SHIP-WITH-CONDITIONS for a human, not a BLOCK.
  * This is NOT the plan's B calibration (that needs human labels).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from ..graders import l3
from ..graders.l1 import wilson
from ..llm import METER, default_model
from ..orchestrator.graph import run_audit
from ..policy import load_policy
from .evals import FLEET, MANIFEST, _rate

MAX_TRIALS_PER_AGENT = 40


def _pick(trials: list[dict], scenarios: dict, cap: int) -> list[dict]:
    """First trial per scenario, then round-robin across campaigns so a small cap still covers every campaign.
    Deterministic. NOT chosen by outcome (no peeking at which trials failed)."""
    seen, by_camp = set(), {}
    for t in trials:
        sid = t["scenario_id"]
        if sid in scenarios and sid not in seen and not t["error"]:
            seen.add(sid)
            by_camp.setdefault(scenarios[sid]["campaign"], []).append(t)
    out, queues = [], list(by_camp.values())
    while queues and len(out) < cap:
        for q in list(queues):
            out.append(q.pop(0))
            if not q:
                queues.remove(q)
            if len(out) >= cap:
                break
    return out


async def run_llm_eval(workdir: Path, out: Path, only: list[str] | None = None, model: str | None = None,
                       concurrency: int = 12, per_agent: int = MAX_TRIALS_PER_AGENT) -> dict:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))["agents"]
    policy = load_policy("policies/retail.md")
    rows = []
    t0 = time.perf_counter()
    METER.reset()
    for rel, e in man.items():
        if only and not any(o in rel for o in only):
            continue
        res = await run_audit({"target": str(FLEET / rel), "policy": "policies/retail.md", "mode": "full", "k": 1,
                               "workdir": str(workdir), "out_dir": str(workdir / "out"), "human_gate": "off",
                               "adversary": False, "l3": False})
        scenarios = {sd["id"]: sd for scns in res["plan"].values() for sd in scns}
        picked = _pick(res["trials"], scenarios, per_agent)
        pairs = [(scenarios[t["scenario_id"]], t) for t in picked]
        sem = asyncio.Semaphore(concurrency)

        async def base(scn, t):
            async with sem:
                return await l3.baseline_judge(scn["prompt"], t["final_message"], model)
        judged, based = await asyncio.gather(l3.judge_many(pairs, policy, model, concurrency),
                                             asyncio.gather(*(base(s, t) for s, t in pairs)))
        j_flags = [(t["scenario_id"], v) for (s, t), v in zip(pairs, judged) if v.get("violation")]
        b_flags = [(t["scenario_id"], v) for (s, t), v in zip(pairs, based) if v.get("acceptable") is False]
        errs = sum(1 for v in judged if "error" in v) + sum(1 for v in based if "error" in v)
        det_hard_trials = {t["scenario_id"] for t in picked if any(f["severity"] == "hard" for f in t["findings"])}
        rows.append({
            "agent": rel, "label": e["label"], "role": e["role"],
            "det_verdict": res["verdict"]["verdict"],
            "trials_judged": len(pairs), "errors": errs,
            "l3_flagged_trials": len(j_flags), "baseline_flagged_trials": len(b_flags),
            "l3_agent_flag": bool(j_flags), "baseline_agent_flag": bool(b_flags),
            "l3_on_det_hard": sum(1 for sid, _ in j_flags if sid in det_hard_trials),
            "l3_judge_only": [{"scenario": sid, "kind": v.get("kind"), "conf": v.get("confidence"),
                               "evidence": v.get("evidence", "")} for sid, v in j_flags if sid not in det_hard_trials][:6],
            "det_hard_trials": len(det_hard_trials),
            "l3_missed_det_hard": sum(1 for sid in det_hard_trials if sid not in {x for x, _ in j_flags}),
        })
        print(f"{rel:<34} {e['label']:<6} det={res['verdict']['verdict']:<21} l3={len(j_flags):>2} base={len(b_flags):>2} "
              f"err={errs}", flush=True)
    summary = _summarise(rows)
    result = {"model": model or default_model(), "trials_per_agent_cap": per_agent, "wall_s": round(time.perf_counter() - t0, 1),
              "tokens": METER.snapshot(), "rows": rows, "summary": summary,
              "honest": __doc__.strip().split("HONEST LABELS:")[1].strip()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["summary_text"] = json.dumps(summary, indent=2)
    return result


def _summarise(rows: list[dict]) -> dict:
    d = [r for r in rows if r["label"] == "defect"]
    c = [r for r in rows if r["label"] == "clean"]

    def block(flag) -> dict:
        return {"recall": _rate(sum(1 for r in d if flag(r)), len(d)),
                "false_flag_on_clean": _rate(sum(1 for r in c if flag(r)), len(c))}
    return {
        "deterministic_gate": block(lambda r: r["det_verdict"] != "SHIP"),
        "l3_judge_alone": block(lambda r: r["l3_agent_flag"]),
        "llm_text_only_baseline": block(lambda r: r["baseline_agent_flag"]),
        "gate_plus_l3 (verdict != SHIP)": block(lambda r: r["det_verdict"] != "SHIP" or r["l3_agent_flag"]),
        "defects_missed_by_det_but_flagged_by_l3": [r["agent"] for r in d if r["det_verdict"] == "SHIP" and r["l3_agent_flag"]],
        "defects_missed_by_l3": [r["agent"] for r in d if not r["l3_agent_flag"]],
        "clean_agents_flagged_by_l3": [r["agent"] for r in c if r["l3_agent_flag"]],
        "clean_agents_flagged_by_baseline": [r["agent"] for r in c if r["baseline_agent_flag"]],
        "judge_errors": sum(r["errors"] for r in rows),
        "l3_missed_det_hard_trials": sum(r["l3_missed_det_hard"] for r in rows),
        "l3_on_det_hard_trials": sum(r["l3_on_det_hard"] for r in rows),
    }
