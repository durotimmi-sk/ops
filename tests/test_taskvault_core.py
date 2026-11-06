import os
import tempfile
import unittest
from unittest.mock import patch

import taskvault_core


class TaskVaultCoreTests(unittest.TestCase):
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

    def test_create_and_update_task_preserves_sources_and_audit_chain(self):
        task_id = taskvault_core.create_task(
            "Compare supplier offers for gloves.",
            ["https://supplier.example/gloves"],
            status="running",
            stage="Waiting for model response",
        )
        taskvault_core.update_task(task_id, "completed", "Response ready", result="Need more evidence.")

        task = taskvault_core.list_tasks()[0]
        self.assertEqual(task["id"], task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["sources"], ["https://supplier.example/gloves"])
        self.assertEqual(task["result"], "Need more evidence.")
        self.assertTrue(taskvault_core.verify_audit_ledger())
        self.assertEqual(
            [event["kind"] for event in reversed(taskvault_core.list_activity())],
            ["task.created", "task.completed"],
        )

    def test_existing_task_schema_is_reused_without_replacement(self):
        with taskvault_core.connect() as connection:
            connection.execute(
                "INSERT INTO tasks (id, query, source_urls, status, stage, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("existing", "Earlier request", "[]", "queued", "Queued", "2026-01-01", "2026-01-01"),
            )
        taskvault_core.initialize_database()
        self.assertEqual(taskvault_core.list_tasks()[0]["id"], "existing")

    def test_rejects_non_public_or_credential_bearing_urls(self):
        for value in (
            "file:///etc/passwd",
            "https://user:secret@example.com/",
            "http://127.0.0.1/admin",
            "http://192.168.1.1/",
            "https://service.local/",
            "https://example.com/a b",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                taskvault_core.validate_public_url(value)

    def test_rejects_too_many_sources_and_invalid_prompts(self):
        with self.assertRaises(ValueError):
            taskvault_core.validate_sources(["https://example.com"] * 21)
        with self.assertRaises(ValueError):
            taskvault_core.validate_prompt("  ")

    def test_audit_chain_detects_record_changes(self):
        taskvault_core.create_task("Find glove suppliers.")
        with taskvault_core.connect() as connection:
            connection.execute("UPDATE audit_ledger SET message = 'changed' WHERE id = 1")
        self.assertFalse(taskvault_core.verify_audit_ledger())


if __name__ == "__main__":
    unittest.main()