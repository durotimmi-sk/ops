import html
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from taskvault_catalog import get_offer as catalog_offer, index_meta
from taskvault_core import (
    append_event,
    create_approval,
    create_conversation,
    create_price_watch,
    create_task,
    decide_approval,
    get_offer as stored_offer,
    get_profile,
    get_conversation,
    get_task,
    initialize_database,
    latest_research_task,
    list_activity,
    list_approvals,
    list_price_watches,
    list_task_events,
    list_tasks,
    load_dotenv,
    request_stop,
    save_profile,
    save_conversation_message,
    save_research,
    stop_requested,
    task_result,
    update_task,
    validate_prompt,
    validate_sources,
    verify_audit_ledger,
    check_price_watch,
)
from taskvault_inference import (
    InferenceError,
    inference_policy_status,
    inference_configured,
    inference_endpoint,
    infer,
    narrative_for_research,
    request_inference,
)
from taskvault_research import (
    answer_from_result,
    extract_quantity,
    has_explicit_quantity,
    is_research_request,
    match_product,
    plural_unit,
    purchase_order_draft,
    quote_draft,
)
from taskvault_sandbox import containment_test, run_worker, sandbox_mode


ROOT = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 64 * 1024
MAX_HISTORY_MESSAGES = 12
LOG = logging.getLogger("taskvault.server")
SESSION_TTL_SECONDS = 12 * 60 * 60
_SESSIONS = {}
_SESSION_LOCK = threading.Lock()
_LOGIN_FAILURES = []
_LOGIN_LOCK = threading.Lock()

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def validated_history(value, current_message):
    if not isinstance(value, list):
        raise ValueError("Conversation history must be a list.")
    if len(value) > MAX_HISTORY_MESSAGES:
        raise ValueError("Conversation history is too long.")
    history = []
    for item in value:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            raise ValueError("Conversation history contains an invalid message.")
        content = item.get("content")
        if not isinstance(content, str) or len(content) > 4000:
            raise ValueError("Conversation history contains an invalid message.")
        history.append({"role": item["role"], "content": content})
    if not history or history[-1] != {"role": "user", "content": current_message}:
        history.append({"role": "user", "content": current_message})
    return history[-MAX_HISTORY_MESSAGES:]


def start_research_task(task_id, message, sources, conversation_id=None):
    def run():
        try:
            update_task(task_id, "running", "Preparing sourcing worker")
            append_event(task_id, "sandbox.started", "Sourcing worker started; runtime details are recorded in its receipt.")
            if stop_requested(task_id):
                update_task(task_id, "stopped", "Stopped before execution")
                if conversation_id:
                    save_conversation_message(conversation_id, "assistant", "text", {"text": "The sourcing run was stopped before it started."}, task_id=task_id)
                return
            payload, receipt = run_worker(message, sources, cancel_check=lambda: stop_requested(task_id))
            if stop_requested(task_id):
                update_task(task_id, "stopped", "Stopped after sourcing run", research=payload, sandbox=receipt)
                append_event(task_id, "sandbox.stopped", "Stopped before evidence was saved.")
                if conversation_id:
                    save_conversation_message(conversation_id, "assistant", "text", {"text": "The sourcing run was stopped before its evidence was saved."}, task_id=task_id)
                return
            payload["task_id"] = task_id
            narrative = narrative_for_research(payload)
            if narrative:
                payload["narrative"] = narrative
            save_research(task_id, payload)
            update_task(
                task_id,
                "completed",
                "Comparison ready",
                result=payload.get("summary"),
                research=payload,
                sandbox=receipt,
                summary=payload.get("summary"),
                recommendation=payload.get("recommendation"),
                product_key=payload.get("product", {}).get("key"),
                quantity=payload.get("requested_units"),
            )
            if conversation_id:
                save_conversation_message(
                    conversation_id,
                    "assistant",
                    "research",
                    {"research": payload, "sandbox": receipt},
                    task_id=task_id,
                )
            append_event(
                task_id,
                "sandbox.completed",
                "Sourcing worker completed in {} mode; {} offers retained.".format(
                    receipt.get("mode", "unknown"), len(payload.get("offers", []))
                ),
            )
            append_event(
                task_id,
                "evidence.saved",
                "{} supplier offer records saved with local evidence links; external pages were not captured.".format(
                    payload.get("evidence_count", 0)
                ),
            )
        except InterruptedError as error:
            LOG.info("Research task %s stopped during worker execution", task_id)
            update_task(task_id, "stopped", "Worker stopped", error=str(error))
            append_event(task_id, "sandbox.stopped", "Worker process terminated; temporary task files were removed.")
            if conversation_id:
                save_conversation_message(conversation_id, "assistant", "text", {"text": "The sourcing run was stopped. Its worker was terminated and temporary files were removed."}, task_id=task_id)
        except TimeoutError as error:
            LOG.warning("Research task %s timed out", task_id)
            update_task(task_id, "failed", "Sourcing worker timed out", error=str(error))
            if conversation_id:
                save_conversation_message(conversation_id, "assistant", "error", {"text": "The sourcing worker timed out. You can retry this request."}, task_id=task_id)
        except (RuntimeError, ValueError, OSError) as error:
            LOG.warning("Research task %s failed: %s", task_id, error)
            update_task(task_id, "failed", "Sourcing run failed", error=str(error))
            if conversation_id:
                save_conversation_message(conversation_id, "assistant", "error", {"text": "The sourcing worker could not complete this request."}, task_id=task_id)
        except Exception as error:  # noqa: BLE001 - background task must not crash the server
            LOG.exception("Unexpected research failure for %s", task_id)
            update_task(
                task_id,
                "failed",
                "Sourcing run failed",
                error="The sourcing run failed unexpectedly.",
            )
            if conversation_id:
                save_conversation_message(conversation_id, "assistant", "error", {"text": "An unexpected sourcing error occurred. You can retry this request."}, task_id=task_id)

    thread = threading.Thread(target=run, name="taskvault-research-{}".format(task_id[:8]), daemon=True)
    thread.start()
    return thread


class TaskVaultHandler(BaseHTTPRequestHandler):
    server_version = "TaskVault/0.2"

    def log_message(self, format_string, *args):
        LOG.info("%s - %s", self.address_string(), format_string % args)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        allowed = {
            item.strip().rstrip("/")
            for item in os.environ.get("TASKVAULT_CORS_ORIGINS", "").split(",")
            if item.strip()
        }
        host = self.headers.get("Host", "")
        return origin.rstrip("/") in allowed or origin in ("http://" + host, "https://" + host)

    def _cors_headers(self):
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _auth_enabled():
        return os.environ.get("TASKVAULT_AUTH_REQUIRED", "0").lower() in ("1", "true", "yes")

    def _session_token(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return cookies.get("opspilot_session").value if cookies.get("opspilot_session") else ""
        except Exception:
            return ""

    def _is_authenticated(self):
        if not self._auth_enabled():
            return True
        token = self._session_token()
        if not token:
            return False
        now = time.time()
        with _SESSION_LOCK:
            expires = _SESSIONS.get(token, 0)
            if expires <= now:
                _SESSIONS.pop(token, None)
                return False
            return True

    def _set_session_cookie(self, token, clear=False):
        secure = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
        value = "opspilot_session=" + ("" if clear else token) + "; Path=/; HttpOnly; SameSite=Strict"
        value += "; Max-Age=0" if clear else "; Max-Age={}".format(SESSION_TTL_SECONDS)
        if secure:
            value += "; Secure"
        self.send_header("Set-Cookie", value)

    @staticmethod
    def _verify_password(password):
        encoded = os.environ.get("TASKVAULT_AUTH_PASSWORD_HASH", "")
        try:
            scheme, rounds, salt, expected = encoded.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            calculated = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds)).hex()
            return hmac.compare_digest(calculated, expected)
        except (ValueError, TypeError):
            return False

    def _login(self):
        if not self._auth_enabled():
            return self._send_error(404, "Sign-in is not enabled for this instance.", "not_found")
        now = time.time()
        with _LOGIN_LOCK:
            _LOGIN_FAILURES[:] = [stamp for stamp in _LOGIN_FAILURES if stamp > now - 900]
            if len(_LOGIN_FAILURES) >= 5:
                return self._send_error(429, "Too many sign-in attempts. Try again in 15 minutes.", "login_rate_limited")
        try:
            payload = self._read_json()
        except ValueError:
            return self._send_error(400, "Enter your username and password.", "invalid_request")
        username = payload.get("username", "")
        password = payload.get("password", "")
        password_valid = self._verify_password(password) if isinstance(password, str) and len(password) <= 1024 else False
        valid = (
            set(payload) == {"username", "password"}
            and isinstance(username, str) and len(username) <= 80
            and isinstance(password, str) and len(password) <= 1024
            and hmac.compare_digest(username, "operator")
            and password_valid
        )
        if not valid:
            with _LOGIN_LOCK:
                _LOGIN_FAILURES.append(now)
            time.sleep(0.3)
            return self._send_error(401, "That username or password did not match.", "invalid_credentials")
        with _LOGIN_LOCK:
            _LOGIN_FAILURES.clear()
        token = secrets.token_urlsafe(32)
        with _SESSION_LOCK:
            _SESSIONS[token] = now + SESSION_TTL_SECONDS
        body = json.dumps({"authenticated": True, "username": "operator"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self._set_session_cookie(token)
        self.end_headers()
        self.wfile.write(body)

    def _logout(self):
        token = self._session_token()
        with _SESSION_LOCK:
            _SESSIONS.pop(token, None)
        body = b'{"authenticated":false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self._set_session_cookie("", clear=True)
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self):
        if self._is_authenticated():
            return True
        self._send_error(401, "Sign in to access this workspace.", "authentication_required")
        return False

    def _send_error(self, status, message, code):
        self._send_json(status, {"error": message, "code": code})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request length.") from error
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body must be between 1 byte and 64 KB.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _send_file(self, relative_path, cache="no-cache"):
        file_path = (ROOT / relative_path).resolve()
        if ROOT not in file_path.parents and file_path != ROOT:
            return self._send_error(404, "Not found.", "not_found")
        try:
            body = file_path.read_bytes()
        except OSError:
            LOG.exception("Could not read static asset %s", relative_path)
            return self._send_error(404, "Not found.", "not_found")
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _source_page(self, offer_id):
        product, offer = catalog_offer(offer_id)
        if not offer:
            return self._send_error(404, "That evidence record does not exist.", "not_found")
        is_demo = bool(index_meta().get("is_demo"))
        verified = (
            "Illustrative sample flag: verified" if is_demo and offer.get("verified")
            else "Illustrative sample flag: listing only" if is_demo
            else "Verified supplier documentation" if offer.get("verified")
            else "Listing only — documentation not verified"
        )
        rows = [
            ("Supplier", offer.get("supplier", "")),
            ("Location", offer.get("location", "")),
            ("Product", product.get("name", "")),
            ("Unit price", "${:,.2f} per {}".format(float(offer.get("unit_price", 0)), product.get("unit", "unit"))),
            ("Previous price", "${:,.2f}".format(float(offer["previous_price"])) if offer.get("previous_price") else "No prior observation"),
            ("Minimum order", "{} {}".format(
                offer.get("moq_boxes", 0),
                plural_unit(product.get("unit", "unit"), offer.get("moq_boxes", 0)),
            )),
            ("Lead time", "{} days".format(offer.get("lead_time_days", 0))),
            ("Sample rating" if is_demo else "Rating", "{} / 5 from {} {}".format(offer.get("rating", 0), offer.get("reviews", 0), "sample reviews" if is_demo else "reviews")),
            ("Shipping", "Included above ${:,.2f}".format(float(offer.get("free_shipping_threshold", 0))) if offer.get("free_shipping_threshold") else "${:,.2f} flat".format(float(offer.get("shipping_flat", 0)))),
            ("Illustrative certification claims" if is_demo else "Certifications", ", ".join(offer.get("certifications", [])) or "None listed"),
            ("Evidence status", verified),
            ("Captured", offer.get("updated_at", "")),
        ]
        body = "".join(
            "<tr><th>{}</th><td>{}</td></tr>".format(html.escape(label), html.escape(str(value)))
            for label, value in rows
        )
        page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title} — TaskVault evidence</title>
<style>
body {{ margin:0; background:#f9f9f9; color:#0d0d0d; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:720px; margin:48px auto; padding:0 24px; }}
.card {{ background:#fff; border:1px solid rgba(0,0,0,.1); border-radius:12px; padding:28px; }}
.kicker {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#6e6e6e; margin:0 0 6px; }}
h1 {{ font-size:24px; line-height:1.2; margin:0 0 4px; }}
p.lede {{ color:#6e6e6e; margin:0 0 24px; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ text-align:left; padding:11px 0; border-top:1px solid rgba(0,0,0,.08); vertical-align:top; }}
th {{ width:38%; font-weight:500; color:#6e6e6e; }}
.note {{ margin-top:22px; padding:14px 16px; background:#f4f4f4; border-radius:10px; color:#4a4a4a; font-size:13px; }}
</style>
</head>
<body>
<main>
<section class="card">
<p class="kicker">TaskVault evidence record</p>
<h1>{title}</h1>
<p class="lede">A bounded record from the bundled supplier index. It is not a live page capture.</p>
<table>{body}</table>
<p class="note">{sample_note}This evidence page exists so a human can inspect the exact fields used in a comparison. Prices and availability must be re-confirmed with the supplier before ordering.</p>
</section>
</main>
</body>
</html>""".format(
            title=html.escape(offer.get("supplier", "Supplier")),
            body=body,
            sample_note=(
                "Demonstration record only: supplier names, prices, ratings, certifications, and status fields are illustrative. Do not use them to make a purchase. "
                if is_demo else ""
            ),
        )
        encoded = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if not self._origin_allowed():
            return self._send_error(403, "This frontend origin is not allowed.", "origin_not_allowed")
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path
        if route == "/api/auth/session":
            return self._send_json(200, {"auth_enabled": self._auth_enabled(), "authenticated": self._is_authenticated(), "username": "operator" if self._is_authenticated() and self._auth_enabled() else None})
        if route == "/api/health":
            try:
                meta = index_meta()
            except (OSError, ValueError):
                meta = {}
            return self._send_json(
                200,
                {
                    "ok": True,
                    "auth_enabled": self._auth_enabled(),
                    "inference_configured": inference_configured(),
                    "inference_policy": inference_policy_status(),
                    "sourcing_worker_configured": True,
                    "sandbox_mode": sandbox_mode(),
                    "catalog": meta,
                },
            )
        if route.startswith("/api/") and not self._require_auth():
            return
        if route.startswith("/sources/") and not self._require_auth():
            return
        if route == "/api/tasks":
            return self._send_json(200, {"tasks": list_tasks()})
        if route == "/api/activity":
            return self._send_json(
                200,
                {"events": list_activity(), "audit_chain_valid": verify_audit_ledger()},
            )
        if route == "/api/watches":
            return self._send_json(200, {"watches": list_price_watches()})
        if route == "/api/approvals":
            return self._send_json(200, {"approvals": list_approvals()})
        if route == "/api/profile":
            return self._send_json(200, {"profile": get_profile()})
        match = re.fullmatch(r"/api/conversations/([0-9a-f-]{36})", route)
        if match:
            conversation = get_conversation(match.group(1))
            if not conversation:
                return self._send_error(404, "Conversation not found.", "not_found")
            return self._send_json(200, {"conversation": conversation})
        match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)", route)
        if match:
            task = get_task(match.group(1))
            if not task:
                return self._send_error(404, "Task not found.", "not_found")
            return self._send_json(200, task_result(task["id"]) | {"task": task})
        match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)/result", route)
        if match:
            result = task_result(match.group(1))
            if not result:
                return self._send_error(404, "Task not found.", "not_found")
            return self._send_json(200, result)
        match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)/events", route)
        if match:
            if not get_task(match.group(1)):
                return self._send_error(404, "Task not found.", "not_found")
            return self._send_json(200, {"events": list_task_events(match.group(1))})
        match = re.fullmatch(r"/sources/([A-Za-z0-9_-]+)", route)
        if match:
            return self._source_page(match.group(1))
        if route in ("/", "/index.html"):
            return self._send_file("index.html")
        if route in ("/app.js", "/styles.css", "/config.js"):
            return self._send_file(route.lstrip("/"))
        if route.startswith("/assets/") and ".." not in route:
            return self._send_file(route.lstrip("/"), cache="public, max-age=3600")
        return self._send_error(404, "Not found.", "not_found")

    def do_POST(self):
        if not self._origin_allowed():
            return self._send_error(403, "This frontend origin is not allowed.", "origin_not_allowed")
        route = urllib.parse.urlsplit(self.path).path
        if route == "/api/auth/login":
            return self._login()
        if route == "/api/auth/logout":
            return self._logout()
        if route.startswith("/api/") and not self._require_auth():
            return
        try:
            if route == "/api/chat":
                return self._chat()
            if route == "/api/voice/ask":
                return self._voice_ask()
            if route == "/api/watches":
                return self._create_watch()
            if route == "/api/approvals":
                return self._create_approval()
            if route == "/api/profile":
                return self._save_profile()
            if route == "/api/sandbox/test":
                return self._sandbox_test()
            if route == "/api/inference/check":
                payload = self._read_json()
                if payload:
                    raise ValueError("Inference check does not accept request fields.")
                started = time.perf_counter()
                infer(
                    [{"role": "user", "content": "Reply with OK."}],
                    system_message="Reply with exactly OK.",
                    temperature=0,
                    max_tokens=4,
                    timeout=15,
                )
                return self._send_json(
                    200,
                    {"verified": True, "latency_ms": round((time.perf_counter() - started) * 1000)},
                )
            match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)/stop", route)
            if match:
                payload = self._read_json()
                if set(payload) - {"reason"}:
                    raise ValueError("Unexpected stop request field.")
                request_stop(match.group(1))
                append_event(match.group(1), "task.stop_requested", "Stop requested by the buyer.")
                return self._send_json(200, {"stopped": True, "task_id": match.group(1)})
            match = re.fullmatch(r"/api/watches/([0-9a-f-]+)/check", route)
            if match:
                self._read_json()
                return self._send_json(200, {"watch": check_price_watch(match.group(1))})
            match = re.fullmatch(r"/api/approvals/([0-9a-f-]+)/decision", route)
            if match:
                return self._decide_approval(match.group(1))
        except ValueError as error:
            return self._send_error(400, str(error), "invalid_request")
        except LookupError as error:
            return self._send_error(404, str(error), "not_found")
        except InferenceError as error:
            return self._send_json(error.status, {"error": str(error), "code": error.code})
        return self._send_error(404, "Not found.", "not_found")

    def do_OPTIONS(self):
        if not self._origin_allowed():
            return self._send_error(403, "This frontend origin is not allowed.", "origin_not_allowed")
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self._cors_headers()
        self.end_headers()

    def _chat(self):
        payload = self._read_json()
        message = validate_prompt(payload.get("message"))
        sources = validate_sources(payload.get("sources"))
        history = validated_history(payload.get("history", []), message)
        conversation_id = create_conversation(payload.get("conversation_id"))
        research_query = message
        product = match_product(research_query)
        if not product and has_explicit_quantity(message):
            for prior in reversed(history[:-1]):
                if prior.get("role") == "user" and is_research_request(prior.get("content", "")):
                    product = match_product(prior["content"])
                    if product:
                        research_query = "{} {}".format(prior["content"], message)
                        break
        if is_research_request(research_query):
            product = match_product(research_query)
            if not has_explicit_quantity(research_query):
                prompt = "How many {} do you need? Include the order unit, such as 500 boxes or 2 cartons, and I’ll compare offers for that exact quantity.".format(
                    product.get("short_name", product["name"]).lower()
                )
                save_conversation_message(conversation_id, "user", "text", {"text": message, "sources": sources})
                save_conversation_message(conversation_id, "assistant", "text", {"text": prompt})
                return self._send_json(200, {"answer": prompt, "conversation_id": conversation_id})
            quantity = extract_quantity(research_query, product)
            task_id = create_task(
                research_query,
                sources,
                status="running",
                stage="Queued for the sourcing sandbox",
                intent="research",
                product_key=product["key"],
                quantity=quantity["requested_units"],
                conversation_id=conversation_id,
            )
            save_conversation_message(conversation_id, "user", "text", {"text": message, "sources": sources}, task_id=task_id)
            append_event(
                task_id,
                "research.queued",
                "Sourcing request accepted for {}.".format(quantity["quantity_label"]),
            )
            start_research_task(task_id, research_query, sources, conversation_id)
            return self._send_json(
                202,
                {
                    "task_id": task_id,
                    "status": "running",
                    "intent": "research",
                    "stage": "Preparing the sourcing worker.",
                    "conversation_id": conversation_id,
                },
            )

        task_id = create_task(message, sources, status="running", stage="Waiting for model response", conversation_id=conversation_id)
        save_conversation_message(conversation_id, "user", "text", {"text": message, "sources": sources}, task_id=task_id)
        if not inference_configured():
            inference_policy = inference_policy_status()
            configuration_message = (
                "Blast Radius Zero requires Vultr Serverless Inference for every agent LLM call."
                if inference_policy.get("track") == "blast_radius_zero"
                else "Vultr Serverless Inference is not configured."
            )
            update_task(
                task_id,
                "failed",
                "Model not configured",
                error=configuration_message,
            )
            save_conversation_message(
                conversation_id,
                "assistant",
                "error",
                {"text": "Assistant replies need a configured model endpoint. Your message is saved in this conversation."},
                task_id=task_id,
            )
            return self._send_json(
                503,
                {
                    "error": configuration_message + " Set the approved endpoint, API key, and model on the backend.",
                    "code": "inference_provider_not_allowed" if inference_policy.get("provider_allowed") is False else "inference_not_configured",
                    "task_id": task_id,
                    "conversation_id": conversation_id,
                },
            )
        try:
            answer = request_inference(history)
        except InferenceError as error:
            update_task(task_id, "failed", "Model request failed", error=str(error))
            save_conversation_message(conversation_id, "assistant", "error", {"text": str(error)}, task_id=task_id)
            return self._send_json(
                error.status,
                {"error": str(error), "code": error.code, "task_id": task_id},
            )
        update_task(task_id, "completed", "Response ready", result=answer)
        save_conversation_message(conversation_id, "assistant", "text", {"text": answer, "links": [{"url": url} for url in sources]}, task_id=task_id)
        return self._send_json(
            200,
            {
                "answer": answer,
                "sources": [{"url": url} for url in sources],
                "task_id": task_id,
                "conversation_id": conversation_id,
            },
        )

    def _voice_ask(self):
        payload = self._read_json()
        question = validate_prompt(payload.get("question") or payload.get("message"))
        task_id = payload.get("task_id")
        task = get_task(task_id) if task_id else latest_research_task()
        if not task:
            return self._send_json(
                200,
                {
                    "answer": "There is no completed supplier comparison yet. Start a sourcing request first.",
                    "links": [],
                    "task_id": None,
                },
            )
        research = task.get("research") or {}
        research["task_id"] = task["id"]
        result = answer_from_result(question, research)
        result["task_id"] = task["id"]
        return self._send_json(200, result)

    def _create_watch(self):
        payload = self._read_json()
        if set(payload) - {"task_id", "offer_id", "target_price"}:
            raise ValueError("Unexpected price watch field.")
        offer = stored_offer(payload.get("task_id"), payload.get("offer_id"))
        if not offer:
            raise ValueError("Choose an offer from a completed comparison.")
        if payload.get("target_price") in (None, ""):
            raise ValueError("Enter a target unit price.")
        watch = create_price_watch(payload["task_id"], payload["offer_id"], payload["target_price"])
        return self._send_json(201, {"watch": watch})

    def _create_approval(self):
        payload = self._read_json()
        allowed = {"task_id", "offer_id", "kind", "quantity", "channel"}
        if set(payload) - allowed:
            raise ValueError("Unexpected approval field.")
        task_id = payload.get("task_id")
        offer_id = payload.get("offer_id")
        kind = payload.get("kind")
        task = get_task(task_id) if task_id else None
        if not task:
            raise ValueError("Approval needs a completed comparison task.")
        research = task.get("research") or {}
        offer = stored_offer(task_id, offer_id)
        if not offer:
            raise ValueError("Choose an offer from this comparison.")
        profile = get_profile()
        if kind == "quote_request":
            draft = quote_draft(research, offer, profile)
            title = "Request a quote from {}".format(offer["supplier"])
            body = draft["draft"]
            amount = None
        elif kind == "purchase_order":
            try:
                quantity = int(payload.get("quantity") or research.get("requested_units") or 1)
            except (TypeError, ValueError) as error:
                raise ValueError("Order quantity must be a whole number.") from error
            if quantity < 1 or quantity > 100000:
                raise ValueError("Order quantity must be between 1 and 100,000.")
            draft = purchase_order_draft(research, offer, quantity, profile)
            title = "Approve draft purchase order for {}".format(offer["supplier"])
            body = draft["draft"]
            amount = draft["amount"]
        else:
            raise ValueError("Unsupported approval type.")
        approval = create_approval(task_id, offer_id, kind, title, body, amount=amount)
        return self._send_json(201, {"approval": approval})

    def _decide_approval(self, approval_id):
        payload = self._read_json()
        if set(payload) - {"decision", "note"}:
            raise ValueError("Unexpected approval decision field.")
        approval = decide_approval(approval_id, payload.get("decision"), payload.get("note"))
        return self._send_json(200, {"approval": approval})

    def _save_profile(self):
        payload = self._read_json()
        values = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
        return self._send_json(200, {"profile": save_profile(values)})

    def _sandbox_test(self):
        payload = self._read_json()
        if set(payload) - {"confirm"} or payload.get("confirm") is not True:
            raise ValueError("Containment test requires confirm: true.")
        try:
            result, receipt = containment_test()
        except RuntimeError as error:
            LOG.warning("Worker containment check failed: %s", error)
            return self._send_json(
                503,
                {"error": "The worker isolation check failed. Review the server log before enabling sourcing."},
            )
        return self._send_json(200, {"result": result, "receipt": receipt})


def serve(host=None, port=None):
    load_dotenv()
    if TaskVaultHandler._auth_enabled() and not os.environ.get("TASKVAULT_AUTH_PASSWORD_HASH"):
        raise RuntimeError("TASKVAULT_AUTH_REQUIRED is enabled, but TASKVAULT_AUTH_PASSWORD_HASH is missing.")
    initialize_database()
    host = host or os.environ.get("TASKVAULT_HOST", "127.0.0.1")
    port = int(port or os.environ.get("TASKVAULT_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), TaskVaultHandler)
    LOG.info("TaskVault listening at http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Stopping TaskVault server")
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    serve()
