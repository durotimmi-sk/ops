import hashlib
import ipaddress
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "data" / "taskvault.sqlite3"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_dotenv(path=None):
    env_path = Path(path) if path else ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return

    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[7:].lstrip()
        key, separator, value = entry.partition("=")
        if not separator or not key.strip():
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def database_path():
    configured = os.environ.get("TASKVAULT_DB_PATH")
    path = Path(configured) if configured else DEFAULT_DB_PATH
    return path if path.is_absolute() else ROOT / path


def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _column_names(connection, table):
    return {row["name"] for row in connection.execute("PRAGMA table_info({})".format(table))}


def _ensure_column(connection, table, column, declaration):
    if column not in _column_names(connection, table):
        connection.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, declaration))


def initialize_database():
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                query TEXT NOT NULL,
                source_urls TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT '',
                result TEXT,
                error TEXT,
                stop_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                kind TEXT NOT NULL,
                content_json TEXT NOT NULL,
                task_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS offers (
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                offer_id TEXT NOT NULL,
                product_key TEXT NOT NULL,
                supplier TEXT NOT NULL,
                location TEXT NOT NULL,
                unit_price REAL NOT NULL,
                landed_cost REAL NOT NULL,
                moq_units INTEGER NOT NULL,
                lead_time_days INTEGER NOT NULL,
                rating REAL NOT NULL,
                verified INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_title TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, offer_id)
            );
            CREATE TABLE IF NOT EXISTS task_captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                source_url TEXT NOT NULL,
                final_url TEXT,
                host TEXT,
                title TEXT,
                http_status INTEGER,
                captured_at TEXT,
                screenshot_file TEXT,
                screenshot_sha256 TEXT,
                screenshot_bytes INTEGER,
                text_sha256 TEXT,
                text_excerpt TEXT,
                blocked_requests INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS price_watches (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                offer_id TEXT NOT NULL,
                supplier TEXT NOT NULL,
                product TEXT NOT NULL,
                target_price REAL NOT NULL,
                current_price REAL NOT NULL,
                previous_price REAL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_checked_at TEXT NOT NULL,
                last_result_json TEXT
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                offer_id TEXT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                amount REAL,
                currency TEXT NOT NULL DEFAULT 'USD',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decision_note TEXT
            );
            CREATE TABLE IF NOT EXISTS buyer_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                company TEXT NOT NULL DEFAULT '',
                buyer_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                ship_to TEXT NOT NULL DEFAULT '',
                budget REAL NOT NULL DEFAULT 0,
                approval_threshold REAL NOT NULL DEFAULT 2500,
                payment_method TEXT NOT NULL DEFAULT 'approval_only',
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages ON conversation_messages(conversation_id, id);
            CREATE INDEX IF NOT EXISTS idx_offers_task ON offers(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_captures_task ON task_captures(task_id, id);
            CREATE INDEX IF NOT EXISTS idx_watches_status ON price_watches(status);
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
            """
        )
        _ensure_column(connection, "tasks", "intent", "TEXT NOT NULL DEFAULT 'chat'")
        _ensure_column(connection, "tasks", "product_key", "TEXT")
        _ensure_column(connection, "tasks", "quantity", "INTEGER")
        _ensure_column(connection, "tasks", "summary", "TEXT")
        _ensure_column(connection, "tasks", "recommendation", "TEXT")
        _ensure_column(connection, "tasks", "research_json", "TEXT")
        _ensure_column(connection, "tasks", "sandbox_json", "TEXT")
        _ensure_column(connection, "tasks", "conversation_id", "TEXT")


def validate_prompt(value):
    if not isinstance(value, str):
        raise ValueError("A request message is required.")
    prompt = value.strip()
    if not prompt:
        raise ValueError("A request message is required.")
    if len(prompt) > 4000:
        raise ValueError("A request must be 4,000 characters or fewer.")
    return prompt


def validate_public_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Each source must be a public http or https URL.")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("Source URLs cannot contain whitespace or control characters.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("A source URL is malformed.") from exc
    if parsed.scheme not in ("http", "https") or not hostname or parsed.username or parsed.password:
        raise ValueError("Each source must be a public http or https URL without embedded credentials.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("A source URL has an invalid port.")
    hostname = hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local and internal network addresses are not accepted as sources.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private and reserved IP addresses are not accepted as sources.")
    return value


def validate_sources(values):
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("Provide no more than 20 source URLs.")
    sources = []
    seen = set()
    for item in values:
        value = item.get("url") if isinstance(item, dict) else item
        url = validate_public_url(value)
        if url not in seen:
            sources.append(url)
            seen.add(url)
    return sources


def _record_event(connection, task_id, kind, message, created_at):
    connection.execute(
        "INSERT INTO task_events (task_id, kind, message, created_at) VALUES (?, ?, ?, ?)",
        (task_id, kind, message, created_at),
    )
    previous = connection.execute(
        "SELECT event_hash FROM audit_ledger ORDER BY id DESC LIMIT 1"
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else "0" * 64
    canonical = json.dumps(
        {
            "task_id": task_id,
            "kind": kind,
            "message": message,
            "created_at": created_at,
            "previous_hash": previous_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    connection.execute(
        """
        INSERT INTO audit_ledger
            (task_id, kind, message, created_at, previous_hash, event_hash)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, kind, message, created_at, previous_hash, event_hash),
    )
    return event_hash


def append_event(task_id, kind, message):
    timestamp = utc_now()
    with connect() as connection:
        _record_event(connection, task_id, kind, message, timestamp)
    return timestamp


def create_conversation(conversation_id=None):
    conversation_id = str(conversation_id or uuid.uuid4())
    try:
        conversation_id = str(uuid.UUID(conversation_id))
    except (ValueError, AttributeError) as error:
        raise ValueError("Conversation id must be a UUID.") from error
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, "New conversation", timestamp, timestamp),
        )
    return conversation_id


def save_conversation_message(conversation_id, role, kind, content, task_id=None):
    if role not in ("user", "assistant") or kind not in ("text", "research", "error"):
        raise ValueError("Unsupported conversation message.")
    conversation_id = create_conversation(conversation_id)
    timestamp = utc_now()
    encoded = json.dumps(content, ensure_ascii=False)
    with connect() as connection:
        connection.execute(
            "INSERT INTO conversation_messages (conversation_id, role, kind, content_json, task_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, role, kind, encoded, task_id, timestamp),
        )
        if role == "user" and kind == "text":
            text = content.get("text", "") if isinstance(content, dict) else str(content)
            connection.execute(
                "UPDATE conversations SET title = CASE WHEN title = 'New conversation' THEN ? ELSE title END, updated_at = ? WHERE id = ?",
                (text[:80], timestamp, conversation_id),
            )
        else:
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (timestamp, conversation_id))
    return conversation_id


def get_conversation(conversation_id):
    with connect() as connection:
        conversation = connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not conversation:
            return None
        messages = connection.execute(
            "SELECT role, kind, content_json, task_id, created_at FROM conversation_messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return {
        **dict(conversation),
        "messages": [
            {"role": row["role"], "kind": row["kind"], "content": json.loads(row["content_json"]), "task_id": row["task_id"], "created_at": row["created_at"]}
            for row in messages
        ],
    }


def create_task(query, sources=None, status="queued", stage="Queued", intent="chat", product_key=None, quantity=None, conversation_id=None):
    prompt = validate_prompt(query)
    source_urls = validate_sources(sources)
    if status not in ("queued", "running"):
        raise ValueError("Task status must be queued or running.")
    task_id = str(uuid.uuid4())
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO tasks
                (id, conversation_id, query, source_urls, status, stage, created_at, updated_at, source_count,
                 intent, product_key, quantity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                conversation_id,
                prompt,
                json.dumps(source_urls, ensure_ascii=False),
                status,
                stage,
                timestamp,
                timestamp,
                len(source_urls),
                intent,
                product_key,
                quantity,
            ),
        )
        _record_event(connection, task_id, "task.created", "Research task created.", timestamp)
    return task_id


def update_task(
    task_id,
    status,
    stage,
    result=None,
    error=None,
    research=None,
    sandbox=None,
    summary=None,
    recommendation=None,
    product_key=None,
    quantity=None,
):
    if status not in ("running", "completed", "failed", "stopped"):
        raise ValueError("Unsupported task status.")
    timestamp = utc_now()
    kind = "task.completed" if status == "completed" else "task.failed" if status == "failed" else (
        "task.stopped" if status == "stopped" else "task.updated"
    )
    message = "Research response completed." if status == "completed" else (
        "Research request failed." if status == "failed" else (
            "Research request stopped." if status == "stopped" else stage
        )
    )
    research_json = json.dumps(research, ensure_ascii=False) if research is not None else None
    sandbox_json = json.dumps(sandbox, ensure_ascii=False) if sandbox is not None else None
    with connect() as connection:
        current = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if current is None:
            raise LookupError("Task not found.")
        connection.execute(
            """
            UPDATE tasks
            SET status = ?,
                stage = ?,
                result = COALESCE(?, result),
                error = COALESCE(?, error),
                summary = COALESCE(?, summary),
                recommendation = COALESCE(?, recommendation),
                product_key = COALESCE(?, product_key),
                quantity = COALESCE(?, quantity),
                research_json = COALESCE(?, research_json),
                sandbox_json = COALESCE(?, sandbox_json),
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                stage,
                result,
                error,
                summary,
                recommendation,
                product_key,
                quantity,
                research_json,
                sandbox_json,
                timestamp,
                task_id,
            ),
        )
        _record_event(connection, task_id, kind, message, timestamp)


def save_research(task_id, research):
    timestamp = utc_now()
    offers = research.get("offers") if isinstance(research, dict) else None
    if not isinstance(offers, list):
        return
    with connect() as connection:
        connection.execute("DELETE FROM offers WHERE task_id = ?", (task_id,))
        for offer in offers:
            connection.execute(
                """
                INSERT INTO offers
                    (task_id, offer_id, product_key, supplier, location, unit_price, landed_cost,
                     moq_units, lead_time_days, rating, verified, image_url, source_url,
                     source_title, data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    offer.get("id", ""),
                    offer.get("product_key", ""),
                    offer.get("supplier", ""),
                    offer.get("location", ""),
                    float(offer.get("unit_price", 0) or 0),
                    float(offer.get("landed_cost", 0) or 0),
                    int(offer.get("moq_units", 0) or 0),
                    int(offer.get("lead_time_days", 0) or 0),
                    float(offer.get("rating", 0) or 0),
                    1 if offer.get("verified") else 0,
                    offer.get("image_url", ""),
                    offer.get("source_url", ""),
                    offer.get("source_title", ""),
                    json.dumps(offer, ensure_ascii=False),
                    timestamp,
                ),
            )


def save_task_captures(task_id, captures, artifact_base_url=None):
    if not isinstance(captures, list):
        return
    timestamp = utc_now()
    with connect() as connection:
        connection.execute("DELETE FROM task_captures WHERE task_id = ?", (task_id,))
        for capture in captures:
            if not isinstance(capture, dict):
                continue
            screenshot = capture.get("screenshot_file")
            if screenshot and artifact_base_url:
                screenshot = "{}/{}".format(artifact_base_url.rstrip("/"), screenshot)
            connection.execute(
                """
                INSERT INTO task_captures
                    (task_id, source_url, final_url, host, title, http_status, captured_at,
                     screenshot_file, screenshot_sha256, screenshot_bytes, text_sha256,
                     text_excerpt, blocked_requests, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    capture.get("url", ""),
                    capture.get("final_url"),
                    capture.get("host"),
                    capture.get("title"),
                    capture.get("http_status"),
                    capture.get("captured_at"),
                    screenshot,
                    capture.get("screenshot_sha256"),
                    int(capture.get("screenshot_bytes", 0) or 0),
                    capture.get("text_sha256"),
                    capture.get("text_excerpt", ""),
                    int(capture.get("blocked_requests", 0) or 0),
                    capture.get("error"),
                    timestamp,
                ),
            )


def list_task_captures(task_id, limit=50):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, task_id, source_url, final_url, host, title, http_status, captured_at,
                   screenshot_file, screenshot_sha256, screenshot_bytes, text_sha256,
                   text_excerpt, blocked_requests, error, created_at
            FROM task_captures
            WHERE task_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (task_id, max(1, min(int(limit), 200))),
        ).fetchall()
    return [dict(row) for row in rows]


def _task_from_row(row):
    task = dict(row)
    task["sources"] = json.loads(task.pop("source_urls") or "[]")
    research_json = task.pop("research_json", None)
    sandbox_json = task.pop("sandbox_json", None)
    task["research"] = json.loads(research_json) if research_json else None
    task["sandbox"] = json.loads(sandbox_json) if sandbox_json else None
    return task


def get_task(task_id):
    with connect() as connection:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_from_row(row) if row else None


def list_tasks(limit=100):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [_task_from_row(row) for row in rows]


def list_task_events(task_id, limit=200):
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, task_id, kind, message, created_at FROM task_events WHERE task_id = ? ORDER BY id ASC LIMIT ?",
            (task_id, max(1, min(int(limit), 500))),
        ).fetchall()
    return [dict(row) for row in rows]


def request_stop(task_id):
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE tasks SET stop_requested = 1, updated_at = ? WHERE id = ?",
            (utc_now(), task_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("Task not found.")
    return True


def stop_requested(task_id):
    with connect() as connection:
        row = connection.execute("SELECT stop_requested FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return bool(row and row["stop_requested"])


def get_offer(task_id, offer_id):
    with connect() as connection:
        row = connection.execute(
            "SELECT data_json FROM offers WHERE task_id = ? AND offer_id = ?",
            (task_id, offer_id),
        ).fetchone()
    return json.loads(row["data_json"]) if row else None


def list_activity(limit=100):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, task_id, kind, message, created_at, previous_hash, event_hash
            FROM audit_ledger ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_audit_ledger():
    previous_hash = "0" * 64
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT task_id, kind, message, created_at, previous_hash, event_hash
            FROM audit_ledger ORDER BY id
            """
        ).fetchall()
    for row in rows:
        if row["previous_hash"] != previous_hash:
            return False
        canonical = json.dumps(
            {
                "task_id": row["task_id"],
                "kind": row["kind"],
                "message": row["message"],
                "created_at": row["created_at"],
                "previous_hash": row["previous_hash"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if row["event_hash"] != expected:
            return False
        previous_hash = row["event_hash"]
    return True


def create_price_watch(task_id, offer_id, target_price):
    offer = get_offer(task_id, offer_id)
    if not offer:
        raise LookupError("Offer not found.")
    try:
        target = float(target_price)
    except (TypeError, ValueError) as exc:
        raise ValueError("A numeric target price is required.") from exc
    if target <= 0:
        raise ValueError("The target price must be greater than zero.")
    watch_id = str(uuid.uuid4())
    timestamp = utc_now()
    result = {
        "status": "watching",
        "message": "Waiting for the next checked price.",
    }
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO price_watches
                (id, task_id, offer_id, supplier, product, target_price, current_price,
                 previous_price, status, created_at, last_checked_at, last_result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                watch_id,
                task_id,
                offer_id,
                offer.get("supplier", ""),
                offer.get("product_name", ""),
                target,
                float(offer.get("unit_price", 0) or 0),
                float(offer.get("previous_price", 0) or 0) if offer.get("previous_price") else None,
                "watching",
                timestamp,
                timestamp,
                json.dumps(result),
            ),
        )
    append_event(task_id, "watch.created", "Price watch created for {}.".format(offer.get("supplier", "supplier")))
    return get_price_watch(watch_id)


def _watch_from_row(row):
    watch = dict(row)
    result_json = watch.pop("last_result_json", None)
    watch["last_result"] = json.loads(result_json) if result_json else None
    return watch


def get_price_watch(watch_id):
    with connect() as connection:
        row = connection.execute("SELECT * FROM price_watches WHERE id = ?", (watch_id,)).fetchone()
    return _watch_from_row(row) if row else None


def list_price_watches(limit=100):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM price_watches ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [_watch_from_row(row) for row in rows]


def check_price_watch(watch_id):
    watch = get_price_watch(watch_id)
    if not watch:
        raise LookupError("Price watch not found.")
    offer = get_offer(watch["task_id"], watch["offer_id"]) if watch["task_id"] else None
    if not offer:
        raise LookupError("The linked offer is no longer available.")
    current = float(offer.get("unit_price", 0) or 0)
    status = "triggered" if current <= float(watch["target_price"]) else "watching"
    timestamp = utc_now()
    result = {
        "status": status,
        "current_price": current,
        "target_price": watch["target_price"],
        "message": "Target reached. Review the supplier before acting." if status == "triggered"
        else "Price is above your target. We will keep this watch active.",
    }
    with connect() as connection:
        connection.execute(
            """
            UPDATE price_watches
            SET current_price = ?, status = ?, last_checked_at = ?, last_result_json = ?
            WHERE id = ?
            """,
            (current, status, timestamp, json.dumps(result), watch_id),
        )
    if watch["task_id"]:
        append_event(
            watch["task_id"],
            "watch.checked",
            "Price watch checked for {}: ${:.2f} per {}.".format(
                watch["supplier"], current, offer.get("unit", "unit")
            ),
        )
    return get_price_watch(watch_id)


def create_approval(task_id, offer_id, kind, title, body, amount=None, currency="USD"):
    if kind not in ("quote_request", "purchase_order", "supplier_call"):
        raise ValueError("Unsupported approval type.")
    approval_id = str(uuid.uuid4())
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO approvals
                (id, task_id, offer_id, kind, title, body, amount, currency, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (approval_id, task_id, offer_id, kind, title, body, amount, currency, timestamp),
        )
    append_event(task_id, "approval.requested", "Human approval requested: {}.".format(title))
    return get_approval(approval_id)


def get_approval(approval_id):
    with connect() as connection:
        row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    return dict(row) if row else None


def list_approvals(limit=100):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [dict(row) for row in rows]


def decide_approval(approval_id, decision, note=None):
    if decision not in ("approved", "rejected"):
        raise ValueError("Decision must be approved or rejected.")
    timestamp = utc_now()
    with connect() as connection:
        row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise LookupError("Approval not found.")
        if row["status"] != "pending":
            raise ValueError("This approval has already been decided.")
        connection.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (decision, timestamp, (note or "")[:500], approval_id),
        )
    append_event(
        row["task_id"],
        "approval.decided",
        "Human decision recorded: {} — {}.".format(row["title"], decision),
    )
    return get_approval(approval_id)


def get_profile():
    with connect() as connection:
        row = connection.execute("SELECT * FROM buyer_profile WHERE id = 1").fetchone()
    if row:
        return dict(row)
    return {
        "id": 1,
        "company": "",
        "buyer_name": "",
        "email": "",
        "phone": "",
        "ship_to": "",
        "budget": 0,
        "approval_threshold": 2500,
        "payment_method": "approval_only",
        "updated_at": None,
    }


def save_profile(values):
    if not isinstance(values, dict):
        raise ValueError("Profile values must be an object.")
    allowed = {
        "company", "buyer_name", "email", "phone", "ship_to", "budget",
        "approval_threshold", "payment_method",
    }
    if set(values) - allowed:
        raise ValueError("Unexpected profile field.")
    if values.get("payment_method") not in (None, "", "approval_only", "invoice", "hosted_checkout"):
        raise ValueError("Unsupported payment method.")
    for key in ("company", "buyer_name", "email", "phone", "ship_to"):
        if key in values and (not isinstance(values[key], str) or len(values[key]) > 200):
            raise ValueError("Profile text fields must be 200 characters or fewer.")
    try:
        budget = float(values.get("budget", 0) or 0)
        threshold = float(values.get("approval_threshold", 2500) or 2500)
    except (TypeError, ValueError) as exc:
        raise ValueError("Budget and approval threshold must be numbers.") from exc
    if budget < 0 or threshold < 0:
        raise ValueError("Budget and approval threshold cannot be negative.")
    current = get_profile()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO buyer_profile
                (id, company, buyer_name, email, phone, ship_to, budget, approval_threshold,
                 payment_method, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                company = excluded.company,
                buyer_name = excluded.buyer_name,
                email = excluded.email,
                phone = excluded.phone,
                ship_to = excluded.ship_to,
                budget = excluded.budget,
                approval_threshold = excluded.approval_threshold,
                payment_method = excluded.payment_method,
                updated_at = excluded.updated_at
            """,
            (
                values.get("company", current["company"]),
                values.get("buyer_name", current["buyer_name"]),
                values.get("email", current["email"]),
                values.get("phone", current["phone"]),
                values.get("ship_to", current["ship_to"]),
                budget,
                threshold,
                values.get("payment_method", current["payment_method"]),
                utc_now(),
            ),
        )
    return get_profile()


def latest_research_task():
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM tasks WHERE intent = 'research' AND status = 'completed' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return get_task(row["id"]) if row else None


def task_result(task_id):
    task = get_task(task_id)
    if not task:
        return None
    research = task.get("research") or {}
    return {
        "task_id": task["id"],
        "status": task["status"],
        "stage": task["stage"],
        "query": task["query"],
        "intent": task.get("intent"),
        "summary": task.get("summary"),
        "recommendation": task.get("recommendation"),
        "research": research,
        "captures": list_task_captures(task["id"]),
        "sandbox": task.get("sandbox"),
        "error": task.get("error"),
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }
