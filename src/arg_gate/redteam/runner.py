"""Run the red-team attacks through the real gate (full tier) and record outcomes."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from ..graders.l1 import wilson
from ..orchestrator.graph import run_audit
from .attacks import ATTACKS, FLAKY_LEAK


async def run_redteam(workdir: Path, out: Path, round_label: str) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for aid, family, desc, expect, src in ATTACKS:
        d = workdir / aid
        shutil.rmtree(d, ignore_errors=True)  # stale marker files would fake a result
        d.mkdir(parents=True, exist_ok=True)
        if src == "FLAKY":
            src = FLAKY_LEAK.format(mark=str(d / "mark.txt"))
        (d / f"{aid}.py").write_text(src, encoding="utf-8")
        res = await run_audit({"target": str(d / f"{aid}.py"), "policy": "policies/retail.md", "mode": "full",
                               "workdir": str(d / "w"), "out_dir": str(d / "o"), "human_gate": "off",
                               "adversary": False})
        v = res["verdict"]["verdict"]
        kinds = sorted({f["kind"] for f in res["findings"] if f["severity"] == "hard"})
        by = sorted({f["level"] for f in res["findings"] if f["severity"] == "hard"})
        ok = ({"BLOCK": "BLOCK", "SHIP": "SHIP", "SWC": "SHIP-WITH-CONDITIONS"}[expect] == v)
        rows.append({"id": aid, "family": family, "description": desc, "expect": expect, "verdict": v,
                     "hard_kinds": kinds, "levels": by, "as_expected": ok})
    attacks = [r for r in rows if r["expect"] == "BLOCK"]
    probes = [r for r in rows if r["expect"] != "BLOCK"]
    missed = [r["id"] for r in attacks if not r["as_expected"]]
    lo, hi = wilson(len(missed), len(attacks))
    result = {"round": round_label, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": rows,
              "attacks": len(attacks), "evaded": missed,
              "evasion_rate": {"k": len(missed), "n": len(attacks), "wilson95": [round(lo, 3), round(hi, 3)]},
              "false_positives": [r["id"] for r in probes if not r["as_expected"]],
              "note": "Attacks were written by the same author as the graders; the list is NOT exhaustive."}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
