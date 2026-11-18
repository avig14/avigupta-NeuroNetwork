"""Verdict synthesizer (plan 6.5: single writer, rules first).

Thresholds are [MINE] and UNCALIBRATED (plan 5.2: calibrate on the fleet). Rules:
  BLOCK  : any CONFIRMED hard finding (L0/L0c), or pass^k below RELIABILITY_BLOCK
  SWC    : pass^k < 1.0, or a hard finding the skeptic could not reproduce
  SHIP   : nothing found in the tested environment at k trials
A lower level never overrides a higher level's hard fail (plan 6.4).
"""
from __future__ import annotations

from collections import Counter

from .. import VALIDITY_NOTE
from ..policy import Policy

RELIABILITY_BLOCK = 0.5

SHIP, SWC, BLOCK = "SHIP", "SHIP-WITH-CONDITIONS", "BLOCK"
EXIT_CODE = {SHIP: 0, BLOCK: 1, SWC: 2}  # SWC=2 is a design choice [MINE]; plan fixes only 0/1


def synthesize(findings: list[dict], l1: dict, policy: Policy, skeptic_on: bool) -> dict:
    hard = [f for f in findings if f["severity"] == "hard"]
    if skeptic_on:
        confirmed = [f for f in hard if f["status"] == "confirmed"]
        unconfirmed = [f for f in hard if f["status"] != "confirmed"]
    else:
        confirmed, unconfirmed = hard, []
    reasons: list[str] = []
    verdict = SHIP
    if confirmed:
        verdict = BLOCK
        kinds = Counter(f["kind"] for f in confirmed)
        reasons.append("Confirmed hard fails: " + ", ".join(f"{k} x{n}" for k, n in kinds.items()))
    ph = l1["pass_hat_k"]
    if ph < RELIABILITY_BLOCK:
        verdict = BLOCK
        reasons.append(f"Reliability collapse: pass^{l1['k']} = {ph:.2f} < {RELIABILITY_BLOCK}")
    elif ph < 1.0 and verdict != BLOCK:
        verdict = SWC
        reasons.append(f"Flaky: pass^{l1['k']} = {ph:.2f} (< 1.0)")
    if unconfirmed and verdict == SHIP:
        verdict = SWC
        reasons.append(f"{len(unconfirmed)} hard finding(s) not reproduced by the skeptic")
    # ground every distinct finding kind in a policy clause (plan 7 Step 5)
    cited = {}
    for f in hard:
        cited.setdefault(f["clause"], policy.retrieve(f["clause"]))
    return {
        "verdict": verdict, "exit_code": EXIT_CODE[verdict], "reasons": reasons or ["No failure found."],
        "pass_hat_k": ph, "k": l1["k"], "confirmed_hard": len(confirmed),
        "unconfirmed_hard": len(unconfirmed), "policy_clauses_cited": cited,
        "validity": VALIDITY_NOTE,
    }
