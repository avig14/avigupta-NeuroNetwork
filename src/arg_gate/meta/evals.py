"""Meta-evals: evaluate the evaluator (plan section 8).

Implemented: A (seeded-defect fleet), D (skeptic ablation + evidence faithfulness),
F (self-consistency, 3 audits), G (orchestrator health, from our own records), I (deltas vs Baseline 1),
plus 8.3 #2 (layer removed: L0c off).
NOT implemented (need an LLM key / human labelers / time): B judge calibration, C mutation score.

READ THIS BEFORE QUOTING ANY NUMBER:
  * Fleet agents are scripted by the same author as the graders (plan 8.5 asks for different people).
    The hold-out is therefore biased in the gate's favour.
  * With scripted deterministic agents, F (flip rate) and D (skeptic delta) are expected to be ~0.
    They test plumbing, not the stability or value of the gate on real LLM agents.
  * Small n: Wilson intervals are wide. They are reported next to every rate.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from ..graders.l1 import wilson
from ..orchestrator.graph import run_audit
from ..skeptic.replay import _evidence_present

FLEET = Path("fleet")
MANIFEST = FLEET / "manifest.json"
REPS_F = 3


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _is_clean(p: Path) -> bool:
    n = p.stem
    return n.startswith("clean") or (n[0] == "c" and n[1:2].isdigit())


def freeze(fleet: Path = FLEET) -> dict:
    """Write fleet/manifest.json: sha256 + ground-truth label per agent file (plan 8.5: freeze first)."""
    entries = {}
    for role in ("dev", "holdout"):
        for p in sorted((fleet / role).glob("*.py")):
            entries[f"{role}/{p.name}"] = {"role": role, "label": "clean" if _is_clean(p) else "defect",
                                           "sha256": _sha(p)}
    man = {"note": "Labels are ground truth authored with the agent. Hold-out must not change after freeze.",
           "agents": entries}
    (fleet / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    return man


def verify_manifest(fleet: Path = FLEET) -> list[str]:
    man = json.loads((fleet / "manifest.json").read_text(encoding="utf-8"))
    bad = []
    for rel, e in man["agents"].items():
        p = fleet / rel
        if not p.exists() or _sha(p) != e["sha256"]:
            bad.append(rel)
    return bad


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "wilson95": [round(lo, 3), round(hi, 3)]}


def _confusion(rows: list[dict]) -> dict:
    defects = [r for r in rows if r["label"] == "defect"]
    clean = [r for r in rows if r["label"] == "clean"]
    flagged_def = sum(1 for r in defects if r["verdict"] != "SHIP")
    flagged_all = sum(1 for r in rows if r["verdict"] != "SHIP")
    return {
        "n_defects": len(defects), "n_clean": len(clean),
        "recall": _rate(flagged_def, len(defects)),
        "precision": _rate(flagged_def, flagged_all),
        "false_SHIP": _rate(sum(1 for r in defects if r["verdict"] == "SHIP"), len(defects)),
        "false_BLOCK": _rate(sum(1 for r in clean if r["verdict"] == "BLOCK"), len(clean)),
        "missed": [r["agent"] for r in defects if r["verdict"] == "SHIP"],
        "wrongly_blocked": [r["agent"] for r in clean if r["verdict"] == "BLOCK"],
    }


def _baseline_verdict(trials: list[dict]) -> str:
    return "BLOCK" if any(not t["text_only_pass"] for t in trials) else "SHIP"


def _faithfulness(res: dict) -> tuple[int, int]:
    """Do cited evidence rows really exist in the trial's post state? Returns (ok, checkable)."""
    by = {(t["scenario_id"], t["trial_idx"]): t for t in res["trials"]}
    ok = checkable = 0
    for f in res["findings"]:
        if f["severity"] != "hard":
            continue
        ev = f["evidence"]
        if not (ev.get("table") and ev.get("row")) and ev.get("where") != "final_message":
            continue
        t = by.get((f["scenario_id"], f["trial_idx"]))
        if t is None:
            continue
        checkable += 1
        ok += bool(_evidence_present(f, SimpleNamespace(post=t["post"], final_message=t["final_message"])))
    return ok, checkable


async def _audit(rel: str, workdir: Path, **over) -> dict:
    cfg = {"target": str(FLEET / rel), "policy": "policies/retail.md", "mode": "full",
           "workdir": str(workdir), "out_dir": str(workdir / "out"), "human_gate": "off", **over}
    t0 = time.perf_counter()
    try:
        res = await run_audit(cfg)
        wall, done = time.perf_counter() - t0, True
    except Exception as exc:  # completion-rate input (meta-eval G)
        return {"ok": False, "wall": time.perf_counter() - t0, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "wall": wall, "res": res}


async def run_all(workdir: Path, out: Path) -> dict:
    bad = verify_manifest()
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))["agents"]
    agents = list(man)
    workdir.mkdir(parents=True, exist_ok=True)

    runs: dict[str, list[dict]] = {}  # agent -> REPS_F full audits (F, A, G, I use these)
    for rel in agents:
        runs[rel] = [await _audit(rel, workdir / f"rep{i}") for i in range(REPS_F)]
    off = {rel: await _audit(rel, workdir / "skeptic_off", skeptic=False) for rel in agents}
    nol0c = {rel: await _audit(rel, workdir / "l0c_off", l0c=False) for rel in agents}

    def rows(src: dict[str, dict]) -> list[dict]:
        out_rows = []
        for rel, a in src.items():
            if not a["ok"]:
                continue
            out_rows.append({"agent": rel, "role": man[rel]["role"], "label": man[rel]["label"],
                             "verdict": a["res"]["verdict"]["verdict"]})
        return out_rows

    A_rows = rows({r: runs[r][0] for r in agents})
    by_role = lambda rs, role: [r for r in rs if r["role"] == role]
    A = {"dev": _confusion(by_role(A_rows, "dev")), "holdout": _confusion(by_role(A_rows, "holdout")),
         "pooled": _confusion(A_rows), "per_agent": A_rows}

    # D: skeptic ON (rep0) vs OFF
    off_rows = rows(off)
    on_c, off_c = _confusion(A_rows), _confusion(off_rows)
    ok_f = tot_f = 0
    for rel in agents:
        a = runs[rel][0]
        if a["ok"]:
            o, c = _faithfulness(a["res"])
            ok_f, tot_f = ok_f + o, tot_f + c
    on_wall = sum(runs[r][0]["wall"] for r in agents if runs[r][0]["ok"])
    off_wall = sum(off[r]["wall"] for r in agents if off[r]["ok"])
    D = {"false_BLOCK_on": on_c["false_BLOCK"], "false_BLOCK_off": off_c["false_BLOCK"],
         "false_SHIP_on": on_c["false_SHIP"], "false_SHIP_off": off_c["false_SHIP"],
         "verdict_changes": [r["agent"] for r, o in zip(sorted(A_rows, key=lambda x: x["agent"]),
                                                          sorted(off_rows, key=lambda x: x["agent"]))
                             if r["verdict"] != o["verdict"]],
         "wall_seconds_on": round(on_wall, 2), "wall_seconds_off": round(off_wall, 2),
         "overhead_ratio": round(on_wall / off_wall, 2) if off_wall else None,
         "faithfulness": _rate(ok_f, tot_f),
         "note": "Scripted deterministic agents: replay always reproduces, so ON==OFF is expected. "
                 "This does NOT show the skeptic is useless; it shows it cannot be tested without real LLM agents."}

    # F: flips across 3 audits
    flips = []
    for rel in agents:
        vs = [a["res"]["verdict"]["verdict"] for a in runs[rel] if a["ok"]]
        if len(set(vs)) > 1:
            flips.append({"agent": rel, "verdicts": vs})
    F = {"audits_per_agent": REPS_F, "agents": len(agents), "flip_rate": _rate(len(flips), len(agents)),
         "flips": flips, "note": "Scripted + seeded agents are deterministic, so ~0 flips is expected and weak evidence."}

    # G: orchestrator health from our own records (plan: LangSmith; not used here)
    all_a = [a for rel in agents for a in runs[rel]]
    okd = [a for a in all_a if a["ok"]]
    trials = [t for a in okd for t in a["res"]["trials"]]
    retried = [t for t in trials if t["retried"]]
    G = {"audits": len(all_a), "completion_rate": _rate(len(okd), len(all_a)),
         "mean_wall_s": round(sum(a["wall"] for a in okd) / max(1, len(okd)), 2),
         "mean_trials": round(len(trials) / max(1, len(okd)), 1),
         "mean_tool_calls": round(sum(len(t["tool_calls"]) for t in trials) / max(1, len(okd)), 1),
         "llm_tokens": 0,
         "retry_recovery": {"retried": len(retried), "recovered": sum(1 for t in retried if not t["error"])},
         "note": "Computed from our own trial records, not LangSmith. Cost is trials/tool calls/seconds: no LLM tokens."}

    # I: deltas vs Baseline 1 (text-only heuristic stand-in)
    base_rows = [{"agent": rel, "role": man[rel]["role"], "label": man[rel]["label"],
                  "verdict": _baseline_verdict(runs[rel][0]["res"]["trials"])}
                 for rel in agents if runs[rel][0]["ok"]]
    bc, gc = _confusion(base_rows), _confusion(A_rows)
    I = {"baseline": "text-only heuristic stand-in (NOT an LLM judge)",
         "gate": {k: gc[k] for k in ("recall", "false_SHIP", "false_BLOCK")},
         "baseline_metrics": {k: bc[k] for k in ("recall", "false_SHIP", "false_BLOCK")},
         "delta_recall": round((gc["recall"]["rate"] or 0) - (bc["recall"]["rate"] or 0), 3),
         "delta_false_SHIP": round((gc["false_SHIP"]["rate"] or 0) - (bc["false_SHIP"]["rate"] or 0), 3),
         "baseline_missed": bc["missed"]}

    # 8.3 #2: layer removed
    L = {"l0c_off": _confusion(rows(nol0c)), "full": gc,
         "newly_missed_without_l0c": sorted(set(_confusion(rows(nol0c))["missed"]) - set(gc["missed"]))}

    result = {"manifest_tampered": bad, "A": A, "D": D, "F": F, "G": G, "I": I, "layer_ablation": L,
              "not_implemented": ["B judge calibration (needs LLM judge + human labels)",
                                  "C mutation score (time)"],
              "caveats": __doc__}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    result["summary_text"] = _summary(result)
    return result


def _fmt(r: dict) -> str:
    return f"{r['k']}/{r['n']} = {r['rate']:.2f} (95% Wilson {r['wilson95'][0]:.2f}-{r['wilson95'][1]:.2f})" \
        if r["rate"] is not None else f"{r['k']}/{r['n']} (n/a)"


def _summary(r: dict) -> str:
    L = ["", "=== META-EVALS (scripted fleet, SAME-AUTHOR hold-out: plumbing check, not detection power) ==="]
    if r["manifest_tampered"]:
        L.append(f"!! FLEET CHANGED AFTER FREEZE: {r['manifest_tampered']} -> hold-out results INVALID")
    for part in ("dev", "holdout", "pooled"):
        c = r["A"][part]
        L += [f"[A:{part}] defects={c['n_defects']} clean={c['n_clean']}",
              f"   recall      {_fmt(c['recall'])}", f"   false-SHIP  {_fmt(c['false_SHIP'])}  missed={c['missed']}",
              f"   false-BLOCK {_fmt(c['false_BLOCK'])}  wrong={c['wrongly_blocked']}"]
    D = r["D"]
    L += [f"[D] skeptic ON vs OFF verdict changes: {D['verdict_changes']}  overhead x{D['overhead_ratio']}",
          f"   evidence faithfulness {_fmt(D['faithfulness'])}"]
    L += [f"[F] flip rate {_fmt(r['F']['flip_rate'])} over {r['F']['audits_per_agent']} audits/agent"]
    G = r["G"]
    L += [f"[G] completion {_fmt(G['completion_rate'])}  mean wall {G['mean_wall_s']}s  trials/audit {G['mean_trials']}"
          f"  retries {G['retry_recovery']}"]
    I = r["I"]
    L += [f"[I] vs Baseline 1 (text-only stand-in): d_recall {I['delta_recall']:+}  d_false_SHIP {I['delta_false_SHIP']:+}",
          f"   baseline missed: {I['baseline_missed']}"]
    L += [f"[layer] without L0c newly missed: {r['layer_ablation']['newly_missed_without_l0c']}"]
    L += ["Not implemented: " + "; ".join(r["not_implemented"])]
    return "\n".join(L)
