import os
import unittest
from unittest.mock import patch

from taskvault_sandbox import containment_test, run_worker, sandbox_mode


class SandboxTests(unittest.TestCase):
    def test_worker_returns_research_without_inheriting_secrets(self):
        environment = {
            "TASKVAULT_DB_PATH": "/tmp/private.sqlite3",
            "VULTR_INFERENCE_API_KEY": "do-not-inherit",
            "SOME_SECRET": "do-not-inherit",
        }
        with patch.dict(os.environ, environment):
            result, receipt = run_worker("Source 500 boxes of nitrile gloves.")
        self.assertEqual(len(result["offers"]), 5)
        self.assertIn(receipt["mode"], ("process", "docker", "macos-seatbelt", "bubblewrap"))
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIn("No inference keys", receipt["secrets_policy"])
        if receipt["mode"] == "process":
            self.assertEqual(receipt["network"], "unrestricted host network")
        if receipt["mode"] == "macos-seatbelt":
            self.assertEqual(receipt["network"], "denied by macOS Seatbelt")
        if receipt["mode"] == "bubblewrap":
            self.assertIn("isolated Linux network namespace", receipt["network"])

    def test_containment_test_reports_no_inherited_credentials(self):
        with patch.dict(os.environ, {"VULTR_INFERENCE_API_KEY": "do-not-inherit", "SOME_TOKEN": "nope"}):
            result, receipt = containment_test()
        if receipt["mode"] in ("docker", "macos-seatbelt", "bubblewrap"):
            self.assertTrue(result["pass"])
        else:
            self.assertFalse(result["pass"])
        self.assertFalse(result["has_database_path"])
        self.assertFalse(result["has_inference_key"])
        self.assertEqual(result["secrets_visible"], [])
        self.assertIn(receipt["mode"], ("process", "docker", "macos-seatbelt", "bubblewrap"))

    def test_sandbox_mode_can_be_pinned_locally(self):
        with patch.dict(os.environ, {"TASKVAULT_SANDBOX_MODE": "process"}):
            self.assertEqual(sandbox_mode(), "process")


if __name__ == "__main__":
    unittest.main()
