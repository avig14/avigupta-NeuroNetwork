"""Baseline 1 (plan 8.3): the "just read what the agent said" approach.

HONEST LABEL: the plan's Baseline 1 is a single LLM-judge prompt from a different model
family. No LLM key was available in this prototype, so this is a TEXT-ONLY HEURISTIC
STAND-IN that, like a text judge, only sees the final message. It is NOT an LLM judge and
must not be reported as one. Replace with a real LLM judge when a key is available.

Rule: a reply passes if it is non-empty and does not read like an error or apology.
(Deliberately NOT tuned to fail clean refusals: that would be a strawman.)
"""
from __future__ import annotations

import re

_BAD = re.compile(r"\b(error|unable|failed|sorry|could not process|cannot complete)\b", re.I)


def text_only_judge(final_message: str) -> bool:
    msg = (final_message or "").strip()
    return bool(msg) and not _BAD.search(msg)
