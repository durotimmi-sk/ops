import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
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

    def request(self, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req_headers = {"Content-Type": "application/json"} if data else {}
        if headers:
            req_headers.update(headers)
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=req_headers,
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

    def test_missing_quantity_returns_a_structured_clarification_and_resumes(self):
        status, first = self.request_json(
            "POST",
            "/api/chat",
            {"message": "Source nitrile exam gloves.", "history": [], "sources": []},
        )
        self.assertEqual(status, 200)
        clarification = first["clarification"]
        self.assertEqual(clarification["kind"], "quantity")
        self.assertEqual(clarification["product"]["key"], "nitrile-gloves")
        self.assertIn("nitrile exam gloves", clarification["prompt"].lower())
        self.assertIn("cartons", clarification["units"])
        self.assertIn("boxes", clarification["units"])

        status, accepted = self.request_json(
            "POST",
            "/api/chat",
            {
                "message": "500 boxes",
                "history": [
                    {"role": "user", "content": "Source nitrile exam gloves."},
                    {"role": "assistant", "content": first["answer"]},
                ],
                "sources": [],
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(accepted["intent"], "research")
        task = self.wait_for_task(accepted["task_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["research"]["quantity"]["quantity_label"], "500 boxes")

    def test_buyer_sources_are_captured_and_served_as_evidence(self):
        def fake_capture(urls, artifact_dir=None, cancel_check=None):
            artifact = Path(artifact_dir)
            artifact.mkdir(parents=True, exist_ok=True)
            (artifact / "source-01.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"evidence")
            result = {
                "mode": "browser_capture",
                "requested_count": len(urls),
                "captured_count": 1,
                "error_count": 0,
                "captures": [
                    {
                        "url": urls[0],
                        "final_url": urls[0],
                        "host": "example.com",
                        "title": "Example page",
                        "http_status": 200,
                        "captured_at": "2026-11-06T12:00:00+00:00",
                        "read_only": True,
                        "screenshot_file": "source-01.png",
                        "screenshot_sha256": "a" * 64,
                        "screenshot_bytes": 16,
                        "text_excerpt": "Price USD 8.10 per box. MOQ 100. Dispatch in 4 days.",
                        "blocked_requests": 0,
                        "error": None,
                    }
                ],
                "blocked_requests": [],
                "allowed_request_count": 1,
                "screenshots_retained": 1,
                "browser": {"name": "Chromium", "version": "test", "read_only": True},
            }
            receipt = {
                "worker_id": "bw_test",
                "mode": "browser-process",
                "duration_ms": 12,
                "exit_code": 0,
                "degraded": True,
            }
            return result, receipt

        with patch.object(server, "run_browser_capture", side_effect=fake_capture):
            status, accepted = self.request_json(
                "POST",
                "/api/chat",
                {
                    "message": "Source 500 boxes of nitrile examination gloves.",
                    "history": [{"role": "user", "content": "Source 500 boxes of nitrile examination gloves."}],
                    "sources": ["https://example.com/product"],
                },
            )
            self.assertEqual(status, 202)
            task = self.wait_for_task(accepted["task_id"])

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["research"]["index"].get("version"), "live-capture-v1")
        self.assertEqual(len(task["research"]["offers"]), 1)
        capture = task["research"]["captures"][0]
        self.assertEqual(capture["title"], "Example page")
        self.assertEqual(capture["screenshot_file"], None)
        self.assertTrue(capture["screenshot_url"].startswith("/evidence/"))
        self.assertEqual(task["research"]["browser"]["screenshots_retained"], 1)
        status, content_type, body = self.request("GET", capture["screenshot_url"])
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))
        _, events = self.request_json("GET", "/api/tasks/{}/events".format(accepted["task_id"]))
        kinds = [event["kind"] for event in events["events"]]
        self.assertIn("browser.started", kinds)
        self.assertIn("browser.captured", kinds)
        self.assertIn("research.live", kinds)

        status, captures_payload = self.request_json("GET", "/api/tasks/{}/captures".format(accepted["task_id"]))
        self.assertEqual(status, 200)
        self.assertEqual(len(captures_payload["captures"]), 1)
        self.assertTrue(captures_payload["captures"][0]["screenshot_file"].endswith("source-01.png"))

        status, evidence_payload = self.request_json("GET", "/api/v1/tasks/{}/evidence".format(accepted["task_id"]))
        self.assertEqual(status, 200)
        self.assertEqual(evidence_payload["task_id"], accepted["task_id"])
        self.assertEqual(len(evidence_payload["captures"]), 1)
        self.assertEqual(len(evidence_payload["offers"]), 1)

        status, v1_task = self.request_json("GET", "/api/v1/tasks/{}".format(accepted["task_id"]))
        self.assertEqual(status, 200)
        self.assertEqual(v1_task["task"]["id"], accepted["task_id"])

        status, content_type, stream_body = self.request(
            "GET",
            "/api/tasks/{}/events?stream=true".format(accepted["task_id"]),
            headers={"Accept": "text/event-stream"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        self.assertIn(b"event: browser.captured\n", stream_body)
        self.assertIn(b"event: task.completed\n", stream_body)

    def test_task_create_api_and_dynamic_product_live_capture(self):
        def fake_capture(urls, artifact_dir=None, cancel_check=None):
            artifact = Path(artifact_dir)
            artifact.mkdir(parents=True, exist_ok=True)
            (artifact / "source-01.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"evidence")
            result = {
                "mode": "browser_capture",
                "requested_count": len(urls),
                "captured_count": 1,
                "error_count": 0,
                "captures": [
                    {
                        "url": urls[0],
                        "final_url": urls[0],
                        "host": "respirators.example",
                        "title": "KN95 Direct - Wholesale Respirators",
                        "http_status": 200,
                        "captured_at": "2026-11-06T12:00:00+00:00",
                        "read_only": True,
                        "screenshot_file": "source-01.png",
                        "screenshot_sha256": "c" * 64,
                        "screenshot_bytes": 16,
                        "text_excerpt": "KN95 masks in stock. Price USD 1.25 per unit. MOQ 200 units. Ships in 2 days.",
                        "blocked_requests": 0,
                        "error": None,
                    }
                ],
                "blocked_requests": [],
                "allowed_request_count": 1,
                "screenshots_retained": 1,
                "browser": {"name": "Chromium", "version": "test", "read_only": True},
            }
            receipt = {
                "worker_id": "bw_respirator",
                "mode": "browser-process",
                "duration_ms": 15,
                "exit_code": 0,
                "degraded": True,
            }
            return result, receipt

        with patch.object(server, "run_browser_capture", side_effect=fake_capture):
            status, created = self.request_json(
                "POST",
                "/api/v1/tasks",
                {
                    "goal": "Source 200 boxes of KN95 protective respirators",
                    "sources": ["https://respirators.example/item"],
                },
            )
            self.assertEqual(status, 201)
            self.assertIn("task_id", created)
            task = self.wait_for_task(created["task_id"])

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["research"]["product"]["name"], "Kn95 Protective Respirators")
        self.assertEqual(len(task["research"]["offers"]), 1)
        self.assertEqual(task["research"]["offers"][0]["unit_price"], 1.25)
        self.assertEqual(task["research"]["index"]["is_demo"], False)

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
