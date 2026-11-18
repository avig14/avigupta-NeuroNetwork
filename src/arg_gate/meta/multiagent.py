"""Plan section 9 experiment: v1 (single graph) vs v2 (multi: policy + security as sub-agents).

The prediction was written BEFORE any multi-agent code or run: docs/multi_agent_prediction.md.
This runner records that file's FULL sha256 + mtime in the result so the order is checkable, then checks each
numbered prediction against the measured numbers. A prediction that fails is reported as failed.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..orchestrator.graph import run_audit
from .evals import MANIFEST, _audit

PREDICTION = Path("docs/multi_agent_prediction.md")
# The fleet the prediction was written for (18 agents). 6 dev agents were added later (24-case floor).
ORIGINAL_18_EXCLUDED = {"dev/clean2_verbose.py", "dev/clean3_terse.py", "dev/d10_double_refund.py",
                        "dev/d11_b64_leak.py", "dev/d12_cross_address.py", "dev/d13_overclaim_email.py"}
FAULTS = [("security", "crash"), ("policy", "crash"), ("security", "drop_field"), ("policy", "bad_type")]
FAULT_TARGETS = ["dev/clean.py", "dev/d04_leaky.py"]


def _cost(res: dict) -> dict:
    ts = res["trials"]
    return {"trials": len(ts), "tool_calls": sum(len(t["tool_calls"]) for t in ts),
            "handoff_bytes": sum(h["bytes_req"] + h["bytes_resp"] for h in res.get("handoffs", [])),
            "handoff_failures": len(res.get("handoff_failures", []))}


async def _one(rel: str, workdir: Path, **over) -> dict:
    a = await _audit(rel, workdir, **over)
    if not a["ok"]:
        return {"ok": False, "wall": a["wall"], "error": a["error"]}
    return {"ok": True, "wall": a["wall"], "verdict": a["res"]["verdict"]["verdict"], **_cost(a["res"])}


async def run_multiagent(workdir: Path, out: Path) -> dict:
    pred_bytes = PREDICTION.read_bytes()
    pred = {"file": str(PREDICTION), "sha256": hashlib.sha256(pred_bytes).hexdigest(),
            "mtime_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(PREDICTION.stat().st_mtime))}
    agents = list(json.loads(MANIFEST.read_text(encoding="utf-8"))["agents"])
    workdir.mkdir(parents=True, exist_ok=True)

    # 1) healthy runs: same fleet, same seeds, same k
    rows = []
    for rel in agents:
        v1 = await _one(rel, workdir / "v1", arch="single")
        v2 = await _one(rel, workdir / "v2", arch="multi")
        rows.append({"agent": rel, "v1": v1, "v2": v2,
                     "same_verdict": v1.get("verdict") == v2.get("verdict")})
    orig = [r for r in rows if r["agent"] not in ORIGINAL_18_EXCLUDED]
    ok = [r for r in rows if r["v1"]["ok"] and r["v2"]["ok"]]
    w1, w2 = sum(r["v1"]["wall"] for r in ok), sum(r["v2"]["wall"] for r in ok)

    # 2) injected faults (crash is comparable in both; drop_field/bad_type only exist where a contract exists)
    faults = []
    for rel in FAULT_TARGETS:
        for camp, kind in FAULTS:
            f = {"campaign": camp, "kind": kind}
            v1 = (await _one(rel, workdir / "f1", arch="single", inject_fault=f)) if kind == "crash" else \
                {"ok": None, "note": "n/a: v1 has no handoff contract to corrupt"}
            v2 = await _one(rel, workdir / "f2", arch="multi", inject_fault=f)
            faults.append({"agent": rel, "fault": f, "v1": v1, "v2": v2})

    # 3) toy 'wide' variant: scenarios replicated x4 (NOT a real many-tool audit)
    wide = {}
    for arch in ("single", "multi"):
        wide[arch] = await _one("dev/clean.py", workdir / f"wide_{arch}", arch=arch, pad=4, max_trials=3000)

    healthy_incidents = sum(r["v2"].get("handoff_failures", 0) for r in ok)
    v2_fault_incidents = sum(f["v2"].get("handoff_failures", 0) for f in faults if f["v2"]["ok"])
    v1_crashes = sum(1 for f in faults if f["v1"]["ok"] is False)
    v1_crash_cases = sum(1 for f in faults if f["v1"]["ok"] is not None)
    v2_never_crash = all(f["v2"]["ok"] for f in faults)
    v2_not_ship = all(f["v2"].get("verdict") != "SHIP" for f in faults if f["v2"]["ok"])
    same18 = sum(r["same_verdict"] for r in orig)
    ratio = round(w2 / w1, 3) if w1 else None

    checks = {
        "1_verdicts_identical_on_>=17_of_18": {"held": same18 >= 17, "measured": f"{same18}/{len(orig)} identical",
                                              "all_24": f"{sum(r['same_verdict'] for r in rows)}/{len(rows)}"},
        "2_cost_wall_x1.05-1.5_trials_tools_identical": {
            "held": ratio is not None and 1.05 <= ratio <= 1.5 and all(
                r["v1"]["trials"] == r["v2"]["trials"] and r["v1"]["tool_calls"] == r["v2"]["tool_calls"] for r in ok),
            "measured": {"wall_ratio_v2_over_v1": ratio, "wall_v1_s": round(w1, 1), "wall_v2_s": round(w2, 1),
                         "handoff_bytes_mean_v2": round(sum(r["v2"]["handoff_bytes"] for r in ok) / max(1, len(ok)))}},
        "3_no_latency_speedup": {"held": ratio is not None and ratio >= 1.0, "measured": {"wall_ratio": ratio}},
        "4_error_amplification_better_in_v2_only_by_fail_closed_design": {
            "held": v2_never_crash and v1_crashes == v1_crash_cases and v2_not_ship,
            "measured": {"v1_audits_crashed_on_injected_crash": f"{v1_crashes}/{v1_crash_cases}",
                         "v2_audits_completed": f"{sum(1 for f in faults if f['v2']['ok'])}/{len(faults)}",
                         "v2_never_SHIP_under_fault": v2_not_ship}},
        "5_lost_context_0_healthy_>0_under_faults": {"held": healthy_incidents == 0 and v2_fault_incidents > 0,
                                                    "measured": {"healthy_v2_handoff_failures": healthy_incidents,
                                                                 "fault_runs_handoff_failures": v2_fault_incidents}},
        "6_wide_audit_untestable_toy_only": {"held": True, "measured": {
            "toy_wide_x4": {a: {k: wide[a].get(k) for k in ("wall", "trials", "verdict")} for a in wide},
            "label": "TOY: scenarios replicated x4. Not many tools. Does NOT test the plan's wide-audit claim."}},
    }
    result = {"prediction_file": pred, "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "agents": len(agents),
              "healthy_runs": rows, "fault_injection": faults, "wide_toy": wide, "checks": checks,
              "disagreements": [r["agent"] for r in rows if not r["same_verdict"]],
              "honest_notes": ["No LLM tokens exist in either version, so the plan's '15x tokens' cannot be tested; "
                               "handoff bytes are a crude stand-in.",
                               "Prediction 4 is a design effect (we chose to fail closed), not a general multi-agent property.",
                               "Wall times are single-machine and noisy; ratios are indicative only."]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result
