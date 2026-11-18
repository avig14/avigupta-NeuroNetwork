"""Policy-as-code loader (plan 5.3 family 3, 6.4 L0). Parses a markdown policy file:
- bullet clauses `- [P-ID] text` (retrieval/grounding, plan 7 Step 5)
- one fenced ```toml block (machine rules)
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_CLAUSE = re.compile(r"^- \[(P-[A-Z0-9-]+)\]\s+(.*)$", re.M)
_TOML = re.compile(r"```toml\s*\n(.*?)```", re.S)


@dataclass
class Policy:
    path: str
    clauses: dict[str, str]
    max_refund_without_approval: float
    approvers: list[str]
    canary_tokens: list[str]
    raw_rules: dict = field(default_factory=dict)

    def retrieve(self, clause_id: str) -> str:
        return self.clauses.get(clause_id, "")


def load_policy(path: str | Path) -> Policy:
    text = Path(path).read_text(encoding="utf-8")
    clauses = {m.group(1): m.group(2).strip() for m in _CLAUSE.finditer(text)}
    block = _TOML.search(text)
    if not block:
        raise ValueError(f"{path}: no ```toml machine-rules block found")
    rules = tomllib.loads(block.group(1))
    return Policy(
        path=str(path),
        clauses=clauses,
        max_refund_without_approval=float(rules["refunds"]["max_without_approval"]),
        approvers=list(rules["refunds"]["approvers"]),
        canary_tokens=list(rules["canary"]["tokens"]),
        raw_rules=rules,
    )
