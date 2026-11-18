"""arg-gate CLI.

  arg-gate run  --target fleet/dev/d01_no_cap.py [--mode smoke|full] [--k 5] [--transport inproc|http]
  arg-gate meta [--out runs/meta.json]
  arg-gate replay runs/<id>/evidence.json [--scenario ID] [--all]

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
    if a.l3:
        from .llm import default_model, llm_available, load_dotenv
        load_dotenv()
        if not llm_available(a.l3_model or default_model()):
            print("--l3 needs GROQ_API_KEY in the environment (or a gitignored .env).",
                  file=sys.stderr)
            return 3
    cfg = {"l3": a.l3, "l3_max": a.l3_max, "l3_model": a.l3_model, "target": target, "policy": a.policy, "mode": a.mode, "k": a.k, "transport": a.transport,
           "workdir": a.workdir, "out_dir": a.out, "l0c": not a.no_l0c, "l0": not a.no_l0, "l1": not a.no_l1, "skeptic": not a.no_skeptic,
           "adversary": not a.no_adversary, "human_gate": gate, "max_trials": a.max_trials}
    res = asyncio.run(run_audit(cfg, on_int))
    v = res["verdict"]
    print(f"\nVERDICT: {v['verdict']}  (exit {v['exit_code']})")
    for r in v["reasons"]:
        print(" -", r)
    print(f"pass^{v['k']} = {v['pass_hat_k']:.2f} | confirmed hard: {v['confirmed_hard']} "
          f"| unconfirmed: {v['unconfirmed_hard']}")
    llm = res.get("llm") or {}
    if llm.get("enabled"):
        print(f"L3 judge: read {llm['judged']} trials, flagged {llm['flagged']} "
              f"({llm['judge_only_flags']} that L0 did not hard-fail), errors {llm['errors']}, "
              f"tokens in/out {llm['input_tokens']}/{llm['output_tokens']}")
    print("evidence:", res["evidence_path"])
    print(v["validity"])
    return v["exit_code"]


def _cmd_replay(a: argparse.Namespace) -> int:
    from .replay import replay
    ev = Path(a.evidence)
    if not ev.is_file():
        print(f"evidence file not found: {ev}", file=sys.stderr)
        return 3
    try:
        pack = json.loads(ev.read_text(encoding="utf-8"))
        _guard_target(pack["profile"]["target"], a.trust_target)
        res = asyncio.run(replay(ev, Path(a.workdir), a.scenario, a.all))
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"cannot replay: {exc}", file=sys.stderr)
        return 3
    print(f"verdict in file: {res['verdict_in_file']}   target: {res['target']}")
    if res["target_changed"]:
        print("WARNING: target file changed since the audit. Differences below may come from that.")
    for r in res["rows"]:
        print(f"{'same' if r['reproduced'] else 'DIFF'}  {r['scenario_id']}#{r['trial_idx']}  "
              f"passed {r['orig_passed']}->{r['new_passed']}  findings {r['orig_findings']} -> {r['new_findings']}")
    if not res["rows"]:
        print("nothing to replay (no failing trials; use --all to replay every trial)")
    print(f"reproduced {res['reproduced']}/{res['replayed']}")
    return 0 if res["all_reproduced"] or not res["rows"] else 1


def _cmd_meta(a: argparse.Namespace) -> int:
    from .meta.evals import run_all
    out = asyncio.run(run_all(Path(a.workdir), Path(a.out)))
    print(out["summary_text"])
    print("written:", a.out)
    return 0


def _cmd_llm_eval(a: argparse.Namespace) -> int:
    from .llm import default_model, llm_available, load_dotenv
    load_dotenv()
    if not llm_available(a.model or default_model()):
        print("llm-eval needs GROQ_API_KEY (environment or gitignored .env).", file=sys.stderr)
        return 3
    from .meta.llm_eval import run_llm_eval
    res = asyncio.run(run_llm_eval(Path(a.workdir), Path(a.out), a.only, a.model, per_agent=a.per_agent))
    print(res["summary_text"])
    t = res["tokens"]
    print(f"tokens in/out {t['input_tokens']}/{t['output_tokens']}  calls {t['calls']}  est ${t['est_usd']}  wall {res['wall_s']}s")
    print("written:", a.out)
    return 0


def _cmd_judge_redteam(a: argparse.Namespace) -> int:
    from .llm import default_model, llm_available, load_dotenv
    load_dotenv()
    if not llm_available(a.model or default_model()):
        print("judge-redteam needs GROQ_API_KEY (environment or gitignored .env).", file=sys.stderr)
        return 3
    from .redteam.judge_inject import run_judge_redteam
    res = asyncio.run(run_judge_redteam(Path(a.out), a.model, a.reps))
    for r in res["cases"]:
        print(f"{r['case']:<28} real={str(r['real_violation']):<5} flagged={r['flagged']} errors={r['errors']} fooled={r['fooled']}")
    print(f"fooled {res['fooled']} of {res['judgements']} judgements. written: {a.out}")
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
    r.add_argument("--no-l0c", action="store_true", help="ablation: turn the claim-vs-state check off")
    r.add_argument("--no-l0", action="store_true", help="ablation: turn the L0 state-diff graders off")
    r.add_argument("--no-l1", action="store_true", help="ablation: ignore reliability (pass^k forced to 1.0)")
    r.add_argument("--no-skeptic", action="store_true")
    r.add_argument("--l3", action="store_true", help="add the LLM judge (soft findings only; needs GROQ_API_KEY)")
    r.add_argument("--l3-max", type=int, default=40, help="max trials the LLM judge reads (cost cap)")
    r.add_argument("--l3-model", default=None, help="Groq model id (default openai/gpt-oss-120b)")
    r.add_argument("--no-adversary", action="store_true")
    r.add_argument("--trust-target", action="store_true", help="allow targets outside ./fleet (executes their code)")
    r.set_defaults(fn=_cmd_run)
    rp = sub.add_parser("replay", help="re-run the trials behind a verdict and check they reproduce")
    rp.add_argument("evidence", help="path to evidence.json written by `arg-gate run`")
    rp.add_argument("--scenario", default=None, help="replay only this scenario id")
    rp.add_argument("--all", action="store_true", help="replay every trial, not just failing ones")
    rp.add_argument("--workdir", default=".arg_runs/replay")
    rp.add_argument("--trust-target", action="store_true", help="allow targets outside ./fleet (executes their code)")
    rp.set_defaults(fn=_cmd_replay)
    m = sub.add_parser("meta", help="run the gate's own evaluation (meta-evals)")
    m.add_argument("--workdir", default=".arg_runs/meta")
    m.add_argument("--out", default="runs/meta.json")
    m.set_defaults(fn=_cmd_meta)
    le = sub.add_parser("llm-eval", help="fleet through deterministic gate vs L3 LLM judge vs LLM text-only baseline (needs key)")
    le.add_argument("--workdir", default=".arg_runs/llm_eval")
    le.add_argument("--out", default="runs/llm_eval.json")
    le.add_argument("--only", nargs="*", default=None, help="only agents whose path contains one of these")
    le.add_argument("--model", default=None)
    le.add_argument("--per-agent", type=int, default=40, help="max trials judged per agent (free Groq quota is ~200K tokens/day)")
    le.set_defaults(fn=_cmd_llm_eval)
    jr = sub.add_parser("judge-redteam", help="try to steer the L3 judge with injections (needs key)")
    jr.add_argument("--out", default="runs/judge_redteam.json")
    jr.add_argument("--model", default=None)
    jr.add_argument("--reps", type=int, default=2)
    jr.set_defaults(fn=_cmd_judge_redteam)
    ma = sub.add_parser("multiagent", help="plan section 9: single vs multi-agent experiment")
    ma.add_argument("--workdir", default=".arg_runs/multiagent")
    ma.add_argument("--out", default="runs/multiagent.json")
    ma.set_defaults(fn=_cmd_multiagent)
    rt = sub.add_parser("redteam", help="attack our own graders (plan 6.7 red-team log)")
    rt.add_argument("--round", default="current")
    rt.add_argument("--workdir", default=".arg_runs/redteam")
    rt.add_argument("--out", default="runs/redteam.json")
    rt.set_defaults(fn=_cmd_redteam)
    sv = sub.add_parser("serve", help="demo web app: submit an agent, get the report (localhost only)")
    sv.add_argument("--port", type=int, default=8800)
    sv.set_defaults(fn=lambda a: __import__("arg_gate.webapp", fromlist=["serve"]).serve(a.port))
    f = sub.add_parser("freeze", help="hash the fleet into fleet/manifest.json (do BEFORE tuning on hold-out)")
    f.set_defaults(fn=_cmd_freeze)
    a = ap.parse_args(argv)
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
