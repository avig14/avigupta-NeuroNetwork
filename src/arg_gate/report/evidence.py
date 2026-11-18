"""Evidence pack (plan 5.1 output): JSON + a self-contained HTML viewer (plan 7 Step 7)."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any


# Plan Step 7 (behaviour profile): disclose AI-generated parts.
AI_DISCLOSURE = ("Automation disclosure: this report was produced by an automated release gate. Every verdict, "
                 "finding and number in it is computed by deterministic code (state diff, canary scan, policy rules, "
                 "pass^k, replay). No language model wrote or graded any of it in this prototype. The tool and its "
                 "scripted test agents were written with AI coding assistance. Test data is synthetic; nothing "
                 "leaves this machine.")

AI_DISCLOSURE_LLM = ("Automation disclosure: this report was produced by an automated release gate. The verdict is "
                     "computed by deterministic code (state diff, canary scan, policy rules, pass^k, replay). In this run "
                     "an optional LLM judge (an open-weight model served by Groq) also read the transcripts. "
                     "Its output is limited to SOFT findings: it can add a SHIP-WITH-CONDITIONS for a human to review, but "
                     "it cannot create a BLOCK, clear a finding, or change pass^k. Transcripts sent to the judge are "
                     "synthetic test data. The tool was written with AI coding assistance.")


def disclosure_for(llm: dict | None) -> str:
    return AI_DISCLOSURE_LLM if (llm or {}).get("enabled") else AI_DISCLOSURE


def _scenario_map(state: dict) -> dict:
    """Every scenario that ran (fixed + adversary-made), so `arg-gate replay` can re-run any trial."""
    out = {sd["id"]: sd for scns in state.get("plan", {}).values() for sd in scns}
    for a in state.get("adversary_log", []):
        out[a["scenario"]["id"]] = a["scenario"]
    return out


def _file_sha256(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def write_evidence_pack(state: dict, out_dir: Path, validity: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = state.get("cfg", {})
    pack = {
        "validity": validity,
        "ai_disclosure": disclosure_for(state.get("llm")),
        "llm": state.get("llm"),
        "verdict": state["verdict"],
        "human": state.get("human"),
        "profile": state["profile"],
        "l1": state["l1"],
        "skeptic": state["skeptic"],
        "cost": state["cost"],
        "findings": state["findings"],
        "handoff_failures": state.get("handoff_failures", []),
        "adversary_log": [{k: v for k, v in a.items() if k != "scenario"} for a in state.get("adversary_log", [])],
        "trials": state["trials"],
        "replay": "Each trial is deterministic: scenario + trial_seed reproduce it. "
                  "Run `arg-gate replay <this file>` to re-run the trials behind the findings.",
        "scenarios": _scenario_map(state),
        "replay_config": {"policy": cfg.get("policy"), "transport": cfg.get("transport", "inproc"),
                          "l0c": cfg.get("l0c", True), "l0": cfg.get("l0", True)},
        "target_sha256": _file_sha256(state["profile"]["target"]),
    }
    path = out_dir / "evidence.json"
    path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(pack), encoding="utf-8")
    return path


def _e(x: Any) -> str:
    return html.escape(str(x))


def _diff_html(diff: dict) -> str:
    rows = []
    for t, items in diff.get("added", {}).items():
        for r in items:
            rows.append(f"<tr><td>+ {_e(t)}</td><td><code>{_e(r)}</code></td></tr>")
    for t, items in diff.get("removed", {}).items():
        for r in items:
            rows.append(f"<tr><td>- {_e(t)}</td><td><code>{_e(r)}</code></td></tr>")
    for t, items in diff.get("changed", {}).items():
        for r in items:
            rows.append(f"<tr><td>~ {_e(t)} {_e(r['pk'])}</td><td><code>{_e(r['cols'])}</code></td></tr>")
    return "<table>" + ("".join(rows) or "<tr><td colspan=2>no state change</td></tr>") + "</table>"


def _llm_html(p: dict) -> str:
    """L3 judge panel + readable cost. Judge rows are shown as evidence for a human, never as a verdict."""
    llm = p.get("llm") or {}
    cost = p.get("cost") or {}
    spent = cost.get("llm") or {}
    usd = spent.get("est_usd")
    cost_line = (f"{_e(cost.get('agent_seconds', '?'))} s of agent time, {_e(cost.get('trials', '?'))} trials, "
                 f"{_e(cost.get('tool_calls', '?'))} tool calls, LLM tokens {_e(cost.get('llm_tokens', 0))}"
                 + (f" (est. ${usd})" if usd else ""))
    if not llm.get("enabled"):
        return ("<h2>L3 LLM judge</h2><p class=muted>Off for this run (deterministic layers only). "
                "Add <code>--l3</code> to attach an LLM judge. It can only add soft findings.</p>"
                f"<h2>Cost</h2><p>{cost_line}</p>")
    rows = []
    for r in llm.get("rows", [])[:40]:
        if r.get("error"):
            badge, txt = "<span class='tag warn'>judge error</span>", _e(r["error"])
        elif r.get("violation"):
            agree = "L0 also failed it" if r.get("det_hard") else "L0 did not hard-fail it"
            badge = f"<span class='tag flag'>flagged</span> <span class=tag>{_e(r.get('kind'))}</span>"
            txt = f"{_e(r.get('evidence', ''))} <span class=muted>({_e(agree)}; {_e(r.get('confidence'))} confidence)</span>"
        else:
            badge, txt = "<span class='tag ok'>no issue</span>", ""
        rows.append(f"<tr><td>{_e(r.get('scenario_id'))}</td><td>{badge}</td><td>{txt}</td></tr>")
    return f"""<h2>L3 LLM judge <span class=tag>{_e(llm.get('model'))}</span></h2>
<p>Read <b>{_e(llm.get('judged'))}</b> trials, flagged <b>{_e(llm.get('flagged'))}</b>
 ({_e(llm.get('judge_only_flags'))} that the deterministic layer did not hard-fail), errors <b>{_e(llm.get('errors'))}</b>,
 tokens in/out {_e(llm.get('input_tokens'))}/{_e(llm.get('output_tokens'))}.</p>
<p class=muted>The judge sees tool calls, tool results, the state diff and the reply, treats them as untrusted data,
 and can only add a soft finding. It never creates or clears a BLOCK. It is a same-sample, small-n signal for a human.</p>
<table><tr><th>scenario</th><th>judge</th><th>evidence</th></tr>{''.join(rows)}</table>
<h2>Cost</h2><p>{cost_line}</p>"""


def render_html(p: dict) -> str:
    v = p["verdict"]
    color = {"SHIP": "#1a7f37", "BLOCK": "#cf222e"}.get(v["verdict"], "#9a6700")
    hard = [f for f in p["findings"] if f["severity"] == "hard"]
    seen, shown = set(), []
    for f in hard:  # show the first trial per (scenario, kind) so the page stays readable
        key = (f["scenario_id"], f["kind"])
        if key not in seen:
            seen.add(key)
            shown.append(f)
    trial_by = {(t["scenario_id"], t["trial_idx"]): t for t in p["trials"]}
    blocks = []
    for f in shown[:25]:
        t = trial_by.get((f["scenario_id"], f["trial_idx"]), {})
        calls = "".join(f"<li><code>{_e(c['tool'])}({_e(c['args'])})</code>"
                        f"{' <b>ERROR</b> ' + _e(c['error']) if c['error'] else ''}</li>"
                        for c in t.get("tool_calls", []))
        blocks.append(f"""<div class=card><h3>{_e(f['kind'])} <span class=tag>{_e(f['level'])}</span>
<span class=tag>{_e(f['status'])}</span></h3>
<p>{_e(f['message'])}</p>
<p><b>Policy clause</b> [{_e(f['clause'])}]: {_e(v['policy_clauses_cited'].get(f['clause'], ''))}</p>
<p><b>Scenario</b> {_e(f['scenario_id'])} trial {_e(f['trial_idx'])} (seed {_e(t.get('trial_seed'))})</p>
<p><b>Agent said:</b> <em>{_e(t.get('final_message', ''))}</em></p>
<p><b>Agent did (state diff):</b></p>{_diff_html(t.get('diff', {}))}
<p><b>Tool-call trace:</b></p><ul>{calls}</ul></div>""")
    adv = "".join(f"<tr><td>{_e(a['payload_id'])}</td><td>{_e(a['family'])}</td>"
                  f"<td>{'BREACH' if a['breached'] else 'ignored'}</td><td>{_e(a['finding_kinds'])}</td></tr>"
                  for a in p["adversary_log"])
    l1 = p["l1"]
    soft = [f for f in p["findings"] if f["severity"] == "soft"]
    soft_html = ("<h2>Needs a human look (soft findings)</h2><ul>" +
                 "".join(f"<li><b>{_e(f['kind'])}</b>: {_e(f['message'])}</li>" for f in soft[:10]) + "</ul>") if soft else ""
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Agent Release Gate report</title>
<style>:root{{--bg:#fff;--fg:#1f2328;--mut:#656d76;--bd:#d0d7de;--tag:#eaeef2;--card:#f6f8fa}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--bd:#30363d;--tag:#21262d;--card:#161b22}}}}
body{{font:15px/1.5 system-ui,Segoe UI,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:var(--fg);background:var(--bg)}}
.v{{background:{color};color:#fff;padding:14px 18px;border-radius:8px;font-size:22px;font-weight:600}}
.card{{border:1px solid var(--bd);background:var(--card);border-radius:8px;padding:6px 16px;margin:14px 0}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid var(--bd);padding:4px 8px;text-align:left;font-size:13px;vertical-align:top}}
.tag{{background:var(--tag);border-radius:10px;padding:1px 8px;font-size:12px;margin-left:6px}}
.tag.flag{{background:#9a6700;color:#fff}}.tag.ok{{background:#1a7f37;color:#fff}}.tag.warn{{background:#cf222e;color:#fff}}
.muted{{color:var(--mut);font-size:13px}}code{{font-size:12px;word-break:break-word}}
h2{{margin-top:28px;border-bottom:1px solid var(--bd);padding-bottom:4px}}
@media (max-width:600px){{body{{margin:12px auto}}.v{{font-size:18px}}}}</style></head><body>
<div class=v>{_e(v['verdict'])} &nbsp; (exit code {_e(v['exit_code'])})</div>
<p><b>Target:</b> {_e(p['profile']['target'])} &nbsp; <b>Mode:</b> {_e(p['profile']['mode'])}
 &nbsp; <b>k:</b> {_e(l1['k'])}</p>
<ul>{''.join(f'<li>{_e(r)}</li>' for r in v['reasons'])}</ul>
<p><b>pass^{_e(l1['k'])}</b> = {l1['pass_hat_k']:.2f} over {l1['scenarios']} scenarios;
 trial pass rate {l1['trial_pass_rate']:.2f} (95% Wilson {l1['trial_ci'][0]:.2f}-{l1['trial_ci'][1]:.2f}).
 Confirmed hard fails: {v['confirmed_hard']}. Unconfirmed: {v['unconfirmed_hard']}.</p>
<p><i>{_e(v['validity'])}</i></p>
<p><i>{_e(p.get('ai_disclosure') or AI_DISCLOSURE)}</i></p>{soft_html}
<h2>Findings (state diff = what the agent DID)</h2>{''.join(blocks) or '<p>No hard findings.</p>'}
<h2>Adaptive adversary log</h2><table><tr><th>payload</th><th>family</th><th>outcome</th><th>findings</th></tr>{adv or '<tr><td colspan=4>not run in this mode</td></tr>'}</table>
{_llm_html(p)}
<h2>Replay this verdict</h2><p><code>arg-gate replay evidence.json</code> <span class=muted>re-runs the trials behind it and checks they reproduce.</span></p></body></html>"""
