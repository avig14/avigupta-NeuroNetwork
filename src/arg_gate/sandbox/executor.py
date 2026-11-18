"""Deterministic NON-LLM executor (plan 6.5): restores a clean DB per trial, serves the
mock MCP tools, records trace + state, then runs the L0/L0c graders.

Transports: 'inproc' (FastMCP in-memory Client) or 'http' (Streamable HTTP subprocess).
Error path (plan 7 Step 3/4): a trial that errors or times out is retried once.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import socket
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Any

from fastmcp import Client

from ..fleetkit import Tools
from ..graders.baseline import text_only_judge
from ..graders.l0 import grade_l0, task_completed
from ..graders.l0c import grade_l0c
from ..models import Scenario, Task, TrialRecord
from ..policy import Policy
from .db import build_clean_db, diff_snapshots, read_tool_calls, reset_db, snapshot
from .retail_server import make_server

TRIAL_TIMEOUT_S = 20.0


def trial_seed(scenario_id: str, trial_idx: int) -> int:
    return zlib.crc32(f"{scenario_id}:{trial_idx}".encode())


def load_agent_class(path: str | Path):
    """Load `Agent` from a target file. Plan 6.9: only run code you trust (fleet = our own)."""
    p = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"target_{p.stem}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.Agent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sandbox:
    """One sandbox = one live DB file + one MCP server. One per campaign worker (no sharing)."""

    def __init__(self, workdir: str | Path, clean_db: str | Path, transport: str = "inproc"):
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.clean_db = Path(clean_db)
        self.live_db = self.workdir / "live.db"
        self.transport = transport
        self._proc: subprocess.Popen | None = None
        self._target: Any = None

    async def __aenter__(self) -> "Sandbox":
        reset_db(self.clean_db, self.live_db)
        if self.transport == "http":
            port = _free_port()
            env = {**os.environ, "ARG_DB_PATH": str(self.live_db)}
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "arg_gate.sandbox.retail_server", "--port", str(port)],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._target = f"http://127.0.0.1:{port}/mcp"
            for _ in range(60):  # wait until the server answers
                try:
                    async with Client(self._target) as c:
                        await c.list_tools()
                    break
                except Exception:
                    await asyncio.sleep(0.5)
            else:
                raise RuntimeError("HTTP sandbox did not start")
        else:
            self._target = make_server(str(self.live_db))
        return self

    async def __aexit__(self, *exc) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def client(self) -> Client:
        return Client(self._target)

    def reset(self, seed) -> None:
        reset_db(self.clean_db, self.live_db, seed)


async def _attempt(agent_cls, scn: Scenario, idx: int, sb: Sandbox, policy: Policy,
                   l0c: bool) -> TrialRecord:
    seed = trial_seed(scn.id, idx)
    sb.reset(scn.seed)
    rec = TrialRecord(scenario_id=scn.id, campaign=scn.campaign, trial_idx=idx, trial_seed=seed)
    rec.pre = snapshot(sb.live_db)
    t0 = time.perf_counter()
    async with sb.client() as client:
        result = await asyncio.wait_for(
            agent_cls().run(Task(scn.prompt, scn.requester, seed), Tools(client)), TRIAL_TIMEOUT_S)
    rec.duration_s = time.perf_counter() - t0
    rec.final_message = result.final_message
    rec.post = snapshot(sb.live_db)
    rec.diff = diff_snapshots(rec.pre, rec.post)
    rec.tool_calls = read_tool_calls(sb.live_db)
    findings = grade_l0(scn, rec, policy)
    if l0c:
        findings += grade_l0c(rec)
    for f in findings:
        f.scenario_id, f.trial_idx = scn.id, idx
    rec.findings = [f.to_dict() for f in findings]
    rec.task_completed = task_completed(scn, rec)
    rec.passed = rec.task_completed and not any(f["severity"] == "hard" for f in rec.findings)
    rec.text_only_pass = text_only_judge(rec.final_message)
    return rec


async def run_trial(agent_cls, scn: Scenario, idx: int, sb: Sandbox, policy: Policy,
                    l0c: bool = True) -> TrialRecord:
    """Run one trial. On error/timeout retry ONCE (retry-recovery is tracked, meta-eval G)."""
    last_err = ""
    for attempt in range(2):
        try:
            rec = await _attempt(agent_cls, scn, idx, sb, policy, l0c)
            rec.retried = attempt == 1
            return rec
        except Exception as exc:  # agent crash, timeout, transport error
            last_err = f"{type(exc).__name__}: {exc}"
    rec = TrialRecord(scenario_id=scn.id, campaign=scn.campaign, trial_idx=idx,
                      trial_seed=trial_seed(scn.id, idx), error=last_err, retried=True)
    return rec


def ensure_clean_db(workdir: str | Path) -> Path:
    return build_clean_db(Path(workdir) / "clean.db")
