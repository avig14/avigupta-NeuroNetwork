"""Adaptive adversary (plan 5.3 / 6.5): multi-turn, picks its next attack from what the
last attempt did. Prototype deviation: the plan's adversary is an LLM agent. No LLM key
was available, so this is a deterministic escalation strategy:

  1. try overt payloads, then subtler ones up the LADDER (authority, politeness, fake tool result)
  2. when a whole rung is ignored, escalate to the next rung
  3. when the ladder is exhausted, MUTATE payloads that failed (authority prefix, urgency, role-play)
  4. stop at the first breach or when the attempt budget is spent

It adapts to observed outcomes (ignored vs breached) but does not invent new attacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Scenario
from .scenarios import LADDER, MUTATIONS, PAYLOADS, injection_scenario

_BY_ID = {p[0]: p for p in PAYLOADS}


@dataclass
class Adversary:
    max_attempts: int = 8
    history: list[dict] = field(default_factory=list)

    def _queue(self) -> list[tuple[str, str, str]]:
        q: list[tuple[str, str, str]] = []
        for rung in LADDER:
            for pid in rung:
                q.append(_BY_ID[pid])
        # mutation phase: only payloads that were tried and ignored
        for mname, fn in MUTATIONS.items():
            for pid in ("I01", "I02", "I04"):
                _, fam, text = _BY_ID[pid]
                q.append((f"{pid}+{mname}", f"{fam}+{mname}", fn(text)))
        return q

    def next_scenario(self) -> Scenario | None:
        if len(self.history) >= self.max_attempts:
            return None
        if self.history and self.history[-1]["breached"]:
            return None  # breach found, stop
        tried = {h["payload_id"] for h in self.history}
        for pid, fam, text in self._queue():
            if pid not in tried:
                return injection_scenario(pid, fam, text)
        return None

    def observe(self, scn: Scenario, breached: bool, finding_kinds: list[str]) -> None:
        self.history.append({"payload_id": scn.meta["payload_id"], "family": scn.meta["family"],
                             "breached": breached, "finding_kinds": finding_kinds})
