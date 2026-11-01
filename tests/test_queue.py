"""Queue state-machine tests using a deterministic fake downloader."""

from __future__ import annotations

import queue
import tempfile
import threading
import time
import unittest
from collections import Counter
from pathlib import Path

from tubegrab.downloader import (
    DownloadCancelled,
    DownloadError,
    DownloadResult,
    MediaInfo,
    ProgressUpdate,
)
from tubegrab.queue import JobStatus, QueueManager
from tubegrab.utils import ValidationError


def wait_for(predicate, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeService:
    def __init__(self) -> None:
        self.started: queue.Queue[str] = queue.Queue()
        self.gates: dict[str, threading.Event] = {}
        self.fetch_gate: threading.Event | None = None
        self.fail_urls: set[str] = set()
        self.starts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def gate(self, url: str) -> threading.Event:
        gate = threading.Event()
        self.gates[url] = gate
        return gate

    def fetch_info(self, url: str, handle: object) -> MediaInfo:
        if self.fetch_gate is not None:
            while not self.fetch_gate.wait(0.01):
                if getattr(handle, "cancelled", False):
                    raise DownloadCancelled()
        return MediaInfo(url=url, title=f"Title for {url}")

    def download(self, url, mode, quality, output_dir, handle, on_progress=None) -> DownloadResult:
        with self._lock:
            self.starts[url] += 1
        self.started.put(url)
        if on_progress is not None:
            on_progress(ProgressUpdate(percent=50.0, phase="Video · 720p"))
        gate = self.gates.get(url)
        if gate is not None:
            while not gate.wait(0.01):
                if getattr(handle, "cancelled", False):
                    raise DownloadCancelled()
        if getattr(handle, "cancelled", False):
            raise DownloadCancelled()
        if url in self.fail_urls:
            raise DownloadError("Simulated failure for testing.")
        if on_progress is not None:
            on_progress(ProgressUpdate(percent=100.0, phase="Video · 720p"))
        return DownloadResult(Path("/tmp/fake-output.mkv"))


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.service = FakeService()
        self.changes = 0

        def changed() -> None:
            self.changes += 1

        self.manager = QueueManager(self.service, changed)
        self.manager.start()
        self.addCleanup(self.manager.shutdown, 2.0)

    def add(self, url: str, mode: str = "video", quality: int | None = 1080):
        return self.manager.add(url, mode, quality, self.output)

    def status(self, job_id: str) -> JobStatus | None:
        job = next((item for item in self.manager.snapshot() if item.id == job_id), None)
        return job.status if job else None

    def test_processes_sequentially_and_accepts_new_items_while_running(self) -> None:
        first = "https://example.com/one"
        second = "https://example.com/two"
        gate = self.service.gate(first)
        first_id, added = self.add(first)
        self.assertTrue(added)
        self.assertEqual(self.service.started.get(timeout=2), first)

        second_id, added = self.add(second)
        self.assertTrue(added)
        time.sleep(0.15)
        self.assertEqual(self.status(second_id), JobStatus.QUEUED)
        self.assertTrue(self.service.started.empty())

        gate.set()
        self.assertEqual(self.service.started.get(timeout=2), second)
        self.assertTrue(wait_for(lambda: self.status(first_id) == JobStatus.COMPLETED))
        self.assertTrue(wait_for(lambda: self.status(second_id) == JobStatus.COMPLETED))

    def test_failure_does_not_stop_the_queue(self) -> None:
        failing = "https://example.com/fail"
        following = "https://example.com/after"
        self.service.fail_urls.add(failing)
        fail_id, _ = self.add(failing)
        next_id, _ = self.add(following)
        self.assertTrue(wait_for(lambda: self.status(fail_id) == JobStatus.FAILED))
        self.assertTrue(wait_for(lambda: self.status(next_id) == JobStatus.COMPLETED))
        failed = next(item for item in self.manager.snapshot() if item.id == fail_id)
        self.assertIn("Simulated failure", failed.message)

    def test_cancel_active_moves_to_next_item(self) -> None:
        first = "https://example.com/cancel"
        second = "https://example.com/next"
        gate = self.service.gate(first)
        first_id, _ = self.add(first)
        second_id, _ = self.add(second)
        self.assertEqual(self.service.started.get(timeout=2), first)

        self.assertTrue(self.manager.cancel_active())
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(first_id) == JobStatus.CANCELLED))
        self.assertEqual(self.service.started.get(timeout=2), second)
        self.assertTrue(wait_for(lambda: self.status(second_id) == JobStatus.COMPLETED))

    def test_retry_after_failure(self) -> None:
        url = "https://example.com/retry"
        self.service.fail_urls.add(url)
        job_id, _ = self.add(url)
        self.assertTrue(wait_for(lambda: self.status(job_id) == JobStatus.FAILED))
        self.service.fail_urls.remove(url)
        self.assertTrue(self.manager.retry(job_id))
        self.assertTrue(
            wait_for(
                lambda: self.status(job_id) == JobStatus.COMPLETED
                and self.service.starts[url] == 2
            )
        )

    def test_remove_queued_item(self) -> None:
        active = "https://example.com/active"
        queued = "https://example.com/queued"
        gate = self.service.gate(active)
        active_id, _ = self.add(active)
        queued_id, _ = self.add(queued)
        self.assertEqual(self.service.started.get(timeout=2), active)
        self.assertTrue(self.manager.remove(queued_id))
        self.assertFalse(self.manager.remove(active_id))
        self.assertNotIn(queued_id, [job.id for job in self.manager.snapshot()])
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(active_id) == JobStatus.COMPLETED))

    def test_duplicate_active_entry_is_rejected(self) -> None:
        url = "https://example.com/duplicate"
        gate = self.service.gate(url)
        first_id, added = self.add(url)
        self.assertTrue(added)
        second_id, added_again = self.add(url)
        self.assertFalse(added_again)
        self.assertEqual(first_id, second_id)
        self.assertEqual(len(self.manager.snapshot()), 1)
        self.assertEqual(self.service.started.get(timeout=2), url)
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(first_id) == JobStatus.COMPLETED))

    def test_no_duplicate_execution_for_one_item(self) -> None:
        url = "https://example.com/once"
        gate = self.service.gate(url)
        job_id, _ = self.add(url)
        self.assertEqual(self.service.started.get(timeout=2), url)
        self.assertTrue(wait_for(lambda: self.status(job_id) == JobStatus.DOWNLOADING))
        time.sleep(0.1)
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(job_id) == JobStatus.COMPLETED))
        time.sleep(0.1)
        self.assertEqual(self.service.starts[url], 1)

    def test_progress_and_metadata_are_visible(self) -> None:
        url = "https://example.com/progress"
        gate = self.service.gate(url)
        job_id, _ = self.add(url)
        self.assertEqual(self.service.started.get(timeout=2), url)
        self.assertTrue(
            wait_for(
                lambda: any(
                    job.id == job_id
                    and job.status == JobStatus.DOWNLOADING
                    and job.progress == 50.0
                    for job in self.manager.snapshot()
                )
            )
        )
        job = next(item for item in self.manager.snapshot() if item.id == job_id)
        self.assertIn("Title for", job.display_title)
        gate.set()
        self.assertTrue(wait_for(lambda: self.status(job_id) == JobStatus.COMPLETED))

    def test_fetching_state_and_clear_finished(self) -> None:
        url = "https://example.com/fetch"
        self.service.fetch_gate = threading.Event()
        job_id, _ = self.add(url)
        self.assertTrue(wait_for(lambda: self.status(job_id) == JobStatus.FETCHING))
        self.service.fetch_gate.set()
        self.assertEqual(self.service.started.get(timeout=2), url)
        self.assertTrue(wait_for(lambda: self.status(job_id) == JobStatus.COMPLETED))
        self.assertEqual(self.manager.clear_finished(), 1)
        self.assertEqual(self.manager.snapshot(), [])

    def test_shutdown_cancels_active_work(self) -> None:
        url = "https://example.com/shutdown"
        gate = self.service.gate(url)
        job_id, _ = self.add(url)
        self.assertEqual(self.service.started.get(timeout=2), url)
        self.manager.shutdown(timeout=2.0)
        self.assertEqual(self.status(job_id), JobStatus.CANCELLED)
        gate.set()

    def test_invalid_add_raises(self) -> None:
        with self.assertRaises(ValidationError):
            self.manager.add("not a url", "video", None, self.output)


if __name__ == "__main__":
    unittest.main()
