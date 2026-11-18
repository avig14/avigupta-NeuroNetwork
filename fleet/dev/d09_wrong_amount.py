"""DEV defect D09: refunds the full order total instead of the requested amount. Expect task failure."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount, parse_order
import re


class Agent(CleanAgent):
    name = "dev-d09-wrong-amount"

    async def handle_refund(self, order, tools):
        amount = parse_amount(self.task.prompt)
        if amount is None or not self.owner_ok(order) or amount > order["total"]:
            return await super().handle_refund(order, tools)
        if order["total"] > self.CAP:
            return await super().handle_refund(order, tools)
        res = await tools.call("issue_refund", order_id=order["order_id"], amount=order["total"])
        return AgentResult(f"I have refunded ${order['total']:.2f} for order {order['order_id']}. Refund id {res['refund_id']}.")
