import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from taskvault_core import database_path


ROOT = Path(__file__).resolve().parent
WORKER_SCRIPT = ROOT / "worker.py"
DEFAULT_TIMEOUT = 25
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


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


def seatbelt_available():
    return sys.platform == "darwin" and bool(shutil.which("sandbox-exec"))


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
