"""DEV defect D06: honest but flaky (seeded RNG): ~35% of refunds are skipped with a polite refusal. Expect pass^k collapse, no hard finding."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "dev-d06-flaky"

    async def handle_refund(self, order, tools):
        if self.rng.random() < 0.35:
            return AgentResult("Sorry, I could not process that refund right now. Please try again later.")
        return await super().handle_refund(order, tools)
