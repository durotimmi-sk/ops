"""Read-only browser evidence worker.

This process receives a bounded JSON request on stdin, opens explicitly
allowlisted HTTPS pages through a loopback policy proxy, and writes screenshots
plus metadata into the task-scoped artifacts directory. It never clicks, types,
submits forms, downloads files, or executes model-generated scripts.
"""

import hashlib
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from taskvault_egress import ALLOWED_PORT, EgressBlocked, host_allowed, normalize_allowlist, normalize_host


MAX_INPUT_BYTES = 64 * 1024
MAX_PAGES = 3
MAX_TEXT_CHARS = 6000
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
NAVIGATION_TIMEOUT_MS = 15000
SETTLE_MS = 1200
SAFE_FILENAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_capture_url(value, allowlist):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise EgressBlocked("Each capture source must be a public HTTPS URL.")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise EgressBlocked("Capture source URLs cannot contain whitespace or control characters.")
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise EgressBlocked("A capture source URL is malformed.") from error
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise EgressBlocked("Only public HTTPS URLs without embedded credentials can be captured.")
    if port is not None and port != ALLOWED_PORT:
        raise EgressBlocked("Only HTTPS port 443 can be captured.")
    host = normalize_host(hostname)
    if not host_allowed(host, allowlist):
        raise EgressBlocked("The source host is not on this task's allowlist.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


class RequestPolicy:
    def __init__(self, allowlist):
        self.allowlist = allowlist
        self.blocked = []
        self.allowed_count = 0

    def check(self, url):
        try:
            parsed = urllib.parse.urlsplit(url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return False, "malformed"
        if parsed.scheme != "https":
            return False, "non-https scheme"
        if port is not None and port != ALLOWED_PORT:
            return False, "non-443 port"
        if not hostname:
            return False, "missing host"
        if not host_allowed(hostname, self.allowlist):
            return False, "host not allowlisted"
        return True, ""

    def handle(self, route):
        allowed, reason = self.check(route.request.url)
        if allowed:
            self.allowed_count += 1
            route.continue_()
            return
        if len(self.blocked) < 50:
            host = ""
            try:
                host = urllib.parse.urlsplit(route.request.url).hostname or ""
            except ValueError:
                pass
            self.blocked.append({"host": host, "reason": reason})
        route.abort()


def _safe_artifact_dir(value, cwd):
    candidate = Path(value or "artifacts")
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("The artifacts directory must be relative.")
    root = (cwd / candidate).resolve()
    if cwd.resolve() not in root.parents and root != cwd.resolve():
        raise ValueError("The artifacts directory escapes the task workspace.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _browser_launch_options():
    options = {
        "headless": True,
        "args": [
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-domain-reliability",
            "--disable-extensions",
            "--disable-features=MediaRouter,OptimizationHints,Translate",
            "--disable-quic",
            "--disable-sync",
            "--dns-prefetch-disable",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-default-browser-check",
            "--no-first-run",
            "--no-pings",
            "--disable-breakpad",
        ],
    }
    executable = os.environ.get("TASKVAULT_BROWSER_EXECUTABLE", "").strip()
    channel = os.environ.get("TASKVAULT_BROWSER_CHANNEL", "").strip()
    if executable:
        options["executable_path"] = executable
    elif channel:
        options["channel"] = channel
    elif sys.platform == "darwin":
        options["channel"] = "chrome"
    return options


def _clean_text(page):
    try:
        text = page.evaluate(
            "() => (document.body && document.body.innerText) || "
            "(document.documentElement && document.documentElement.innerText) || ''"
        )
    except Exception:
        text = ""
    text = re.sub(r"[ \t]+", " ", str(text or ""))
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:MAX_TEXT_CHARS]


def capture_page(page, url, policy, artifact_root, index):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    captured_at = utc_now()
    record = {
        "url": url,
        "final_url": url,
        "host": urllib.parse.urlsplit(url).hostname or "",
        "title": "",
        "http_status": None,
        "captured_at": captured_at,
        "read_only": True,
        "screenshot_file": None,
        "screenshot_sha256": None,
        "screenshot_bytes": 0,
        "text_sha256": None,
        "text_excerpt": "",
        "blocked_requests": 0,
        "error": None,
    }
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        final_url = page.url
        allowed, reason = policy.check(final_url)
        if not allowed:
            raise EgressBlocked("The page ended on a blocked destination: {}.".format(reason))
        record["final_url"] = final_url
        record["host"] = urllib.parse.urlsplit(final_url).hostname or record["host"]
        record["http_status"] = response.status if response else None
        record["title"] = page.title()[:300]
        text = _clean_text(page)
        record["text_excerpt"] = text
        record["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        screenshot = page.screenshot(
            full_page=False,
            type="png",
            animations="disabled",
            caret="hide",
            timeout=8000,
        )
        if len(screenshot) > MAX_SCREENSHOT_BYTES:
            raise ValueError("The screenshot exceeded the evidence size limit.")
        filename = "source-{:02d}.png".format(index)
        path = artifact_root / filename
        path.write_bytes(screenshot)
        record["screenshot_file"] = filename
        record["screenshot_sha256"] = hashlib.sha256(screenshot).hexdigest()
        record["screenshot_bytes"] = len(screenshot)
    except (PlaywrightTimeoutError, PlaywrightError, EgressBlocked, ValueError, OSError) as error:
        message = str(error).strip()
        if "Timeout" in error.__class__.__name__ or "Timeout" in message:
            message = "The page did not finish loading inside the capture window."
        record["error"] = message[:300] or "The page could not be captured."
    record["blocked_requests"] = len(policy.blocked)
    return record


def capture_sources(request):
    from playwright.sync_api import sync_playwright

    urls = request.get("urls") or []
    if not isinstance(urls, list) or not urls:
        raise ValueError("At least one source URL is required for live capture.")
    if len(urls) > MAX_PAGES:
        urls = urls[:MAX_PAGES]
    allowlist = normalize_allowlist(request.get("allowlist") or [
        urllib.parse.urlsplit(url).hostname or "" for url in urls if isinstance(url, str)
    ])
    validated = []
    for url in urls:
        try:
            validated.append(validate_capture_url(url, allowlist))
        except EgressBlocked as error:
            validated.append({"url": url if isinstance(url, str) else "", "error": str(error)})
    artifact_root = _safe_artifact_dir(request.get("artifacts_dir"), Path.cwd())
    proxy_url = str(request.get("proxy") or "").strip()
    if not proxy_url.startswith("http://127.0.0.1:"):
        raise ValueError("The browser worker requires a loopback policy proxy.")

    captures = []
    blocked = []
    allowed_requests = 0
    browser_version = ""
    with sync_playwright() as playwright:
        options = _browser_launch_options()
        options["args"] = list(options["args"]) + [
            "--proxy-server={}".format(proxy_url),
            "--proxy-bypass-list=<-loopback>",
        ]
        browser = playwright.chromium.launch(**options)
        browser_version = browser.version
        try:
            for index, candidate in enumerate(validated, start=1):
                if isinstance(candidate, dict):
                    captures.append(candidate)
                    continue
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    screen={"width": 1280, "height": 800},
                    service_workers="block",
                    accept_downloads=False,
                    ignore_https_errors=False,
                    locale="en-US",
                    timezone_id="UTC",
                    color_scheme="light",
                    user_agent="OpsPilotEvidence/0.1 (read-only browser capture)",
                )
                context.set_default_timeout(10000)
                policy = RequestPolicy(allowlist)
                context.route("**/*", policy.handle)
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.on("download", lambda download: download.cancel())
                try:
                    record = capture_page(page, candidate, policy, artifact_root, index)
                finally:
                    blocked.extend(policy.blocked)
                    allowed_requests += policy.allowed_count
                    context.close()
                captures.append(record)
        finally:
            browser.close()

    return {
        "mode": "browser_capture",
        "requested_count": len(urls),
        "captured_count": sum(1 for item in captures if item.get("screenshot_file")),
        "error_count": sum(1 for item in captures if item.get("error")),
        "captures": captures,
        "blocked_requests": blocked[:50],
        "allowed_request_count": allowed_requests,
        "browser": {
            "name": "Chromium",
            "version": browser_version,
            "headless": True,
            "read_only": True,
            "actions": ["navigate", "read text", "screenshot"],
        },
    }


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise SystemExit(json.dumps({"error": "Request exceeds browser worker input limit."}))
    try:
        request = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SystemExit(json.dumps({"error": "Request must be valid JSON."}))
    if not isinstance(request, dict) or request.get("mode") != "browser_capture":
        raise SystemExit(json.dumps({"error": "Browser worker mode is required."}))
    try:
        result = capture_sources(request)
    except (ValueError, EgressBlocked, OSError) as error:
        raise SystemExit(json.dumps({"error": str(error)})) from error
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
