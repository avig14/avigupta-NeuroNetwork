"""Multi-agent variant v2 (plan section 9 experiment): policy + security become independent sub-agents.

v1 (single): all campaigns are workers inside one graph and share one state.
v2 (multi):  `policy` and `security` (the adversary) each run as their OWN compiled LangGraph subgraph
             with a PRIVATE state schema. They talk to the orchestrator only through JSON handoff
             contracts. A bad or missing handoff is a recorded failure, never a crash, and it is
             FAIL-CLOSED: the verdict cannot be SHIP while a handoff failed (coverage is incomplete).
`reliability` stays in the orchestrator (it is the L1 signal the verdict needs directly).

Docs-first (verified 18 Nov 2026, docs.langchain.com): a subgraph with a DIFFERENT state schema is invoked
from a wrapper node with manual state mapping; only the parent graph needs a checkpointer.

HONEST NOTE: the experiment cannot test the plan's main claim (multi-agent helps wide, many-tool audits;
costs ~15x tokens) because the fleet is narrow and there are no LLM tokens. See docs/multi_agent_results.md.
"""
from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

SUBAGENT_CAMPAIGNS = ("policy", "security")
_TRIAL_KEYS = {"scenario_id": str, "campaign": str, "trial_idx": int, "passed": bool, "findings": list,
               "final_message": str, "diff": dict, "post": dict, "tool_calls": list, "retried": bool}


class ContractError(Exception):
    """A handoff message broke its JSON contract (the 'lost context' failure class)."""


class SubState(TypedDict, total=False):  # PRIVATE to a sub-agent; shares no keys with the parent AuditState
    request: dict
    response: dict


def validate_request(req: Any) -> None:
    if not isinstance(req, dict) or {"campaign", "scenarios", "cfg"} - set(req):
        raise ContractError("request must be an object with campaign, scenarios, cfg")
    if req["campaign"] not in SUBAGENT_CAMPAIGNS or not isinstance(req["scenarios"], list):
        raise ContractError("request has an unknown campaign or non-list scenarios")


def validate_response(resp: Any, campaign: str) -> None:
    if not isinstance(resp, dict):
        raise ContractError("response is not an object")
    missing = {"campaign", "status", "trials", "adversary_log"} - set(resp)
    if missing:
        raise ContractError(f"response missing fields: {sorted(missing)}")
    if resp["campaign"] != campaign:
        raise ContractError(f"response is for campaign {resp['campaign']!r}, expected {campaign!r}")
    if resp["status"] != "ok":
        raise ContractError(f"sub-agent reported status {resp['status']!r}")
    if not isinstance(resp["trials"], list) or not isinstance(resp["adversary_log"], list):
        raise ContractError("trials and adversary_log must be lists")
    for i, t in enumerate(resp["trials"]):
        if not isinstance(t, dict):
            raise ContractError(f"trial {i} is not an object")
        for key, typ in _TRIAL_KEYS.items():
            if key not in t or not isinstance(t[key], typ):
                raise ContractError(f"trial {i} field {key!r} missing or not {typ.__name__}")


def _fault(cfg: dict, campaign: str) -> str | None:
    f = cfg.get("inject_fault")
    return f["kind"] if f and f.get("campaign") == campaign else None


def make_run_campaign_v2(core: Callable[[dict], Awaitable[dict]]):
    """Build the v2 campaign node around the shared core campaign runner."""

    async def execute(state: SubState) -> dict:
        req = state["request"]
        validate_request(req)
        out = await core({"campaign": req["campaign"], "scenarios": req["scenarios"], "cfg": req["cfg"]})
        resp: dict = {"campaign": req["campaign"], "status": "ok", "trials": out["trials"],
                      "adversary_log": out["adversary_log"]}
        kind = _fault(req["cfg"], req["campaign"])  # fault injection: corrupt the HANDOFF, not the grading
        if kind == "drop_field":
            resp.pop("trials")
        elif kind == "bad_type":
            resp["trials"] = "not-a-list"
        return {"response": resp}

    b = StateGraph(SubState)
    b.add_node("execute", execute)
    b.add_edge(START, "execute")
    b.add_edge("execute", END)
    subagent = b.compile()  # no checkpointer: only the parent needs one

    async def run_campaign_v2(inp: dict) -> dict:
        name = inp["campaign"]
        if name not in SUBAGENT_CAMPAIGNS:  # reliability stays in the orchestrator
            out = await core(inp)
            return {**out, "handoffs": [{"campaign": name, "via": "direct", "bytes_req": 0, "bytes_resp": 0,
                                         "ms": 0.0}]}
        t0 = time.perf_counter()
        wire_req = json.dumps({"campaign": name, "scenarios": inp["scenarios"], "cfg": inp["cfg"]})
        rec = {"campaign": name, "via": "subagent", "bytes_req": len(wire_req.encode()), "bytes_resp": 0}
        try:
            res = await subagent.ainvoke({"request": json.loads(wire_req)})
            wire_resp = json.dumps(res["response"])
            rec["bytes_resp"] = len(wire_resp.encode())
            resp = json.loads(wire_resp)
            validate_response(resp, name)
        except Exception as exc:  # fail closed: record, never crash the audit
            rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return {"trials": [], "adversary_log": [], "handoffs": [rec],
                    "handoff_failures": [{"campaign": name, "error_type": type(exc).__name__,
                                          "error": str(exc)[:300],
                                          "lost_context": isinstance(exc, ContractError)}]}
        rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return {"trials": resp["trials"], "adversary_log": resp["adversary_log"], "handoffs": [rec]}

    return run_campaign_v2
