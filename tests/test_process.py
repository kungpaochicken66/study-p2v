import os
import sys
import time
from pathlib import Path

import pytest

from study_p2v.errors import RenderError
from study_p2v.process import run


def test_error_has_no_child_output_or_argument_content(tmp_path):
    with pytest.raises(RenderError) as caught:
        run(
            [sys.executable, "-c", "import sys;print('private-input');sys.exit(3)"],
            cwd=tmp_path,
            timeout=2,
        )
    assert str(caught.value) == "process_failed"


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_or_cancel_terminates_parent_and_descendant(tmp_path, cancel):
    pidfile = tmp_path / "child.pid"
    child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    parent = (
        "import subprocess,sys,time,pathlib;"
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]);"
        f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(30)"
    )
    started = time.monotonic()
    with pytest.raises(RenderError) as caught:
        run(
            [sys.executable, "-c", parent],
            cwd=tmp_path,
            timeout=0.7 if not cancel else 5,
            cancel=lambda: cancel and time.monotonic() - started > 0.7,
        )
    assert caught.value.code == ("cancelled" if cancel else "deadline_exceeded")
    assert time.monotonic() - started < 4
    child_pid = int(pidfile.read_text())
    for _ in range(40):
        status = Path(f"/proc/{child_pid}/status")
        if not status.exists() or "State:\tZ" in status.read_text():
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, 9)
        pytest.fail("render subprocess descendant survived cancellation")
