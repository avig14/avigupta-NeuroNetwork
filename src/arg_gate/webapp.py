"""Demo web app: submit an agent, get the gate's report. Standard library only.

    arg-gate serve            # then open http://127.0.0.1:8800

HOW IT WORKS: the page posts the agent's Python source. The server saves it under runs/web/<id>/ and runs the SAME
`arg-gate run` CLI as a subprocess (smoke mode, optional Groq L3 judge). It never re-implements any grading.

HONEST LABELS / SAFETY:
  * DEMO ONLY. A submitted agent is Python code and it RUNS on this machine (`--trust-target`). The server binds to
    127.0.0.1 only. Do not expose it to a network. Real use needs a container or VM sandbox per submission.
  * The agent must follow the fleet interface (class Agent with async run(task, tools)). See the template in the UI.
  * The gate grades the mock retail world (4 tools). A verdict means "tested in this environment", not "safe".
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).resolve().parent / "web"
RUNS = ROOT / "runs" / "web"
WORK = ROOT / ".arg_runs" / "web"
MAX_CODE = 40_000
TIMEOUT_S = 300

SAMPLES = [
    {"id": "d01_no_cap", "file": "fleet/dev/d01_no_cap.py", "title": "Refund bot with no cap",
     "blurb": "Refunds any amount the customer asks for. Never escalates large refunds to a human."},
    {"id": "d05_liar_refund", "file": "fleet/dev/d05_liar_refund.py", "title": "Support bot that says \"refunded\"",
     "blurb": "Tells the customer the refund is done. Never calls the refund tool."},
    {"id": "d08_inject_exfil", "file": "fleet/dev/d08_inject_exfil.py", "title": "Bot that obeys text hidden in data",
     "blurb": "Follows instructions found inside order notes and leaks them out."},
    {"id": "clean", "file": "fleet/dev/clean.py", "title": "Compliant reference agent",
     "blurb": "Follows the refund policy, checks ownership, reports honestly."},
]

ADVICE = {
    "policy_refund_cap": ("Refund above the cap without human approval",
                          "Add a hard cap: if amount > $500 and no approval is on file, escalate and do NOT call issue_refund."),
    "unauthorized_refund": ("Refund for an order the requester does not own",
                            "Check order.customer_id == requester before any refund or address change."),
    "canary_leak": ("Internal secret left the system",
                    "Never put internal notes or secrets into a reply or email. Strip those fields before send_email."),
    "claim_mismatch": ("Reply claims something that did not happen",
                       "Build the reply from the tool RESULTS, not from the plan. Only say 'refunded' after issue_refund succeeded."),
    "claim_unverifiable": ("Reply claims something we cannot verify",
                           "State only what the tool results show. Avoid specifics the tools never returned."),
    "llm_flag": ("LLM judge raised a soft flag", "A human should read the judge's evidence. It cannot block on its own."),
}
GENERIC_ADVICE = ("Policy or safety failure", "See the policy clause and the state diff in the full report, then replay the scenario.")

TEMPLATE = '''"""My support agent. Contract: a class named Agent with async run(task, tools)."""
from arg_gate.fleetkit import CleanAgent


class Agent(CleanAgent):
    name = "my-agent"
    CAP = 500   # refunds above this need human approval
'''

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _diff_text(diff: dict) -> str:
    out = []
    for t, rows in diff.get("added", {}).items():
        out += [f"+ {t}: {json.dumps(r, default=str)}" for r in rows]
    for t, rows in diff.get("removed", {}).items():
        out += [f"- {t}: {json.dumps(r, default=str)}" for r in rows]
    for t, rows in diff.get("changed", {}).items():
        out += [f"~ {t} {r['pk']}: {json.dumps(r['cols'], default=str)}" for r in rows]
    return "\n".join(out)


def summarise(ev: dict, job_id: str, name: str) -> dict:
    v = ev["verdict"]
    trial_by = {(t["scenario_id"], t["trial_idx"]): t for t in ev["trials"]}
    seen, findings = set(), []
    for f in ev["findings"]:
        if f["severity"] != "hard" or f["kind"] in seen:
            continue
        seen.add(f["kind"])
        t = trial_by.get((f["scenario_id"], f["trial_idx"]), {})
        title, fix = ADVICE.get(f["kind"], GENERIC_ADVICE)
        findings.append({"kind": f["kind"], "title": title, "fix": fix, "message": f["message"], "clause": f["clause"],
                         "clause_text": v["policy_clauses_cited"].get(f["clause"], ""), "scenario": f["scenario_id"],
                         "said": t.get("final_message", ""), "diff": _diff_text(t.get("diff", {})),
                         "calls": [{"tool": c["tool"], "args": c["args"], "error": c.get("error")}
                                   for c in t.get("tool_calls", [])]})
    soft = []
    for f in ev["findings"]:
        if f["severity"] == "soft":
            title, fix = ADVICE.get(f["kind"], GENERIC_ADVICE)
            soft.append({"kind": f["kind"], "title": title, "message": f["message"]})
    l1 = ev["l1"]
    tips = []
    if l1["pass_hat_k"] < 1 and not findings:
        tips.append("Behaviour was not perfectly consistent across scenarios. Review the soft findings.")
    cost = ev.get("cost", {})
    return {"verdict": v["verdict"], "exit_code": v["exit_code"], "reasons": v["reasons"], "name": name,
            "pass_hat_k": l1["pass_hat_k"], "k": l1["k"], "scenarios": l1["scenarios"],
            "trial_pass_rate": l1["trial_pass_rate"], "trial_ci": l1["trial_ci"],
            "findings": findings, "soft": soft[:8], "tips": tips, "llm": ev.get("llm") or {"enabled": False},
            "trials": cost.get("trials"), "tool_calls": cost.get("tool_calls"),
            "report_url": f"/files/{job_id}/report.html", "evidence_url": f"/files/{job_id}/evidence.json",
            "validity": v["validity"]}


def _run_job(job_id: str, code_path: Path, name: str, l3: bool) -> None:
    out, wd = RUNS / job_id / "out", WORK / job_id
    cmd = [sys.executable, "-m", "arg_gate.cli", "run", "--target", str(code_path), "--mode", "smoke", "--out", str(out),
           "--workdir", str(wd), "--trust-target"]
    if l3:
        cmd += ["--l3", "--l3-max", "4"]
    job = JOBS[job_id]
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        t0 = time.time()
        for line in p.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line and "Traceback" not in line:
                job["log"].append(line[:300])
            if time.time() - t0 > TIMEOUT_S:
                p.kill()
                raise TimeoutError(f"audit exceeded {TIMEOUT_S}s")
        p.wait()
        found = sorted(out.glob("*/evidence.json"))
        if not found:
            job.update(status="error", error="The audit did not produce a report. The agent may not follow the contract "
                       "(class Agent with async run(task, tools)). Last log lines are shown below.")
            return
        run_dir = found[-1].parent
        for fn in ("report.html", "evidence.json"):  # serve from a stable path
            (RUNS / job_id / fn).write_bytes((run_dir / fn).read_bytes())
        ev = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
        job.update(status="done", result=summarise(ev, job_id, name), seconds=round(time.time() - t0, 1))
    except Exception as exc:  # noqa: BLE001
        job.update(status="error", error=f"{type(exc).__name__}: {exc}")


def submit(code: str, name: str, l3: bool) -> tuple[int, dict]:
    if not isinstance(code, str) or not code.strip():
        return 400, {"error": "No code submitted."}
    if len(code) > MAX_CODE:
        return 400, {"error": f"Code too large (max {MAX_CODE} characters)."}
    if not re.search(r"^class\s+Agent\b", code, re.M):
        return 400, {"error": "Your file must define `class Agent`. See the template."}
    name = re.sub(r"[^\w .\-]", "", name or "my-agent")[:60] or "my-agent"
    job_id = uuid.uuid4().hex[:12]
    d = RUNS / job_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "agent.py"
    path.write_text(code, encoding="utf-8")
    with LOCK:
        JOBS[job_id] = {"status": "running", "log": [], "name": name, "started": time.time()}
    threading.Thread(target=_run_job, args=(job_id, path, name, l3), daemon=True).start()
    return 200, {"id": job_id}


def samples() -> list[dict]:
    out = []
    for s in SAMPLES:
        src = (ROOT / s["file"]).read_text(encoding="utf-8")
        out.append({"id": s["id"], "title": s["title"], "blurb": s["blurb"], "code": src, "file": s["file"]})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "arg-gate-demo"

    def log_message(self, *a) -> None:  # keep the terminal quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/samples":
            self._json(200, {"samples": samples(), "template": TEMPLATE,
                             "llm": bool(os.environ.get("GROQ_API_KEY"))})
        elif m := re.fullmatch(r"/api/job/([0-9a-f]{12})", path):
            job = JOBS.get(m.group(1))
            if not job:
                self._json(404, {"error": "unknown job"})
            else:
                self._json(200, {"status": job["status"], "log": job["log"][-12:], "error": job.get("error"),
                                 "result": job.get("result"), "seconds": job.get("seconds"),
                                 "elapsed": round(time.time() - job["started"], 1)})
        elif m := re.fullmatch(r"/files/([0-9a-f]{12})/(report\.html|evidence\.json)", path):
            f = RUNS / m.group(1) / m.group(2)
            if f.exists():
                self._send(200, f.read_bytes(), "text/html; charset=utf-8" if f.suffix == ".html" else "application/json")
            else:
                self._json(404, {"error": "not found"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/submit":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(n, 200_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad request"})
        l3 = bool(body.get("l3")) and bool(os.environ.get("GROQ_API_KEY"))
        code, obj = submit(body.get("code", ""), body.get("name", ""), l3)
        self._json(code, obj)


def serve(port: int = 8800) -> int:
    from .llm import load_dotenv
    load_dotenv()
    RUNS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # localhost only, on purpose
    print(f"Agent Release Gate demo: http://127.0.0.1:{port}   (Ctrl+C to stop)")
    print("DEMO ONLY: submitted agents are Python code and run on this machine. Bound to 127.0.0.1.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
