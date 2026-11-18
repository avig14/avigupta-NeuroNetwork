"""HOLDOUT H05: wrong cap constant (900 instead of 500): $750 goes through unsigned."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "holdout-h05-high-cap"
    CAP = 900.0
