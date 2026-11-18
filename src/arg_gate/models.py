"""Shared data shapes. Plain dataclasses so evidence packs serialise to JSON easily."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Scenario:
    """One test case plus its ORACLE (plan 6.5: every scenario ships with its oracle)."""
    id: str
    campaign: str                      # reliability | security | policy
    prompt: str                        # task sent over the task channel
    requester: str                     # customer id making the request
    seed: list[tuple[str, list[Any]]] = field(default_factory=list)  # SQL applied before the run
    # --- oracle ---
    expected_refund: dict | None = None        # {"order_id", "amount"} or None (= no refund expected)
    expected_address_update: dict | None = None  # {"order_id", "address"}
    expected_message_any: list[str] = field(default_factory=list)  # reply must contain one (lowercase)
    allowed_refund_orders: list[str] = field(default_factory=list)
    allowed_address_updates: list[str] = field(default_factory=list)
    allowed_email_to: list[str] = field(default_factory=list)
    approval_granted: bool = False             # a human sign-off is present in the prompt
    meta: dict = field(default_factory=dict)   # e.g. payload id for security scenarios

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Task:
    """What the target agent receives on the task channel (plan 5.1)."""
    prompt: str
    requester: str
    trial_seed: int


@dataclass
class AgentResult:
    final_message: str


@dataclass
class Finding:
    kind: str            # policy_refund_cap | canary_leak | claim_mismatch | ...
    level: str           # L0 | L0c | L1
    severity: str        # hard | soft
    message: str
    clause: str          # policy clause id (grounding, plan 7 Step 5)
    evidence: dict = field(default_factory=dict)
    scenario_id: str = ""
    trial_idx: int = -1
    status: str = "unreviewed"   # unreviewed | confirmed | unconfirmed (set by skeptic)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrialRecord:
    scenario_id: str
    campaign: str
    trial_idx: int
    trial_seed: int
    final_message: str = ""
    error: str | None = None
    retried: bool = False
    duration_s: float = 0.0
    pre: dict = field(default_factory=dict)
    post: dict = field(default_factory=dict)
    diff: dict = field(default_factory=dict)
    tool_calls: list = field(default_factory=list)
    findings: list = field(default_factory=list)   # list[dict] (Finding.to_dict)
    task_completed: bool = False
    passed: bool = False
    text_only_pass: bool = False   # Baseline 1 verdict on the same trial

    def to_dict(self) -> dict:
        return asdict(self)
