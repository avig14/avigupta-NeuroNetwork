"""Agent Release Gate (arg-gate).

Grade what the agent DID to the data, not what it SAID.
Verdicts are valid for the tested environment only.
"""

__version__ = "0.1.0"

# Plan section 5.2: every verdict carries this caveat.
VALIDITY_NOTE = (
    "Valid for the tested environment only (mock MCP world, k trials). "
    "'SHIP' means no failure found in this environment, not 'safe'."
)
