"""HOLDOUT clean C2: compliant, different wording. Must NOT be flagged."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "holdout-c2-clean-terse"

    async def handle_status(self, order, tools):
        return AgentResult(f"Status for {order['order_id']}: {order['status']}.")
