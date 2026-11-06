import json
import os
import tempfile
import unittest
from unittest.mock import patch

import mcp_server
import taskvault_core


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {"TASKVAULT_DB_PATH": os.path.join(self.temp_dir.name, "taskvault.sqlite3")},
        )
        self.environment.start()
        taskvault_core.initialize_database()

    def tearDown(self):
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_mcp_lists_and_creates_tasks_in_shared_store(self):
        initialized = mcp_server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": mcp_server.PROTOCOL_VERSION},
            }
        )
        listed = mcp_server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        created = mcp_server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "create_research_task",
                    "arguments": {
                        "query": "Find glove suppliers.",
                        "sources": ["https://supplier.example/gloves"],
                    },
                },
            }
        )

        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "taskvault")
        self.assertEqual(len(names), 9)
        self.assertTrue(
            {
                "create_research_task",
                "source_suppliers",
                "get_research_result",
                "create_price_watch",
                "list_approvals",
                "get_audit_activity",
            }.issubset(names)
        )
        self.assertFalse(created["result"]["isError"])
        self.assertEqual(
            json.loads(created["result"]["content"][0]["text"])["sources"],
            ["https://supplier.example/gloves"],
        )
        self.assertEqual(len(taskvault_core.list_tasks()), 1)

    def test_mcp_sources_suppliers_and_returns_evidence(self):
        sourced = mcp_server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "source_suppliers",
                    "arguments": {"query": "Source 500 boxes of nitrile gloves."},
                },
            }
        )
        result = json.loads(sourced["result"]["content"][0]["text"])
        self.assertFalse(sourced["result"]["isError"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["research"]["offers"]), 5)
        self.assertTrue(result["research"]["offers"][0]["source_url"].startswith("/sources/"))
        self.assertIn(result["sandbox"]["mode"], ("process", "docker", "macos-seatbelt"))
        fetched = mcp_server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "get_research_result",
                    "arguments": {"task_id": result["task_id"]},
                },
            }
        )
        self.assertFalse(fetched["result"]["isError"])

    def test_notifications_do_not_write_a_response(self):
        self.assertIsNone(
            mcp_server.dispatch(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )


if __name__ == "__main__":
    unittest.main()
