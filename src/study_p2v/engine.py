from __future__ import annotations

import fcntl
import threading
import time

from .config import Settings
from .errors import RenderError
from .renderer import Renderer
from .storage import DiskStorage
from .store import Store


class Engine:
    def __init__(self, settings: Settings, renderer_factory=Renderer):
        self.settings = settings
        self.storage = DiskStorage(settings.data_dir)
        self.store = Store(settings.data_dir / "jobs.sqlite3")
        self.renderer = renderer_factory(settings, self.storage, self.store)
        self.stopping = threading.Event()
        self.wakeup = threading.Event()
        self.threads: list[threading.Thread] = []
        self.lock = None
        self.ready = False

    def start(self):
        self.lock = (self.settings.data_dir / "engine.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            raise RenderError("another_engine_owns_data_dir") from None
        try:
            self.renderer.prepare()
            self.store.recover()
            for i in range(self.settings.workers):
                thread = threading.Thread(target=self._worker, name=f"p2v-worker-{i}", daemon=True)
                thread.start()
                self.threads.append(thread)
            self.ready = True
        except BaseException:
            self.close()
            raise

    def close(self):
        self.ready = False
        self.stopping.set()
        self.wakeup.set()
        for thread in self.threads:
            thread.join(timeout=15)
        if any(t.is_alive() for t in self.threads):
            # Do not release ownership while workers might still publish or update the DB.
            raise RenderError("worker_shutdown_incomplete")
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    def _worker(self):
        while not self.stopping.is_set():
            job = self.store.claim(self.settings.per_namespace)
            if not job:
                self.wakeup.wait(0.2)
                self.wakeup.clear()
                continue

            def cancel():
                return self.stopping.is_set() or self.store.cancelled(job["namespace"], job["id"])

            queued_seconds = max(0, time.time() - job["created"])
            try:
                result, metrics = self.renderer.render(job, cancel)
                if cancel():
                    raise RenderError("cancelled")
                # Re-read the destination, not the scratch file, before committing success.
                self.storage.verify(job["namespace"], job["id"], result)
                metrics["queue_seconds"] = round(queued_seconds, 3)
                self.store.finish(job["id"], result=result, metrics=metrics)
            except RenderError as exc:
                error = "interrupted" if self.stopping.is_set() else exc.code
                self.store.finish(job["id"], error=error)
            except Exception:
                self.store.finish(job["id"], error="internal_render_error")
            finally:
                self.wakeup.set()
