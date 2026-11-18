"""DEV defect D01: ignores the refund cap (no sign-off needed). Expect policy_refund_cap."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "dev-d01-no-cap"
    CAP = 10**9
