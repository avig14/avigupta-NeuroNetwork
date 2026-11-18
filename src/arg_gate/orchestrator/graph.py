"""Central orchestrator: ONE LangGraph graph (plan 6.3; handbook core = single-agent workflow).

  profile -> plan --Send--> run_campaign x3 (reliability | policy | security, parallel)
          -> aggregate -> skeptic -> synthesize -> [human_gate (interrupt)] -> finalize

Docs-first notes (verified 18 Nov 2026 against docs.langchain.com, langgraph 1.2.22):
  - Send fan-out: workers write to shared keys through a reducer (operator.add).
  - The node that fans out ('plan') uses ONLY conditional edges (no static edge mixed in).
  - interrupt(): needs a checkpointer + thread_id; resume with Command(resume=...);
    the node re-runs from its start on resume, so human_gate has NO side effects before it.
"""
from __future__ import annotations

import operator
from dataclasses import replace
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Awaitable, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from .. import VALIDITY_NOTE, __version__
from ..campaigns import scenarios as scn_lib
from ..campaigns.adversary import Adversary
from ..graders.l1 import pass_hat_k
from ..graders import l3 as l3_lib
from ..llm import METER, default_model
from ..models import Scenario
from ..policy import load_policy
from ..report.evidence import write_evidence_pack
from ..sandbox.executor import Sandbox, ensure_clean_db, load_agent_class, run_trial
from ..skeptic.replay import skeptic_review
from .multi import make_run_campaign_v2
from .verdict import BLOCK, SWC, synthesize

K_FULL, K_SMOKE = 5, 1
MAX_TRIALS_DEFAULT = 400


class AuditState(TypedDict, total=False):
    cfg: dict
    profile: dict
    plan: dict
    trials: Annotated[list[dict], operator.add]
    adversary_log: Annotated[list[dict], operator.add]
    handoffs: Annotated[list[dict], operator.add]          # v2 only: size/time of each JSON handoff
    handoff_failures: Annotated[list[dict], operator.add]  # v2 only: failed/invalid sub-agent handoffs
    l1: dict
    findings: list[dict]
    skeptic: dict
    llm: dict
    verdict: dict
    human: dict
    evidence_path: str


class CampaignInput(TypedDict):
    campaign: str
    scenarios: list[dict]
    cfg: dict


def _scn(d: dict) -> Scenario:
    d = dict(d)
    d["seed"] = [(s, list(p)) for s, p in d.get("seed", [])]
    return Scenario(**d)


def _k(cfg: dict) -> int:
    return cfg.get("k") or (K_SMOKE if cfg["mode"] == "smoke" else K_FULL)


# ---------------------------------------------------------------- nodes
async def profile_node(state: AuditState) -> dict:
    cfg = state["cfg"]
    policy = load_policy(cfg["policy"])
    agent_cls = load_agent_class(cfg["target"])
    clean = ensure_clean_db(Path(cfg["workdir"]))
    async with Sandbox(Path(cfg["workdir"]) / "profile", clean, cfg["transport"]) as sb:
        async with sb.client() as c:
            tools = [t.name for t in await c.list_tools()]
    return {"profile": {
        "target": cfg["target"], "agent_name": getattr(agent_cls, "name", agent_cls.__name__),
        "mcp_tools": tools, "policy_clauses": sorted(policy.clauses),
        "refund_cap": policy.max_refund_without_approval, "canaries": policy.canary_tokens,
        "transport": cfg["transport"], "mode": cfg["mode"], "k": _k(cfg),
        "versions": {"arg_gate": __version__}}}


async def plan_node(state: AuditState) -> dict:
    cfg = state["cfg"]
    designed = scn_lib.design(state["profile"], cfg["mode"])
    pad = int(cfg.get("pad", 1))  # toy 'wide audit' knob for the multi-agent experiment: replicate scenarios
    if pad > 1:
        for scns in designed.values():
            scns.extend([replace(s, id=f"{s.id}~{i}") for i in range(1, pad) for s in list(scns)
                         if not s.id.count("~")])
    return {"plan": {name: [s.to_dict() for s in scns] for name, scns in designed.items()}}


def fan_out(state: AuditState) -> list[Send]:
    return [Send("run_campaign", {"campaign": name, "scenarios": scns, "cfg": state["cfg"]})
            for name, scns in state["plan"].items()]


async def run_campaign(inp: CampaignInput) -> dict:
    cfg, name = inp["cfg"], inp["campaign"]
    fault = cfg.get("inject_fault")
    if fault and fault.get("campaign") == name and fault["kind"] == "crash":
        raise RuntimeError(f"injected fault: {name} campaign crashed")  # same code path in v1 and v2
    policy = load_policy(cfg["policy"])
    agent_cls = load_agent_class(cfg["target"])
    clean = ensure_clean_db(Path(cfg["workdir"]))
    l0c = cfg.get("l0c", True)
    l0 = cfg.get("l0", True)
    k = _k(cfg) if name != "security" else 1
    budget = cfg.get("max_trials", MAX_TRIALS_DEFAULT) // 3
    trials: list[dict] = []
    adv_log: list[dict] = []
    async with Sandbox(Path(cfg["workdir"]) / name, clean, cfg["transport"]) as sb:
        for sd in inp["scenarios"]:
            scn = _scn(sd)
            for idx in range(k):
                if len(trials) >= budget:
                    break
                trials.append((await run_trial(agent_cls, scn, idx, sb, policy, l0c, l0)).to_dict())
        if name == "security" and cfg["mode"] == "full" and cfg.get("adversary", True):
            adv = Adversary(max_attempts=cfg.get("adversary_attempts", 8))
            while (scn := adv.next_scenario()) is not None and len(trials) < budget:
                rec = (await run_trial(agent_cls, scn, 0, sb, policy, l0c, l0)).to_dict()
                trials.append(rec)
                hard = [f["kind"] for f in rec["findings"] if f["severity"] == "hard"]
                adv.observe(scn, bool(hard), hard)
                adv_log.append({**adv.history[-1], "scenario": scn.to_dict()})
    return {"trials": trials, "adversary_log": adv_log}


async def aggregate_node(state: AuditState) -> dict:
    trials = state["trials"]
    findings = [f for t in trials for f in t["findings"]]
    scored = [t for t in trials if t["campaign"] in ("reliability", "policy")]
    l1 = pass_hat_k(scored)
    l1["trial_ci"] = list(l1["trial_ci"])
    if not state["cfg"].get("l1", True):  # layer ablation: ignore reliability
        l1 = {**l1, "pass_hat_k": 1.0, "ablated": True}
    return {"l1": l1, "findings": findings}


async def skeptic_node(state: AuditState) -> dict:
    cfg = state["cfg"]
    if not cfg.get("skeptic", True) or cfg["mode"] == "smoke":
        return {"skeptic": {"enabled": False}}
    scenarios = {sd["id"]: _scn(sd) for scns in state["plan"].values() for sd in scns}
    for a in state.get("adversary_log", []):
        scenarios[a["scenario"]["id"]] = _scn(a["scenario"])
    res = await skeptic_review(
        load_agent_class(cfg["target"]), state["findings"], scenarios, load_policy(cfg["policy"]),
        Path(cfg["workdir"]), ensure_clean_db(Path(cfg["workdir"])), cfg["transport"], cfg.get("l0c", True), cfg.get("l0", True))
    return {"findings": res["findings"],
            "skeptic": {"enabled": True, "confirmed": res["confirmed"], "unconfirmed": res["unconfirmed"]}}


async def l3_node(state: AuditState) -> dict:
    """Optional L3 LLM judge. Adds SOFT findings only (see graders/l3.py guardrails). Off unless cfg['l3']."""
    cfg = state["cfg"]
    if not cfg.get("l3"):
        return {"llm": {"enabled": False}}
    policy = load_policy(cfg["policy"])
    scenarios = {sd["id"]: sd for scns in state["plan"].values() for sd in scns}
    picked, seen = [], set()
    for t in state["trials"]:  # first trial of each scenario; adversary scenarios are not judged
        if t["scenario_id"] in scenarios and t["scenario_id"] not in seen and not t["error"]:
            seen.add(t["scenario_id"])
            picked.append(t)
    picked = picked[: int(cfg.get("l3_max", 40))]
    before = METER.snapshot()
    verdicts = await l3_lib.judge_many([(scenarios[t["scenario_id"]], t) for t in picked], policy,
                                       cfg.get("l3_model"), int(cfg.get("l3_concurrency", 8)))
    new, rows = [], []
    for t, v in zip(picked, verdicts):
        f = l3_lib.to_finding(t["scenario_id"], t["trial_idx"], v, policy)
        det_hard = any(x["severity"] == "hard" for x in t["findings"])
        if f is not None:
            new.append(f.to_dict())
        rows.append({"scenario_id": t["scenario_id"], "trial_idx": t["trial_idx"], "det_hard": det_hard,
                     "violation": bool(v.get("violation")) if "error" not in v else None,
                     "kind": v.get("kind"), "confidence": v.get("confidence"),
                     "evidence": v.get("evidence", ""), "error": v.get("error")})
    after = METER.snapshot()
    errs = sum(1 for r in rows if r["error"])
    return {"findings": state["findings"] + new,
            "llm": {"enabled": True, "model": cfg.get("l3_model") or default_model(), "judged": len(rows),
                    "flagged": sum(1 for r in rows if r["violation"]), "errors": errs,
                    "judge_only_flags": sum(1 for r in rows if r["violation"] and not r["det_hard"]),
                    "agrees_with_l0": sum(1 for r in rows if r["violation"] and r["det_hard"]),
                    "input_tokens": after["input_tokens"] - before["input_tokens"],
                    "output_tokens": after["output_tokens"] - before["output_tokens"],
                    "rows": rows,
                    "note": "Soft findings only: the judge can add SHIP-WITH-CONDITIONS, never clear a finding."}}


async def synthesize_node(state: AuditState) -> dict:
    cfg = state["cfg"]
    sk_on = state["skeptic"].get("enabled", False)
    findings = state["findings"]
    if not sk_on:  # smoke tier / skeptic off: every hard finding stands (deterministic L0)
        for f in findings:
            if f["severity"] == "hard":
                f["status"] = "confirmed"
        sk_on = True
    return {"verdict": synthesize(findings, state["l1"], load_policy(cfg["policy"]), sk_on,
                                  state.get("handoff_failures") or []),
            "findings": findings}


def route_after_verdict(state: AuditState) -> str:
    gate = state["cfg"].get("human_gate", "on")
    return "human_gate" if state["verdict"]["verdict"] == SWC and gate != "off" else "finalize"


def human_gate_node(state: AuditState) -> dict:
    # NO side effects before interrupt(): this node re-runs from the top on resume.
    decision = interrupt({
        "question": "Verdict is SHIP-WITH-CONDITIONS. Accept the conditions or reject (BLOCK)?",
        "reasons": state["verdict"]["reasons"], "pass_hat_k": state["verdict"]["pass_hat_k"]})
    action = (decision or {}).get("action", "defer")
    verdict = dict(state["verdict"])
    if action == "reject":
        verdict["verdict"], verdict["exit_code"] = BLOCK, 1
        verdict["reasons"] = verdict["reasons"] + ["Human reviewer rejected the conditions."]
    return {"human": {"action": action, "note": (decision or {}).get("note", "")}, "verdict": verdict}


async def finalize_node(state: AuditState) -> dict:
    cfg = state["cfg"]
    trials = state["trials"]
    state_view = {**state, "cost": {
        "trials": len(trials), "tool_calls": sum(len(t["tool_calls"]) for t in trials),
        "retries": sum(1 for t in trials if t["retried"]), "errors": sum(1 for t in trials if t["error"]),
        "agent_seconds": round(sum(t["duration_s"] for t in trials), 3),
        "arch": cfg.get("arch", "single"),
        "handoff_bytes": sum(h["bytes_req"] + h["bytes_resp"] for h in state.get("handoffs", [])),
        "handoff_failures": len(state.get("handoff_failures", [])),
        "llm_tokens": (lambda m: m["input_tokens"] + m["output_tokens"])(METER.snapshot()),
        "llm": METER.snapshot(),
        "note": "llm_tokens = every LLM call made in this process (Groq: L3 judge, LLM baseline). 0 means no LLM was used."}}
    path = write_evidence_pack(state_view, Path(cfg["out_dir"]), VALIDITY_NOTE)
    return {"evidence_path": str(path)}


# ---------------------------------------------------------------- graph
def build_graph(arch: str = "single"):
    b = StateGraph(AuditState)
    b.add_node("profile", profile_node)
    b.add_node("plan", plan_node)
    b.add_node("run_campaign", make_run_campaign_v2(run_campaign) if arch == "multi" else run_campaign)
    b.add_node("aggregate", aggregate_node)
    b.add_node("skeptic", skeptic_node)
    b.add_node("l3", l3_node)
    b.add_node("synthesize", synthesize_node)
    b.add_node("human_gate", human_gate_node)
    b.add_node("finalize", finalize_node)
    b.add_edge(START, "profile")
    b.add_edge("profile", "plan")
    b.add_conditional_edges("plan", fan_out, ["run_campaign"])
    b.add_edge("run_campaign", "aggregate")
    b.add_edge("aggregate", "skeptic")
    b.add_edge("skeptic", "l3")
    b.add_edge("l3", "synthesize")
    b.add_conditional_edges("synthesize", route_after_verdict, ["human_gate", "finalize"])
    b.add_edge("human_gate", "finalize")
    b.add_edge("finalize", END)
    return b.compile(checkpointer=InMemorySaver())


async def run_audit(cfg: dict,
                    on_interrupt: Callable[[dict], Awaitable[dict] | dict] | None = None) -> dict:
    """Run one audit. cfg keys: target, policy, mode(full|smoke), k, transport(inproc|http),
    workdir, out_dir, l0c, l0, l1, skeptic, adversary, human_gate(on|off), max_trials,
    arch(single|multi), pad (toy width), inject_fault({campaign, kind})."""
    cfg = {"mode": "full", "transport": "inproc", "human_gate": "on", **cfg}
    audit_id = cfg.get("audit_id") or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    cfg["audit_id"] = audit_id
    cfg["workdir"] = str(Path(cfg["workdir"]) / audit_id)
    cfg["out_dir"] = str(Path(cfg["out_dir"]) / audit_id)
    graph = build_graph(cfg.get("arch", "single"))
    config: Any = {"configurable": {"thread_id": audit_id}}
    result = await graph.ainvoke({"cfg": cfg}, config)
    while result.get("__interrupt__"):
        payload = result["__interrupt__"][0].value
        decision = on_interrupt(payload) if on_interrupt else {"action": "defer"}
        if hasattr(decision, "__await__"):
            decision = await decision
        result = await graph.ainvoke(Command(resume=decision), config)
    return result
