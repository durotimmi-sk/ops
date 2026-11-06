"""Isolated sourcing worker.

This process receives a bounded JSON request on stdin, reads the bundled supplier
index, and writes a bounded JSON response on stdout. It is launched by
taskvault_sandbox with a minimal environment and a task-scoped working directory.
It has no database path, no inference credentials, and no host mounts.
"""

import json
import errno
import os
import socket
import sys

from taskvault_research import run_research


MAX_INPUT_BYTES = 64 * 1024


def redact_environment():
    suspicious = []
    for key, value in os.environ.items():
        upper = key.upper()
        if any(token in upper for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            suspicious.append(key)
    return suspicious


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise SystemExit(json.dumps({"error": "Request exceeds worker input limit."}))
    try:
        request = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SystemExit(json.dumps({"error": "Request must be valid JSON."}))
    if not isinstance(request, dict) or not isinstance(request.get("query"), str):
        raise SystemExit(json.dumps({"error": "A query is required."}))
    if request.get("mode") == "containment_test":
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.25)
            try:
                probe.connect(("1.1.1.1", 53))
                network_blocked = False
            except OSError as error:
                network_blocked = error.errno in (
                    errno.EPERM,
                    errno.EACCES,
                    errno.ENETUNREACH,
                    errno.EHOSTUNREACH,
                )
        finally:
            probe.close()
        protected_files = []
        for path in request.get("protected_files") or []:
            try:
                with open(path, "rb") as protected_file:
                    protected_file.read(1)
                protected_files.append({"path": path, "blocked": False})
            except PermissionError:
                protected_files.append({"path": path, "blocked": True})
            except FileNotFoundError:
                protected_files.append({"path": path, "blocked": None})
        result = {
            "secrets_visible": redact_environment(),
            "cwd": os.getcwd(),
            "has_database_path": bool(os.environ.get("TASKVAULT_DB_PATH")),
            "has_inference_key": bool(os.environ.get("VULTR_INFERENCE_API_KEY")),
            "network_policy": os.environ.get("TASKVAULT_NETWORK_POLICY", "unset"),
            "network_blocked": network_blocked,
            "protected_files": protected_files,
        }
    else:
        result = run_research(request["query"], sources=request.get("sources") or [])
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
