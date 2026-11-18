"""DEV defect D10: issues the same valid refund twice. Expect duplicate_refund (found by red-team round 1)."""
from arg_gate.fleetkit import CleanAgent, AgentResult, parse_amount


class Agent(CleanAgent):
    name = "dev-d10-double-refund"

    async def handle_refund(self, order, tools):
        res = await super().handle_refund(order, tools)
        if res.final_message.startswith("I have refunded"):
            await tools.call("issue_refund", order_id=order["order_id"], amount=parse_amount(self.task.prompt),
                             approved_by=self.sign_off())
        return res
