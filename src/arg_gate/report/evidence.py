"""Evidence pack (plan 5.1 output): JSON + a self-contained HTML viewer (plan 7 Step 7)."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


# Plan Step 7 (behaviour profile): disclose AI-generated parts. Here there are none in the verdict path.
AI_DISCLOSURE = ("Automation disclosure: this report was produced by an automated release gate. Every verdict, "
                 "finding and number in it is computed by deterministic code (state diff, canary scan, policy rules, "
                 "pass^k, replay). No language model wrote or graded any of it in this prototype. The tool and its "
                 "scripted test agents were written with AI coding assistance. Test data is synthetic; nothing "
                 "leaves this machine.")


def write_evidence_pack(state: dict, out_dir: Path, validity: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pack = {
        "validity": validity,
        "ai_disclosure": AI_DISCLOSURE,
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
        "replay": "Each trial is deterministic: scenario id + trial_seed reproduce it. "
                  "See trials[].scenario_id / trial_seed.",
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
    return f"""<!doctype html><html><head><meta charset=utf-8><title>Agent Release Gate report</title>
<style>body{{font:15px system-ui;max-width:980px;margin:24px auto;padding:0 16px;color:#1f2328}}
.v{{background:{color};color:#fff;padding:14px 18px;border-radius:8px;font-size:22px}}
.card{{border:1px solid #d0d7de;border-radius:8px;padding:6px 16px;margin:14px 0}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #d0d7de;padding:4px 8px;text-align:left;font-size:13px}}
.tag{{background:#eaeef2;border-radius:10px;padding:1px 8px;font-size:12px;margin-left:6px}}
code{{font-size:12px}}</style></head><body>
<div class=v>{_e(v['verdict'])} &nbsp; (exit code {_e(v['exit_code'])})</div>
<p><b>Target:</b> {_e(p['profile']['target'])} &nbsp; <b>Mode:</b> {_e(p['profile']['mode'])}
 &nbsp; <b>k:</b> {_e(l1['k'])}</p>
<ul>{''.join(f'<li>{_e(r)}</li>' for r in v['reasons'])}</ul>
<p><b>pass^{_e(l1['k'])}</b> = {l1['pass_hat_k']:.2f} over {l1['scenarios']} scenarios;
 trial pass rate {l1['trial_pass_rate']:.2f} (95% Wilson {l1['trial_ci'][0]:.2f}-{l1['trial_ci'][1]:.2f}).
 Confirmed hard fails: {v['confirmed_hard']}. Unconfirmed: {v['unconfirmed_hard']}.</p>
<p><i>{_e(v['validity'])}</i></p>
<p><i>{_e(AI_DISCLOSURE)}</i></p>{soft_html}
<h2>Findings (state diff = what the agent DID)</h2>{''.join(blocks) or '<p>No hard findings.</p>'}
<h2>Adaptive adversary log</h2><table><tr><th>payload</th><th>family</th><th>outcome</th><th>findings</th></tr>{adv or '<tr><td colspan=4>not run in this mode</td></tr>'}</table>
<h2>Cost</h2><p>{_e(p['cost'])}</p></body></html>"""
