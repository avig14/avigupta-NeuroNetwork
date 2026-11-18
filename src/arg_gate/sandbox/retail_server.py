"""Mock retail MCP server (FastMCP + SQLite). Plan 5.1 / 6.3 sandbox.

Four tools per plan P0a: get_order, issue_refund, update_address, send_email.
The server does basic input validation only. It does NOT enforce the refund policy:
policy is the target agent's job and the grader's check (plan 6.7: judge the effect).
Every call is logged to the tool_calls table (trace for evidence).
Run standalone over Streamable HTTP:
    ARG_DB_PATH=live.db python -m arg_gate.sandbox.retail_server --port 8765
"""
from __future__ import annotations

import functools
import json
import os
import sys
from typing import Any, Callable

from fastmcp import FastMCP

from .db import connect


def _log(db_path: str, tool: str, args: dict, result: Any, error: str | None) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO tool_calls(tool, args_json, result_json, error) VALUES (?,?,?,?)",
            (tool, json.dumps(args, default=str),
             json.dumps(result, default=str) if result is not None else None, error))
        conn.commit()
    finally:
        conn.close()


def make_server(db_path: str) -> FastMCP:
    """Build a retail MCP server bound to one SQLite file. Connections are per call,
    so the harness can replace the file between trials."""
    mcp = FastMCP("retail-sandbox")

    def logged(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(**kwargs):
            try:
                result = fn(**kwargs)
            except Exception as exc:  # logged, then re-raised to the caller as ToolError
                _log(db_path, fn.__name__, kwargs, None, str(exc))
                raise
            _log(db_path, fn.__name__, kwargs, result, None)
            return result
        return wrapper

    @mcp.tool
    @logged
    def get_order(order_id: str) -> dict:
        """Return an order: customer, total, status, address, public_note, internal_note."""
        conn = connect(db_path)
        try:
            row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if row is None:
                raise ValueError(f"order {order_id} not found")
            cust = conn.execute("SELECT email FROM customers WHERE customer_id=?",
                                (row["customer_id"],)).fetchone()
            out = dict(row)
            out["customer_email"] = cust["email"] if cust else None
            return out
        finally:
            conn.close()

    @mcp.tool
    @logged
    def issue_refund(order_id: str, amount: float, approved_by: str | None = None) -> dict:
        """Issue a refund on an order. amount must be > 0 and <= order total.
        approved_by records a human approver when one signed off."""
        conn = connect(db_path)
        try:
            row = conn.execute("SELECT total FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if row is None:
                raise ValueError(f"order {order_id} not found")
            if amount <= 0 or amount > row["total"]:
                raise ValueError(f"invalid refund amount {amount} for order total {row['total']}")
            cur = conn.execute(
                "INSERT INTO refunds(order_id, amount, approved_by) VALUES (?,?,?)",
                (order_id, amount, approved_by))
            conn.execute("UPDATE orders SET status='refunded' WHERE order_id=?", (order_id,))
            conn.commit()
            return {"refund_id": cur.lastrowid, "order_id": order_id, "amount": amount}
        finally:
            conn.close()

    @mcp.tool
    @logged
    def update_address(order_id: str, address: str) -> dict:
        """Update the shipping address of an order."""
        conn = connect(db_path)
        try:
            cur = conn.execute("UPDATE orders SET address=? WHERE order_id=?", (address, order_id))
            if cur.rowcount == 0:
                raise ValueError(f"order {order_id} not found")
            conn.commit()
            return {"order_id": order_id, "address": address}
        finally:
            conn.close()

    @mcp.tool
    @logged
    def send_email(to: str, subject: str, body: str) -> dict:
        """Send an email (mock outbox)."""
        conn = connect(db_path)
        try:
            cur = conn.execute("INSERT INTO outbox(to_addr, subject, body) VALUES (?,?,?)",
                               (to, subject, body))
            conn.commit()
            return {"msg_id": cur.lastrowid, "to": to}
        finally:
            conn.close()

    return mcp


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    port = 8765
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    db_path = os.environ["ARG_DB_PATH"]
    make_server(db_path).run(transport="http", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
