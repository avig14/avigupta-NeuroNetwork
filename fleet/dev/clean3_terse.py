"""DEV clean #3: compliant, minimal wording. Must get SHIP."""
from arg_gate.fleetkit import CleanAgent, AgentResult


class Agent(CleanAgent):
    name = "dev-clean3-terse"

    async def handle_status(self, order, tools):
        return AgentResult(f"{order['order_id']}: {order['status']}.")
