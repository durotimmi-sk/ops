import json
import logging
import sqlite3
import sys

from taskvault_core import (
    append_event,
    create_price_watch,
    create_task,
    decide_approval,
    get_task,
    initialize_database,
    list_activity,
    list_approvals,
    list_price_watches,
    list_tasks,
    load_dotenv,
    save_research,
    task_result,
    update_task,
    verify_audit_ledger,
)
from taskvault_research import extract_quantity, match_product
from taskvault_sandbox import run_worker


LOG = logging.getLogger("taskvault.mcp")
PROTOCOL_VERSION = "2024-11-05"


TOOLS = [
    {
        "name": "create_research_task",
        "description": "Record a TaskVault sourcing request with optional public source URLs. This only records the request; use source_suppliers to run the deterministic comparison.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The sourcing request."},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri"},
                    "maxItems": 20,
                    "description": "Optional public HTTP or HTTPS source URLs supplied by the user.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "source_suppliers",
        "description": "Run a bounded sourcing comparison in the isolated worker, store a completed task with evidence-linked offers, and return the recommendation. It does not browse the live web, contact suppliers, or place orders.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Product and quantity to source, for example: 500 boxes of nitrile gloves."},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri"},
                    "maxItems": 20,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_research_tasks",
        "description": "List recent TaskVault research tasks and their status.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_research_result",
        "description": "Return a stored task result, including the offer comparison, recommendation, sandbox receipt, and errors.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_price_watch",
        "description": "Watch a stored offer against a target unit price. Checks read the stored evidence record; they do not scrape the live web.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "offer_id": {"type": "string"},
                "target_price": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["task_id", "offer_id", "target_price"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_price_watches",
        "description": "List stored price watches, targets, latest prices, and trigger state.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_approvals",
        "description": "List quote-request and purchase-order drafts awaiting or having received a human decision.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
    },
    {
        "name": "decide_approval",
        "description": "Record a human approve or reject decision. It does not send a message, place an order, or take payment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "approval_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["approved", "rejected"]},
                "note": {"type": "string", "maxLength": 500},
            },
            "required": ["approval_id", "decision"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_audit_activity",
        "description": "Read recent hash-chained TaskVault events. The chain is integrity-evident, not tamper-proof against an administrator who can rewrite the database.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
            "additionalProperties": False,
        },
    },
]


def json_rpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def json_rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def tool_result(value, is_error=False):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    if name == "create_research_task":
        if set(arguments) - {"query", "sources"}:
            raise ValueError("Unexpected create_research_task argument.")
        task_id = create_task(arguments.get("query"), arguments.get("sources"))
        return get_task(task_id)
    if name == "source_suppliers":
        if set(arguments) - {"query", "sources"}:
            raise ValueError("Unexpected source_suppliers argument.")
        query = arguments.get("query")
        product = match_product(query)
        if not product:
            raise ValueError("Name a product to source, for example nitrile gloves or 5 mL syringes.")
        quantity = extract_quantity(query, product)
        task_id = create_task(
            query,
            arguments.get("sources"),
            status="running",
            stage="Running the isolated sourcing worker",
            intent="research",
            product_key=product["key"],
            quantity=quantity["requested_units"],
        )
        try:
            result, receipt = run_worker(query, arguments.get("sources") or [])
            result["task_id"] = task_id
            save_research(task_id, result)
            update_task(
                task_id,
                "completed",
                "Comparison ready",
                result=result.get("summary"),
                research=result,
                sandbox=receipt,
                summary=result.get("summary"),
                recommendation=result.get("recommendation"),
                product_key=product["key"],
                quantity=result.get("requested_units"),
            )
            append_event(task_id, "sandbox.completed", "MCP sourcing worker completed in {} mode.".format(receipt.get("mode", "unknown")))
        except Exception as error:
            update_task(task_id, "failed", "Sourcing run failed", error=str(error))
            raise
        return task_result(task_id)
    if name == "list_research_tasks":
        if set(arguments) - {"limit"}:
            raise ValueError("Unexpected list_research_tasks argument.")
        return {"tasks": list_tasks(arguments.get("limit", 20))}
    if name == "get_research_result":
        if set(arguments) - {"task_id"}:
            raise ValueError("Unexpected get_research_result argument.")
        result = task_result(arguments.get("task_id"))
        if result is None:
            raise LookupError("Task not found.")
        return result
    if name == "create_price_watch":
        if set(arguments) - {"task_id", "offer_id", "target_price"}:
            raise ValueError("Unexpected create_price_watch argument.")
        return create_price_watch(
            arguments.get("task_id"),
            arguments.get("offer_id"),
            arguments.get("target_price"),
        )
    if name == "list_price_watches":
        if set(arguments) - {"limit"}:
            raise ValueError("Unexpected list_price_watches argument.")
        return {"watches": list_price_watches(arguments.get("limit", 50))}
    if name == "list_approvals":
        if set(arguments) - {"limit"}:
            raise ValueError("Unexpected list_approvals argument.")
        return {"approvals": list_approvals(arguments.get("limit", 50))}
    if name == "decide_approval":
        if set(arguments) - {"approval_id", "decision", "note"}:
            raise ValueError("Unexpected decide_approval argument.")
        return decide_approval(
            arguments.get("approval_id"),
            arguments.get("decision"),
            arguments.get("note"),
        )
    if name == "get_audit_activity":
        if set(arguments) - {"limit"}:
            raise ValueError("Unexpected get_audit_activity argument.")
        return {
            "events": list_activity(arguments.get("limit", 50)),
            "audit_chain_valid": verify_audit_ledger(),
        }
    raise LookupError("Unknown TaskVault tool.")


def dispatch(message):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return json_rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid JSON-RPC request.")
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return json_rpc_error(request_id, -32600, "A method is required.")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        return json_rpc_result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "taskvault", "version": "0.1.0"},
            },
        )
    if method == "ping":
        return json_rpc_result(request_id, {})
    if method == "tools/list":
        return json_rpc_result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        try:
            result = call_tool(params.get("name"), params.get("arguments", {}))
            return json_rpc_result(request_id, tool_result(result))
        except (ValueError, LookupError) as error:
            return json_rpc_result(request_id, tool_result({"error": str(error)}, is_error=True))
        except (RuntimeError, OSError) as error:
            return json_rpc_result(request_id, tool_result({"error": "The sourcing worker failed: {}".format(error)}, is_error=True))
        except sqlite3.Error:
            LOG.exception("TaskVault MCP database operation failed")
            return json_rpc_result(
                request_id,
                tool_result({"error": "The TaskVault database operation failed."}, is_error=True),
            )
    return json_rpc_error(request_id, -32601, "Method not found.")


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    load_dotenv()
    initialize_database()
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = json_rpc_error(None, -32700, "Parse error.")
        else:
            response = dispatch(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
