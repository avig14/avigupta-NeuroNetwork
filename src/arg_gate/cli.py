"""arg-gate CLI.

  arg-gate run  --target fleet/dev/d01_no_cap.py [--mode smoke|full] [--k 5] [--transport inproc|http]
  arg-gate meta [--out runs/meta.json]

Exit codes: 0 SHIP, 1 BLOCK, 2 SHIP-WITH-CONDITIONS [MINE; plan fixes only 0/1], 3 usage/internal error.
Trust boundary (plan 6.9): the gate IMPORTS and RUNS the target file. It refuses any target
outside ./fleet unless --trust-target is passed. Do not point it at code you do not trust.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

DEFAULT_POLICY = "policies/retail.md"


def _guard_target(target: str, trust: bool) -> str:
    p = Path(target).resolve()
    fleet = (Path.cwd() / "fleet").resolve()
    if not p.is_file():
        sys.exit(f"target not found: {p}")
    inside = fleet in p.parents
    if not inside and not trust:
        print(f"REFUSED: target {p} is outside ./fleet. The gate executes target code. "
              "Pass --trust-target only for code you trust.", file=sys.stderr)
        sys.exit(3)
    return str(p)


def _interactive_gate(payload: dict) -> dict:
    print("\n== HUMAN GATE (L4) ==")
    print(payload["question"])
    for r in payload["reasons"]:
        print(" -", r)
    if not sys.stdin.isatty():
        print("(non-interactive: deferring; verdict stays SHIP-WITH-CONDITIONS)")
        return {"action": "defer"}
    ans = input("accept / reject / defer? ").strip().lower()
    return {"action": ans if ans in ("accept", "reject") else "defer"}


def _cmd_run(a: argparse.Namespace) -> int:
    from .orchestrator.graph import run_audit
    target = _guard_target(a.target, a.trust_target)
    if not Path(a.policy).is_file():
        print(f"policy file not found: {a.policy}", file=sys.stderr)
        return 3
    if a.human_gate == "ask":
        on_int, gate = _interactive_gate, "on"
    elif a.human_gate == "accept":
        on_int, gate = (lambda p: {"action": "accept"}), "on"
    elif a.human_gate == "reject":
        on_int, gate = (lambda p: {"action": "reject"}), "on"
    else:
        on_int, gate = None, "off"
    cfg = {"target": target, "policy": a.policy, "mode": a.mode, "k": a.k, "transport": a.transport,
           "workdir": a.workdir, "out_dir": a.out, "l0c": not a.no_l0c, "skeptic": not a.no_skeptic,
           "adversary": not a.no_adversary, "human_gate": gate, "max_trials": a.max_trials}
    res = asyncio.run(run_audit(cfg, on_int))
    v = res["verdict"]
    print(f"\nVERDICT: {v['verdict']}  (exit {v['exit_code']})")
    for r in v["reasons"]:
        print(" -", r)
    print(f"pass^{v['k']} = {v['pass_hat_k']:.2f} | confirmed hard: {v['confirmed_hard']} "
          f"| unconfirmed: {v['unconfirmed_hard']}")
    print("evidence:", res["evidence_path"])
    print(v["validity"])
    return v["exit_code"]


def _cmd_meta(a: argparse.Namespace) -> int:
    from .meta.evals import run_all
    out = asyncio.run(run_all(Path(a.workdir), Path(a.out)))
    print(out["summary_text"])
    print("written:", a.out)
    return 0


def _cmd_multiagent(a: argparse.Namespace) -> int:
    from .meta.multiagent import run_multiagent
    res = asyncio.run(run_multiagent(Path(a.workdir), Path(a.out)))
    print("prediction sha256:", res["prediction_file"]["sha256"][:16], "mtime(UTC):", res["prediction_file"]["mtime_utc"])
    for k, c in res["checks"].items():
        print(("HELD   " if c["held"] else "FAILED ") + k + "  " + json.dumps(c["measured"], default=str))
    print("verdict disagreements v1 vs v2:", res["disagreements"])
    print("written:", a.out)
    return 0


def _cmd_redteam(a: argparse.Namespace) -> int:
    from .redteam.runner import run_redteam
    res = asyncio.run(run_redteam(Path(a.workdir), Path(a.out), a.round))
    for r in res["rows"]:
        print(f"{'ok ' if r['as_expected'] else 'BAD'} {r['id']:<10} expect={r['expect']:<5} got={r['verdict']:<21} {r['description']}")
    e = res["evasion_rate"]
    print(f"\nevaded {e['k']}/{e['n']} (Wilson95 {e['wilson95']}); false positives: {res['false_positives']}")
    print("written:", a.out)
    return 0


def _cmd_freeze(a: argparse.Namespace) -> int:
    from .meta.evals import freeze
    man = freeze()
    roles = [e["role"] + "/" + e["label"] for e in man["agents"].values()]
    print(f"froze {len(roles)} agents:", {r: roles.count(r) for r in sorted(set(roles))})
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="arg-gate", description="Agent Release Gate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="audit one target agent")
    r.add_argument("--target", required=True)
    r.add_argument("--policy", default=DEFAULT_POLICY)
    r.add_argument("--mode", choices=["smoke", "full"], default="full")
    r.add_argument("--k", type=int, default=None, help="trials per scenario (default 1 smoke / 5 full)")
    r.add_argument("--transport", choices=["inproc", "http"], default="inproc")
    r.add_argument("--workdir", default=".arg_runs")
    r.add_argument("--out", default="runs")
    r.add_argument("--human-gate", choices=["off", "ask", "accept", "reject"], default="off")
    r.add_argument("--max-trials", type=int, default=400, help="trial budget cap (plan 6.2 cost cap)")
    r.add_argument("--no-l0c", action="store_true")
    r.add_argument("--no-skeptic", action="store_true")
    r.add_argument("--no-adversary", action="store_true")
    r.add_argument("--trust-target", action="store_true", help="allow targets outside ./fleet (executes their code)")
    r.set_defaults(fn=_cmd_run)
    m = sub.add_parser("meta", help="run the gate's own evaluation (meta-evals)")
    m.add_argument("--workdir", default=".arg_runs/meta")
    m.add_argument("--out", default="runs/meta.json")
    m.set_defaults(fn=_cmd_meta)
    ma = sub.add_parser("multiagent", help="plan section 9: single vs multi-agent experiment")
    ma.add_argument("--workdir", default=".arg_runs/multiagent")
    ma.add_argument("--out", default="runs/multiagent.json")
    ma.set_defaults(fn=_cmd_multiagent)
    rt = sub.add_parser("redteam", help="attack our own graders (plan 6.7 red-team log)")
    rt.add_argument("--round", default="current")
    rt.add_argument("--workdir", default=".arg_runs/redteam")
    rt.add_argument("--out", default="runs/redteam.json")
    rt.set_defaults(fn=_cmd_redteam)
    f = sub.add_parser("freeze", help="hash the fleet into fleet/manifest.json (do BEFORE tuning on hold-out)")
    f.set_defaults(fn=_cmd_freeze)
    a = ap.parse_args(argv)
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
