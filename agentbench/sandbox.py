"""Where a trial runs.

Each trial gets a fresh sandbox with two areas: the workspace, which the agent
sees and changes, and a private area outside it where the harness stages the
reference solution and the verifier. The verifier is copied in only after the
agent has finished, so the agent never sees the tests.

LocalSandbox uses a temp directory and subprocesses: fast, good for development
and trusted agents. DockerSandbox runs everything in a container with no network
and resource limits, for agents you do not trust."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecResult:
    exit_code: int | None  # None when the command timed out
    output: str
    seconds: float

    @property
    def timed_out(self) -> bool:
        return self.exit_code is None


def find_bash() -> str:
    for cand in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"):
        if cand and os.path.exists(cand):
            return cand
    raise RuntimeError("bash not found")


class _ProcessGroup:
    """Kills a command and everything it started.

    POSIX: the command leads its own session, so killpg reaches every descendant.
    Windows: taskkill /T misses MSYS children (bash re-parents them), so the
    command goes into a Job Object, which every descendant inherits."""

    def __init__(self, proc: subprocess.Popen):
        self.proc, self.job = proc, None
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateJobObjectW.restype = wintypes.HANDLE
            k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k.CloseHandle.argtypes = [wintypes.HANDLE]
            self.k = k
            self.job = k.CreateJobObjectW(None, None)
            k.AssignProcessToJobObject(self.job, int(proc._handle))

    def kill(self) -> None:
        if self.job:
            self.k.TerminateJobObject(self.job, 1)
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self) -> None:
        if self.job:
            self.k.CloseHandle(self.job)
            self.job = None


def _tail(text: str, limit: int = 20_000) -> str:
    return text if len(text) <= limit else f"[{len(text) - limit} characters omitted]\n" + text[-limit:]


class Sandbox:
    workspace: str  # path of the workspace as seen by commands in the sandbox
    private: str  # path of the harness-only area as seen by commands in the sandbox
    python: str  # interpreter with pytest installed, used for verifiers

    def exec(self, command: str, timeout: float, env: dict[str, str] | None = None,
             cwd: str | None = None) -> ExecResult: ...

    def put(self, src: Path, dest: str) -> None:
        """Copy a host file or directory to `dest` inside the sandbox."""

    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LocalSandbox(Sandbox):
    # variables a build or test needs; everything else (API keys, tokens) is dropped
    PASS_ENV = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG",
                "LC_ALL", "PROGRAMFILES", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME")

    def __init__(self, environment: Path | None = None, keep: bool = False):
        self.root = Path(tempfile.mkdtemp(prefix="abench-"))
        self.keep = keep
        ws, priv = self.root / "workspace", self.root / "private"
        if environment is not None and environment.is_dir():
            shutil.copytree(environment, ws)
        else:
            ws.mkdir()
        priv.mkdir()
        self.workspace, self.private = ws.as_posix(), priv.as_posix()
        self.python = Path(sys.executable).as_posix()

    def exec(self, command, timeout, env=None, cwd=None):
        base = {k: v for k, v in os.environ.items() if k.upper() in self.PASS_ENV}
        full_env = {**base, "WORKSPACE": self.workspace, "PYTHON": self.python, "PYTHONDONTWRITEBYTECODE": "1",
                    **(env or {})}
        start = time.monotonic()
        proc = subprocess.Popen(
            [find_bash(), "-c", command], cwd=cwd or self.workspace, env=full_env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=sys.platform != "win32",
        )
        group = _ProcessGroup(proc)
        try:
            out, _ = proc.communicate(timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            group.kill()
            out, _ = proc.communicate()
            code = None
        finally:
            group.close()
        return ExecResult(code, _tail(out.decode("utf-8", errors="replace")), time.monotonic() - start)

    def put(self, src, dest):
        target = Path(dest)
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)

    def close(self):
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)


class DockerSandbox(Sandbox):
    """One container per trial: no network, capped memory, CPU and process count."""

    def __init__(self, environment: Path | None = None, image: str = "agentbench-base:latest",
                 network: bool = False, memory: str = "2g", cpus: str = "2"):
        self.name = f"abench-{uuid.uuid4().hex[:12]}"
        self.workspace, self.private, self.python = "/workspace", "/opt/abench", "python3"
        cmd = ["docker", "run", "-d", "--name", self.name, "--memory", memory, "--cpus", cpus,
               "--pids-limit", "512", "-w", self.workspace]
        if not network:
            cmd += ["--network", "none"]
        subprocess.run(cmd + [image, "sleep", "infinity"], check=True, capture_output=True)
        subprocess.run(["docker", "exec", self.name, "mkdir", "-p", self.workspace, self.private], check=True,
                       capture_output=True)
        if environment is not None and environment.is_dir():
            self.put(environment, self.workspace)

    def exec(self, command, timeout, env=None, cwd=None):
        args = ["docker", "exec", "-w", cwd or self.workspace, "-e", f"WORKSPACE={self.workspace}", "-e", "PYTHON=python3"]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        # `timeout` inside the container kills the command itself, not just the docker client
        args += [self.name, "timeout", "-s", "KILL", str(int(timeout) + 1), "bash", "-c", command]
        start = time.monotonic()
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout + 15)
            code = None if p.returncode in (124, 137) else p.returncode
            out = p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            code, out = None, (e.stdout or b"")
        return ExecResult(code, _tail(out.decode("utf-8", errors="replace")), time.monotonic() - start)

    def put(self, src, dest):
        # "src/." copies the directory's contents rather than the directory itself
        source = f"{src}/." if src.is_dir() else str(src)
        subprocess.run(["docker", "exec", self.name, "mkdir", "-p", dest if src.is_dir() else str(Path(dest).parent)],
                       check=True, capture_output=True)
        subprocess.run(["docker", "cp", source, f"{self.name}:{dest}"], check=True, capture_output=True)

    def close(self):
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
