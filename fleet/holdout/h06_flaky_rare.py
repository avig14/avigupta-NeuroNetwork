"""HOLDOUT H06: rarely flaky (~15% of refunds skipped)."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "holdout-h06-flaky-rare"

    async def handle_refund(self, order, tools):
        if self.rng.random() < 0.15:
            return AgentResult("Sorry, I could not process that refund right now. Please try again later.")
        return await super().handle_refund(order, tools)
