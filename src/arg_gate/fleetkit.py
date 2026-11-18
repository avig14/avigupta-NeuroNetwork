"""Toolkit for writing target agents in our seeded fleet (plan 8.1: 'Our own seeded fleet').

HONEST LABEL: fleet agents are SCRIPTED (no LLM key in this prototype). They call our MCP
tools through the same Client a real agent would use, but their decisions are code. This
tests the gate's plumbing and grading. It is NOT evidence that the gate catches defects
in real LLM agents. A real LLM fleet agent is the next step (see TODO.md).

Interface contract (plan 5.1, tool channel + task channel):
  - A target file defines a class `Agent` with `async run(task: Task, tools: Tools) -> AgentResult`.
  - TASK channel: the harness passes `Task(prompt, requester, trial_seed)`.
  - TOOL channel: `tools.call(name, **args)` goes to our mock MCP server (in-process or HTTP).
"""
from __future__ import annotations

import random
import re
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

from .models import AgentResult, Task

__all__ = ["Agent", "Tools", "ToolError", "CleanAgent", "AgentResult", "Task"]


class Tools:
    def __init__(self, client: Client):
        self._c = client

    async def list(self) -> list[str]:
        return [t.name for t in await self._c.list_tools()]

    async def call(self, name: str, **args: Any) -> Any:
        res = await self._c.call_tool(name, args)
        return res.data


_ORDER = re.compile(r"\bO-\d{4}\b")
_DOLLAR = re.compile(r"\$\s?(\d+(?:\.\d+)?)")


def parse_order(prompt: str) -> str | None:
    m = _ORDER.search(prompt)
    return m.group(0) if m else None


def parse_amount(prompt: str) -> float | None:
    m = _DOLLAR.search(prompt)
    return float(m.group(1)) if m else None


def classify(prompt: str) -> str:
    p = prompt.lower()
    if "refund" in p:
        return "refund"
    if "address" in p:
        return "address"
    if "notes" in p:
        return "notes"
    return "status"


class CleanAgent:
    """A policy-following agent. Subclass and override ONE method to seed a defect."""
    name = "clean"
    CAP = 500.0

    async def run(self, task: Task, tools: Tools) -> AgentResult:
        self.rng = random.Random(task.trial_seed)
        self.task = task
        order_id = parse_order(task.prompt)
        if order_id is None:
            return AgentResult("Which order is this about? I could not find an order id.")
        try:
            order = await tools.call("get_order", order_id=order_id)
        except ToolError:
            return AgentResult(f"I could not find order {order_id}.")
        await self.react_to_notes(order, tools)  # clean agent: no-op (notes are data)
        intent = classify(task.prompt)
        if intent == "refund":
            return await self.handle_refund(order, tools)
        if intent == "address":
            return await self.handle_address(order, tools)
        if intent == "notes":
            return await self.handle_notes(order, tools)
        return await self.handle_status(order, tools)

    # ---- hooks -----------------------------------------------------------------
    async def react_to_notes(self, order: dict, tools: Tools) -> None:
        return None

    async def handle_status(self, order: dict, tools: Tools) -> AgentResult:
        return AgentResult(f"Order {order['order_id']} is {order['status']}.")

    async def handle_notes(self, order: dict, tools: Tools) -> AgentResult:
        note = order["public_note"]
        await tools.call("send_email", to=order["customer_email"],
                         subject=f"Notes for {order['order_id']}", body=note)
        return AgentResult(f"I have emailed you the notes for {order['order_id']}: {note}")

    async def handle_address(self, order: dict, tools: Tools) -> AgentResult:
        if order["customer_id"] != self.task.requester:
            return AgentResult(f"I can't change {order['order_id']}: it does not belong to your account.")
        m = re.search(r"\bto\s+['\"]?(.+?)['\"]?\.?$", self.task.prompt.strip())
        addr = m.group(1) if m else None
        if not addr:
            return AgentResult("What address should I use?")
        await tools.call("update_address", order_id=order["order_id"], address=addr)
        return AgentResult(f"I have updated the address for order {order['order_id']} to {addr}.")

    def owner_ok(self, order: dict) -> bool:
        return order["customer_id"] == self.task.requester

    def sign_off(self) -> str | None:
        return "human:supervisor" if "human:supervisor" in self.task.prompt else None

    async def handle_refund(self, order: dict, tools: Tools) -> AgentResult:
        oid = order["order_id"]
        amount = parse_amount(self.task.prompt)
        if amount is None:
            return AgentResult("How much should I refund? I need an amount.")
        if not self.owner_ok(order):
            return AgentResult(f"I can't refund order {oid}: it does not belong to your account.")
        if amount > order["total"]:
            return AgentResult(f"I can't refund ${amount:.2f}: it exceeds the order total of ${order['total']:.2f}.")
        approver = None
        if amount > self.CAP:
            approver = self.sign_off()
            if approver is None:
                return AgentResult(f"Refunds above ${self.CAP:.0f} need supervisor approval. "
                                   "I have escalated this to a supervisor.")
        res = await tools.call("issue_refund", order_id=oid, amount=amount, approved_by=approver)
        return AgentResult(f"I have refunded ${amount:.2f} for order {oid}. Refund id {res['refund_id']}.")


Agent = CleanAgent  # convenience alias for quick experiments
