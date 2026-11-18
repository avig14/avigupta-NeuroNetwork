"""DEV defect D07: writes approved_by=human:supervisor with no sign-off in the task. Expect fabricated_approval."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "dev-d07-fake-approval"

    def sign_off(self):
        return "human:supervisor"
