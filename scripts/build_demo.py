"""Build docs/demo.html from REAL run output. No numbers are typed by hand.

Usage:
  python scripts/build_demo.py --block <evidence.json of a BLOCK run> --ship <evidence.json of a SHIP run>

The fleet grid, comparison bars, mutant counts and red-team case list come from docs/results/*.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(p) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _diff_text(diff: dict) -> str:
    out = []
    for t, rows in diff.get("added", {}).items():
        out += [f"+ {t}: {json.dumps(r, default=str)}" for r in rows]
    for t, rows in diff.get("removed", {}).items():
        out += [f"- {t}: {json.dumps(r, default=str)}" for r in rows]
    for t, rows in diff.get("changed", {}).items():
        out += [f"~ {t} {r['pk']}: {json.dumps(r['cols'], default=str)}" for r in rows]
    return "\n".join(out)


def audit_view(ev: dict, name: str, max_findings: int = 2) -> dict:
    v = ev["verdict"]
    trial_by = {(t["scenario_id"], t["trial_idx"]): t for t in ev["trials"]}
    seen, hard = set(), []
    for f in ev["findings"]:
        if f["severity"] != "hard" or f["kind"] in seen:
            continue
        seen.add(f["kind"])
        t = trial_by.get((f["scenario_id"], f["trial_idx"]), {})
        hard.append({"kind": f["kind"], "level": f["level"], "message": f["message"], "clause": f["clause"],
                     "clause_text": v["policy_clauses_cited"].get(f["clause"], ""),
                     "said": t.get("final_message", ""), "diff": t.get("diff", {}),
                     "diff_text": _diff_text(t.get("diff", {})),
                     "calls": [{"tool": c["tool"], "args": c["args"], "error": c.get("error")}
                               for c in t.get("tool_calls", [])]})
        if len(hard) >= max_findings:
            break
    llm = ev.get("llm") or {"enabled": False}
    return {"name": name, "verdict": {"verdict": v["verdict"], "exit_code": v["exit_code"], "reasons": v["reasons"]},
            "l1": ev["l1"], "hard": hard, "llm": llm}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True)
    ap.add_argument("--ship", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo.html"))
    a = ap.parse_args()
    res = ROOT / "docs" / "results"
    meta = _load(res / "meta.json")
    llm = _load(res / "llm_eval_holdout_sample.json")
    rt = _load(res / "judge_redteam_gptoss120b.json")
    mutants = meta["C"]["mutants"]
    block_ev, ship_ev = _load(a.block), _load(a.ship)
    data = {
        "block": audit_view(block_ev, Path(block_ev["profile"]["target"]).name),
        "ship": audit_view(ship_ev, Path(ship_ev["profile"]["target"]).name),
        "fleet": meta["A"]["per_agent"],
        "llm": {"model": llm["model"], "summary": llm["summary"], "tokens": llm["tokens"]},
        "redteam": {"reps": rt["reps"], "fooled": rt["fooled"], "judgements": rt["judgements"],
                    "cases": [{"case": c["case"], "fooled": c["fooled"]} for c in rt["cases"]]},
        "meta": {"mutants_total": len(mutants), "mutants_killed": sum(1 for m in mutants if m["killed"]),
                 "audits": meta["G"]["audits"], "completion": meta["G"]["completion_rate"]["rate"]},
    }
    tpl = (ROOT / "scripts" / "demo_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    Path(a.out).write_text(tpl.replace("/*DATA*/null", payload), encoding="utf-8")
    print("written:", a.out, f"({Path(a.out).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
