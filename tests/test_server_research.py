import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import server
import taskvault_core


class ResearchFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "TASKVAULT_DB_PATH": os.path.join(self.temp_dir.name, "taskvault.sqlite3"),
                "TASKVAULT_SANDBOX_MODE": "process",
                "VULTR_INFERENCE_URL": "",
                "VULTR_INFERENCE_API_KEY": "",
                "VULTR_INFERENCE_MODEL": "",
            },
        )
        self.environment.start()
        taskvault_core.initialize_database()
        self.app = ThreadingHTTPServer(("127.0.0.1", 0), server.TaskVaultHandler)
        self.thread = threading.Thread(target=self.app.serve_forever)
        self.thread.start()
        self.base = "http://127.0.0.1:{}".format(self.app.server_port)

    def tearDown(self):
        self.app.shutdown()
        self.app.server_close()
        self.thread.join(timeout=5)
        self.environment.stop()
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
            return response.status, content_type, body

    def request_json(self, method, path, payload=None):
        status, content_type, body = self.request(method, path, payload)
        self.assertEqual(content_type, "application/json")
        return status, json.loads(body.decode())

    def wait_for_task(self, task_id):
        for _ in range(200):
            _, task = self.request_json("GET", "/api/tasks/{}".format(task_id))
            if task["status"] in ("completed", "failed", "stopped"):
                return task
            time.sleep(0.05)
        self.fail("Research task did not settle.")

    def test_sourcing_watch_approval_and_profile_flow(self):
        status, accepted = self.request_json(
            "POST",
            "/api/chat",
            {
                "message": "Source 500 boxes of nitrile examination gloves.",
                "history": [{"role": "user", "content": "Source 500 boxes of nitrile examination gloves."}],
                "sources": [],
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(accepted["intent"], "research")
        task = self.wait_for_task(accepted["task_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(len(task["research"]["offers"]), 5)
        self.assertIn(task["sandbox"]["mode"], ("process", "docker"))
        self.assertIn("No message was sent", task["summary"])

        best = task["research"]["offers"][0]
        status, content_type, source_page = self.request("GET", "/sources/{}".format(best["id"]))
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(best["supplier"].encode(), source_page)
        self.assertIn(b"It is not a live page capture", source_page)

        status, created_watch = self.request_json(
            "POST",
            "/api/watches",
            {"task_id": task["task_id"], "offer_id": best["id"], "target_price": 8.00},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created_watch["watch"]["status"], "watching")
        status, checked = self.request_json(
            "POST", "/api/watches/{}/check".format(created_watch["watch"]["id"]), {}
        )
        self.assertEqual(status, 200)
        self.assertEqual(checked["watch"]["current_price"], best["unit_price"])
        self.assertEqual(checked["watch"]["status"], "watching")

        status, created_approval = self.request_json(
            "POST",
            "/api/approvals",
            {"task_id": task["task_id"], "offer_id": best["id"], "kind": "quote_request"},
        )
        self.assertEqual(status, 201)
        approval = created_approval["approval"]
        self.assertEqual(approval["status"], "pending")
        self.assertIn("500 boxes", approval["body"])
        status, decided = self.request_json(
            "POST",
            "/api/approvals/{}/decision".format(approval["id"]),
            {"decision": "approved"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(decided["approval"]["status"], "approved")
        self.assertIn("No message was sent", approval["body"] + task["summary"])

        status, saved = self.request_json(
            "POST",
            "/api/profile",
            {
                "company": "Northline Clinic",
                "buyer_name": "Alex Morgan",
                "email": "buyer@example.com",
                "ship_to": "Austin, TX",
                "approval_threshold": 2500,
                "payment_method": "invoice",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["profile"]["company"], "Northline Clinic")
        self.assertEqual(saved["profile"]["payment_method"], "invoice")

        status, activity = self.request_json("GET", "/api/activity")
        self.assertEqual(status, 200)
        self.assertTrue(activity["audit_chain_valid"])
        kinds = [event["kind"] for event in activity["events"]]
        for expected in ("research.queued", "sandbox.completed", "evidence.saved", "watch.created", "approval.decided"):
            self.assertIn(expected, kinds)

    def test_containment_endpoint_returns_a_receipt(self):
        status, payload = self.request_json("POST", "/api/sandbox/test", {"confirm": True})
        self.assertEqual(status, 200)
        if payload["receipt"]["mode"] in ("docker", "macos-seatbelt"):
            self.assertTrue(payload["result"]["pass"])
        else:
            self.assertFalse(payload["result"]["pass"])
        self.assertIn(payload["receipt"]["mode"], ("process", "docker", "macos-seatbelt"))


if __name__ == "__main__":
    unittest.main()
