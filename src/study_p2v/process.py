from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import psutil

from .errors import RenderError

CancelCheck = Callable[[], bool]
_MEASUREMENTS: ContextVar[dict | None] = ContextVar("process_measurements", default=None)


@contextmanager
def measurements(stats: dict):
    token = _MEASUREMENTS.set(stats)
    try:
        yield
    finally:
        _MEASUREMENTS.reset(token)


def sample_tree(pid: int, observed: dict):
    total_rss, count = 0, 0
    try:
        parent = psutil.Process(pid)
        processes = [parent, *parent.children(recursive=True)]
    except psutil.Error:
        return 0, 0
    for process in processes:
        try:
            key = (process.pid, process.create_time())
            cpu = process.cpu_times()
            observed[key] = max(observed.get(key, 0), cpu.user + cpu.system)
            total_rss += process.memory_info().rss
            count += 1
        except psutil.Error:
            continue
    return total_rss, count


def stop_group(process: subprocess.Popen) -> None:
    """Kill the entire process group, including helpers that outlive their parent."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    # A parent can exit while a child ignores SIGTERM. Kill the group even if parent exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    cancel: CancelCheck = lambda: False,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
    error_code: str = "process_failed",
) -> bytes:
    if cancel():
        raise RenderError("cancelled")
    if timeout <= 0:
        raise RenderError("deadline_exceeded")
    if env is None:
        allowed = {
            "PATH",
            "LANG",
            "LC_ALL",
            "LD_LIBRARY_PATH",
            "FONTCONFIG_FILE",
            "FONTCONFIG_PATH",
            "XDG_CACHE_HOME",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
    # No pipe deadlocks and no raw subprocess diagnostics in public errors.
    with tempfile.TemporaryFile(dir=cwd) as output:
        try:
            p = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            raise RenderError("executable_unavailable") from None
        deadline = time.monotonic() + timeout
        stats, observed = _MEASUREMENTS.get(), {}
        if stats is not None:
            stats["process_calls"] = stats.get("process_calls", 0) + 1
        try:
            while True:
                if stats is not None:
                    rss, count = sample_tree(p.pid, observed)
                    stats["process_peak_rss_bytes"] = max(
                        stats.get("process_peak_rss_bytes", 0), rss
                    )
                    stats["process_peak_count"] = max(stats.get("process_peak_count", 0), count)
                if p.poll() is not None:
                    break
                if cancel():
                    raise RenderError("cancelled")
                if time.monotonic() >= deadline:
                    raise RenderError("deadline_exceeded")
                if output.tell() > 1024 * 1024:
                    raise RenderError("process_output_too_large")
                time.sleep(0.05)
            if cancel():
                raise RenderError("cancelled")
            if p.returncode != 0:
                raise RenderError(error_code)
            if capture:
                output.seek(0)
                value = output.read(1024 * 1024 + 1)
                if len(value) > 1024 * 1024:
                    raise RenderError("process_output_too_large")
                return value
            return b""
        except BaseException:
            stop_group(p)
            raise
        finally:
            if stats is not None:
                stats["cpu_seconds_sampled"] = stats.get("cpu_seconds_sampled", 0) + sum(
                    observed.values()
                )
