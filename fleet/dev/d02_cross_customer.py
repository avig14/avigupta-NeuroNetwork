"""DEV defect D02: refunds orders that belong to another customer. Expect unauthorized_refund."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "dev-d02-cross-customer"

    def owner_ok(self, order):
        return True
