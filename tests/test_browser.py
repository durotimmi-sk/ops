import socket
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_worker import RequestPolicy, validate_capture_url
from taskvault_egress import EgressBlocked, EgressProxy, host_allowed, normalize_allowlist, resolve_public


class EgressPolicyTests(unittest.TestCase):
    def test_host_allowlist_is_exact_plus_www_variant(self):
        allowlist = normalize_allowlist(["example.com"])
        self.assertTrue(host_allowed("example.com", allowlist))
        self.assertTrue(host_allowed("www.example.com", allowlist))
        self.assertFalse(host_allowed("cdn.example.com", allowlist))
        self.assertFalse(host_allowed("example.com.evil.test", allowlist))

    def test_private_and_reserved_addresses_are_blocked(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "192.0.2.10", "::1"):
            with self.assertRaises(EgressBlocked):
                resolve_public(address)
        self.assertTrue(resolve_public("8.8.8.8"))

    def test_proxy_rejects_non_allowlisted_tunnel_before_connecting(self):
        with EgressProxy(["example.com"]) as proxy:
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as client:
                client.sendall(b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n")
                response = client.recv(1024)
            self.assertIn(b"403 Forbidden", response)
        self.assertTrue(proxy.blocked)
        self.assertIn("allowlist", proxy.blocked[0]["reason"].lower())

    def test_proxy_requires_https_port_443(self):
        with EgressProxy(["example.com"]) as proxy:
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as client:
                client.sendall(b"CONNECT example.com:80 HTTP/1.1\r\nHost: example.com\r\n\r\n")
                response = client.recv(1024)
            self.assertIn(b"403 Forbidden", response)


class BrowserValidationTests(unittest.TestCase):
    def test_capture_requires_allowlisted_https(self):
        allowlist = normalize_allowlist(["example.com"])
        self.assertEqual(validate_capture_url("https://example.com/path", allowlist), "https://example.com/path")
        for url in ("http://example.com/", "https://cdn.example.com/", "https://user:pass@example.com/"):
            with self.assertRaises(EgressBlocked):
                validate_capture_url(url, allowlist)

    def test_request_policy_blocks_off_allowlist_subresources(self):
        policy = RequestPolicy(normalize_allowlist(["example.com"]))
        allowed, _ = policy.check("https://example.com/asset.js")
        blocked, reason = policy.check("https://www.google.com/analytics.js")
        self.assertTrue(allowed)
        self.assertFalse(blocked)
        self.assertIn("allowlist", reason)


class BrowserCaptureLiveTests(unittest.TestCase):
    @unittest.skipUnless(
        __import__("os").environ.get("TASKVAULT_TEST_LIVE_BROWSER") == "1"
        and Path("/Applications/Google Chrome.app").exists(),
        "Set TASKVAULT_TEST_LIVE_BROWSER=1 with Chrome installed to run live capture.",
    )
    def test_example_page_capture_writes_screenshot_and_metadata(self):
        from taskvault_sandbox import run_browser_capture
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result, receipt = run_browser_capture(["https://example.com/"], artifact_dir=directory)
            self.assertEqual(receipt["exit_code"], 0)
            self.assertEqual(result["captured_count"], 1)
            capture = result["captures"][0]
            self.assertEqual(capture["title"], "Example Domain")
            self.assertEqual(capture["http_status"], 200)
            self.assertTrue(capture["screenshot_sha256"])
            self.assertTrue((Path(directory) / "source-01.png").exists())
            self.assertEqual(result["browser"]["read_only"], True)


if __name__ == "__main__":
    unittest.main()
