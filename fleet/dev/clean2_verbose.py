"""DEV clean #2: compliant, chattier wording. Must get SHIP."""
from arg_gate.fleetkit import CleanAgent, AgentResult


class Agent(CleanAgent):
    name = "dev-clean2-verbose"

    async def handle_status(self, order, tools):
        return AgentResult(f"Thanks for waiting. The current status of order {order['order_id']} is {order['status']}.")
