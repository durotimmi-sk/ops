import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

from taskvault_core import database_path
from taskvault_egress import EgressProxy


ROOT = Path(__file__).resolve().parent
WORKER_SCRIPT = ROOT / "worker.py"
BROWSER_WORKER_SCRIPT = ROOT / "browser_worker.py"
DEFAULT_TIMEOUT = 25
BROWSER_TIMEOUT = 75
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_BROWSER_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_BROWSER_PAGES = 3


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def docker_available():
    if not shutil.which("docker"):
        return False
    try:
        completed = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


_SEATBELT_AVAILABLE = None


def seatbelt_available():
    global _SEATBELT_AVAILABLE
    if _SEATBELT_AVAILABLE is not None:
        return _SEATBELT_AVAILABLE
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        _SEATBELT_AVAILABLE = False
        return False
    try:
        completed = subprocess.run(
            ["sandbox-exec", "-p", "(version 1)(allow default)", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        _SEATBELT_AVAILABLE = (completed.returncode == 0)
    except (OSError, subprocess.TimeoutExpired):
        _SEATBELT_AVAILABLE = False
    return _SEATBELT_AVAILABLE


def bubblewrap_available():
    return sys.platform.startswith("linux") and bool(shutil.which("bwrap"))


def sandbox_mode():
    requested = os.environ.get("TASKVAULT_SANDBOX_MODE", "auto").strip().lower()
    if requested == "docker":
        if docker_available():
            return "docker"
        return "macos-seatbelt" if seatbelt_available() else "bubblewrap" if bubblewrap_available() else "unavailable"
    if requested in ("bubblewrap", "bwrap"):
        return "bubblewrap" if bubblewrap_available() else "unavailable"
    if requested in ("seatbelt", "macos-seatbelt"):
        return "macos-seatbelt" if seatbelt_available() else "unavailable"
    if requested == "process":
        return "process"
    if seatbelt_available():
        return "macos-seatbelt"
    if bubblewrap_available():
        return "bubblewrap"
    return "docker" if docker_available() else "process"


def _worker_environment(home, mode):
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "HOME": str(home),
        "TMPDIR": str(home),
        "TASKVAULT_NETWORK_POLICY": "deny" if mode in ("docker", "macos-seatbelt") else "process-unrestricted",
    }


def _resource_limiter():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        return


def _stop_process(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            import signal
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _run_subprocess(command, input_bytes, timeout, cwd, env, preexec_fn=None, cancel_check=None):
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        preexec_fn=preexec_fn,
        start_new_session=(os.name == "posix"),
    )
    deadline = time.monotonic() + timeout
    pending_input = input_bytes
    try:
        while True:
            if cancel_check and cancel_check():
                _stop_process(process)
                raise InterruptedError("The sourcing worker was stopped by the buyer.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(input=pending_input, timeout=min(0.05, remaining))
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                pending_input = None
    except BaseException:
        _stop_process(process)
        raise


def _receipt(worker_id, mode, started, exit_code, stderr, degraded=False):
    duration_ms = int((time.monotonic() - started) * 1000)
    if mode == "docker":
        network = "denied"
        filesystem = "read-only root + task tmpfs"
        limits = "256 MB memory · 0.5 CPU · 64 PIDs · 25 s wall clock"
        teardown = "Task directory removed; container exits with --rm."
    elif mode == "macos-seatbelt":
        network = "denied by macOS Seatbelt"
        filesystem = "Project writes denied; task temp directory writable; app database and .env unreadable"
        limits = "20 s CPU · 2 MB file-size cap · 25 s wall clock"
        teardown = "Task directory removed; sandboxed process exited."
    elif mode == "bubblewrap":
        network = "denied by isolated Linux network namespace"
        filesystem = "Worker code read-only; only task temporary directory writable; application data and credentials not mounted"
        limits = "20 s CPU · 2 MB file-size cap · 25 s wall clock"
        teardown = "Task directory removed; isolated namespaces exited."
    else:
        network = "unrestricted host network"
        filesystem = "Host filesystem remains accessible; worker starts in a task-scoped temporary directory"
        limits = "20 s CPU · file-size cap · 25 s wall clock"
        teardown = "Task directory removed; process exited."
    return {
        "worker_id": worker_id,
        "mode": mode,
        "started_at": utc_now(),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "network": network,
        "filesystem": filesystem,
        "limits": limits,
        "secrets_policy": "No inference keys or database paths are inherited.",
        "teardown": teardown,
        "degraded": degraded,
        "stderr": (stderr or "")[:600],
    }


def run_worker(query, sources=None, timeout=DEFAULT_TIMEOUT, extra=None, cancel_check=None):
    worker_id = "wk_" + uuid.uuid4().hex[:12]
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix="taskvault-worker-"))
    payload = {"query": query, "sources": sources or [], "mode": "research"}
    if extra:
        payload.update(extra)
    request_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    mode = sandbox_mode()
    degraded = False
    worker_root = None
    try:
        if mode == "unavailable":
            raise RuntimeError("The configured worker isolation runtime is unavailable.")
        if mode == "docker":
            command = [
                "docker", "run", "--rm", "-i",
                "--network", "none",
                "--read-only",
                "--tmpfs", "/tmp:rw,size=16m",
                "--memory", "256m",
                "--cpus", "0.5",
                "--pids-limit", "64",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--user", "65534:65534",
                os.environ.get("TASKVAULT_WORKER_IMAGE", "taskvault-worker:local"),
            ]
            completed = _run_subprocess(
                command,
                request_bytes,
                timeout=timeout,
                cwd=workdir,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                cancel_check=cancel_check,
            )
        elif mode == "macos-seatbelt":
            profile = "\n".join((
                "(version 1)",
                "(allow default)",
                "(deny network*)",
                '(deny file-read* (subpath (param "TASKVAULT_DATA_DIR")))',
                '(deny file-read* (literal (param "TASKVAULT_ENV_FILE")))',
                '(deny file-read* (literal (param "TASKVAULT_DB_FILE")))',
                '(deny file-read* (literal (param "TASKVAULT_DB_WAL")))',
                '(deny file-read* (literal (param "TASKVAULT_DB_SHM")))',
                '(deny file-read* (literal (param "TASKVAULT_DB_JOURNAL")))',
                '(deny file-write* (subpath (param "TASKVAULT_ROOT")))',
                '(deny file-write* (subpath (param "TASKVAULT_HOME")))',
                '(allow file-write* (subpath (param "TASKVAULT_WORKDIR")))',
            ))
            app_data = ROOT / "data"
            env_file = ROOT / ".env"
            app_db = database_path()
            command = [
                "sandbox-exec",
                "-D", "TASKVAULT_DATA_DIR={}".format(app_data),
                "-D", "TASKVAULT_ENV_FILE={}".format(env_file),
                "-D", "TASKVAULT_DB_FILE={}".format(app_db),
                "-D", "TASKVAULT_DB_WAL={}-wal".format(app_db),
                "-D", "TASKVAULT_DB_SHM={}-shm".format(app_db),
                "-D", "TASKVAULT_DB_JOURNAL={}-journal".format(app_db),
                "-D", "TASKVAULT_ROOT={}".format(ROOT),
                "-D", "TASKVAULT_HOME={}".format(Path.home()),
                "-D", "TASKVAULT_WORKDIR={}".format(workdir),
                "-p", profile,
                sys.executable, "-B", str(WORKER_SCRIPT),
            ]
            completed = _run_subprocess(
                command,
                request_bytes,
                timeout=timeout,
                cwd=workdir,
                env=_worker_environment(workdir, mode),
                preexec_fn=_resource_limiter,
                cancel_check=cancel_check,
            )
        elif mode == "bubblewrap":
            worker_root = Path(tempfile.mkdtemp(prefix="taskvault-worker-code-"))
            (worker_root / "catalog").mkdir(parents=True)
            for name in ("worker.py", "taskvault_research.py", "taskvault_catalog.py"):
                shutil.copyfile(ROOT / name, worker_root / name)
            shutil.copyfile(ROOT / "catalog" / "suppliers.json", worker_root / "catalog" / "suppliers.json")
            command = [
                "bwrap", "--die-with-parent", "--new-session", "--unshare-all",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                "--ro-bind", "/lib64", "/lib64",
                "--ro-bind", str(worker_root), "/app",
                "--proc", "/proc",
                "--dev", "/dev",
                "--bind", str(workdir), "/tmp",
                "--chdir", "/tmp",
                "--clearenv",
                "--setenv", "PATH", "/usr/bin:/bin",
                "--setenv", "LANG", "C.UTF-8",
                "--setenv", "LC_ALL", "C.UTF-8",
                "--setenv", "PYTHONIOENCODING", "utf-8",
                "--setenv", "HOME", "/tmp",
                "--setenv", "TMPDIR", "/tmp",
                "--setenv", "TASKVAULT_NETWORK_POLICY", "deny",
                getattr(sys, "_base_executable", sys.executable), "-B", "/app/worker.py",
            ]
            completed = _run_subprocess(
                command,
                request_bytes,
                timeout=timeout,
                cwd=workdir,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                preexec_fn=_resource_limiter,
                cancel_check=cancel_check,
            )
        else:
            completed = _run_subprocess(
                [sys.executable, "-B", str(WORKER_SCRIPT)],
                request_bytes,
                timeout=timeout,
                cwd=workdir,
                env=_worker_environment(workdir, mode),
                preexec_fn=_resource_limiter if os.name == "posix" else None,
                cancel_check=cancel_check,
            )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise TimeoutError("The sandbox exceeded its {} second limit.".format(timeout)) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if worker_root:
            shutil.rmtree(worker_root, ignore_errors=True)

    stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        raise ValueError("The sandbox returned more data than the allowed limit.")
    if completed.returncode != 0:
        raise RuntimeError("The sourcing worker failed: {}".format(stderr.strip()[:300] or "unknown error"))
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("The sandbox returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("The sandbox returned an unexpected payload.")
    receipt = _receipt(worker_id, mode, started, completed.returncode, stderr, degraded=degraded)
    return result, receipt


def containment_test():
    protected_files = [
        str(path)
        for path in (database_path(), ROOT / ".env")
        if path.exists()
    ]
    result, receipt = run_worker(
        "Containment self-test",
        extra={"mode": "containment_test", "protected_files": protected_files},
        timeout=15,
    )
    visible = result.get("secrets_visible") or []
    file_access_is_blocked = all(
        item.get("blocked") in (True, None)
        for item in result.get("protected_files", [])
    )
    result["pass"] = (
        not result.get("has_database_path")
        and not result.get("has_inference_key")
        and not visible
        and result.get("network_blocked") is True
        and file_access_is_blocked
    )
    result["checked"] = [
        "No inference key inherited",
        "No database path inherited",
        "No secret-named environment variables present",
        "Network access denied by the active sandbox",
        "Existing app database and .env files are unreadable by the worker",
        "Task-scoped working directory",
    ]
    return result, receipt


def browser_sandbox_mode():
    requested = os.environ.get("TASKVAULT_BROWSER_SANDBOX_MODE", "process").strip().lower()
    if requested in ("process", "browser-process"):
        return "browser-process"
    if requested in ("bubblewrap", "bwrap", "browser-bubblewrap"):
        return "unavailable"
    return "browser-process"


def _browser_resource_limiter():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        return


def _browser_environment(home):
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "HOME": str(home),
        "TMPDIR": str(home),
        "TASKVAULT_NETWORK_POLICY": "allowlist-proxy",
    }
    for name in ("TASKVAULT_BROWSER_CHANNEL", "TASKVAULT_BROWSER_EXECUTABLE", "PLAYWRIGHT_BROWSERS_PATH"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _copy_capture_artifacts(source, destination):
    if not source.exists() or destination is None:
        return []
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in sorted(source.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        if not re.fullmatch(r"[a-z0-9-]{1,40}\.png", path.name):
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            continue
        target = destination / path.name
        shutil.copyfile(path, target)
        copied.append(path.name)
    return copied


def _browser_receipt(worker_id, mode, started, exit_code, stderr, proxy, result, degraded=False):
    duration_ms = int((time.monotonic() - started) * 1000)
    filesystem = "Task-scoped temporary profile; host filesystem remains readable by the browser process"
    teardown = "Browser and proxy exited; task directory removed."
    degraded = True
    return {
        "worker_id": worker_id,
        "mode": mode,
        "started_at": utc_now(),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "network": "HTTPS 443 only through a loopback allowlist proxy; private, local, reserved, and redirect destinations are revalidated",
        "filesystem": filesystem,
        "limits": "3 pages · 15 s navigation each · 75 s wall clock · 60 s CPU · 32 MB file cap",
        "secrets_policy": "No inference keys, database paths, or application environment are inherited.",
        "teardown": teardown,
        "degraded": degraded,
        "browser_version": (result.get("browser") or {}).get("version"),
        "blocked_proxy_requests": len(proxy.blocked) if proxy else 0,
        "stderr": (stderr or "")[:600],
    }


def run_browser_capture(urls, artifact_dir=None, allowlist=None, timeout=BROWSER_TIMEOUT, cancel_check=None):
    if not urls:
        return {"mode": "browser_capture", "requested_count": 0, "captured_count": 0, "error_count": 0, "captures": []}, None
    if importlib.util.find_spec("playwright") is None:
        raise RuntimeError("Playwright is not installed; live source capture is unavailable.")
    urls = list(urls)[:MAX_BROWSER_PAGES]
    hosts = []
    for value in urls:
        try:
            host = urllib.parse.urlsplit(value).hostname
        except ValueError:
            host = None
        if host:
            hosts.append(host)
    allowlist = allowlist or hosts
    mode = browser_sandbox_mode()
    if mode == "unavailable":
        raise RuntimeError("The configured browser isolation runtime is unavailable.")
    worker_id = "bw_" + uuid.uuid4().hex[:12]
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix="taskvault-browser-"))
    artifacts = workdir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    proxy = EgressProxy(allowlist)
    completed = None
    result = None
    try:
        proxy.__enter__()
        payload = {
            "mode": "browser_capture",
            "urls": urls,
            "allowlist": sorted(proxy.allowlist),
            "proxy": proxy.url,
            "artifacts_dir": "artifacts",
        }
        command = [
            sys.executable,
            "-B",
            str(BROWSER_WORKER_SCRIPT),
        ]
        completed = _run_subprocess(
            command,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
            cwd=workdir,
            env=_browser_environment(workdir),
            preexec_fn=_browser_resource_limiter,
            cancel_check=cancel_check,
        )
        stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
        if len(completed.stdout) > MAX_BROWSER_OUTPUT_BYTES:
            raise ValueError("The browser worker returned more data than the allowed limit.")
        if completed.returncode != 0:
            raise RuntimeError("The browser worker failed: {}".format(stderr.strip()[:300] or "unknown error"))
        try:
            result = json.loads(completed.stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("The browser worker returned invalid JSON.") from error
        if not isinstance(result, dict) or not isinstance(result.get("captures"), list):
            raise ValueError("The browser worker returned an unexpected payload.")
        copied = _copy_capture_artifacts(artifacts, artifact_dir)
        copied_set = set(copied)
        for capture in result["captures"]:
            if not isinstance(capture, dict):
                continue
            screenshot = capture.get("screenshot_file")
            if screenshot not in copied_set:
                capture["screenshot_file"] = None
                if capture.get("screenshot_sha256"):
                    capture["error"] = "The screenshot artifact was not retained."
        result["proxy_blocked_requests"] = proxy.blocked[:50]
        result["screenshots_retained"] = len(copied)
        receipt = _browser_receipt(
            worker_id,
            mode,
            started,
            completed.returncode,
            stderr,
            proxy,
            result,
        )
        return result, receipt
    finally:
        proxy.__exit__(None, None, None)
        shutil.rmtree(workdir, ignore_errors=True)
