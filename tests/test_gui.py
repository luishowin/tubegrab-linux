"""Lightweight GUI smoke test (skipped when no display is available)."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path

from tubegrab.config import AppPaths
from tubegrab.downloader import (
    DependencyStatus,
    DownloadCancelled,
    DownloadError,
    DownloadResult,
    MediaInfo,
    ProgressUpdate,
)
from tubegrab.logging_setup import configure_logging


def _has_display() -> bool:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


class SlowFakeService:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.preview_delay = 0.0
        self.fail_next = False
        self.download_calls = 0

    def fetch_info(self, url: str, handle: object) -> MediaInfo:
        deadline = time.monotonic() + self.preview_delay
        while time.monotonic() < deadline:
            if getattr(handle, "cancelled", False):
                raise DownloadCancelled()
            time.sleep(0.01)
        return MediaInfo(url=url, title="GUI test video")

    def download(
        self,
        url,
        mode,
        quality,
        output_dir,
        handle,
        on_progress=None,
        restart=False,
    ) -> DownloadResult:
        self.download_calls += 1
        if self.fail_next:
            self.fail_next = False
            raise DownloadError("Simulated failure for the retry test.")
        if on_progress is not None:
            on_progress(ProgressUpdate(42.0, "Video · 720p"))
        while not self.release.wait(0.01):
            if getattr(handle, "cancelled", False):
                raise DownloadCancelled()
        if getattr(handle, "cancelled", False):
            raise DownloadCancelled()
        return DownloadResult(Path("/tmp/gui-test.mkv"))


@unittest.skipUnless(_has_display(), "no graphical display available")
class GuiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(
            config_dir=Path(self.temp.name) / "config",
            state_dir=Path(self.temp.name) / "state",
            cache_dir=Path(self.temp.name) / "cache",
        )
        self.log_state = configure_logging(self.paths)
        self.root = tk.Tk(className="TubeGrabTest")
        self.root.withdraw()
        self.addCleanup(self._destroy_root)
        self.service = SlowFakeService()
        deps = DependencyStatus(
            ytdlp_command=["yt-dlp"],
            ffmpeg="/usr/bin/ffmpeg",
            ffprobe="/usr/bin/ffprobe",
            ytdlp_version="test",
        )
        from tubegrab.app import TubeGrabApp

        self.app = TubeGrabApp(
            self.root,
            self.paths,
            self.log_state.logger,
            self.log_state,
            dependencies=deps,
            downloader=self.service,
        )
        self.root.update()

    def tearDown(self) -> None:
        try:
            self.app.request_close(confirm=False)
        except tk.TclError:
            pass
        self.service.release.set()

    def _destroy_root(self) -> None:
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass

    def test_starts_with_disabled_download_and_enables_on_url(self) -> None:
        self.assertEqual(str(self.app.download_button.cget("state")), "disabled")
        self.app.url_var.set("https://example.com/watch?v=abc")
        self.root.update()
        self.assertEqual(str(self.app.download_button.cget("state")), "normal")
        self.app.folder_var.set(self.temp.name)
        self.root.update()
        self.assertEqual(str(self.app.open_folder_button.cget("state")), "normal")

    def test_queue_row_appears_and_cancel_stops_it(self) -> None:
        self.app.url_var.set("https://example.com/watch?v=abc")
        self.app.folder_var.set(self.temp.name)
        self.root.update()
        self.app._add_download()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self.app.queue_view.rows:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(len(self.app.queue_view.rows), 1)
        self.assertEqual(len(self.app.queue_manager.snapshot()), 1)
        self.app._cancel_active()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            jobs = self.app.queue_manager.snapshot()
            if jobs and jobs[0].status.value == "cancelled":
                break
            time.sleep(0.01)
        self.assertEqual(self.app.queue_manager.snapshot()[0].status.value, "cancelled")

    def test_details_window_and_input_error(self) -> None:
        self.app._show_details()
        self.root.update()
        self.assertIsNotNone(self.app._log_window)
        self.app._close_details()
        self.root.update()
        self.assertIsNone(self.app._log_window)
        self.app._show_input_error("A friendly error")
        self.root.update()
        self.assertEqual(self.app.input_error_var.get(), "A friendly error")

    def test_retry_button_requeues_failed_item(self) -> None:
        self.app.url_var.set("https://example.com/watch?v=retry")
        self.app.folder_var.set(self.temp.name)
        self.root.update()
        self.service.fail_next = True
        self.app._add_download()
        deadline = time.monotonic() + 3
        job = None
        while time.monotonic() < deadline:
            self.root.update()
            jobs = self.app.queue_manager.snapshot()
            if jobs and jobs[0].status.value == "failed":
                job = jobs[0]
                break
            time.sleep(0.01)
        self.assertIsNotNone(job)
        assert job is not None
        self.service.release.set()
        self.app._retry_job(job.id)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            jobs = self.app.queue_manager.snapshot()
            if jobs and jobs[0].status.value == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(self.app.queue_manager.snapshot()[0].status.value, "completed")
        self.assertEqual(self.service.download_calls, 2)

    def test_event_loop_stays_responsive_while_preview_runs(self) -> None:
        self.service.preview_delay = 0.6
        self.app.url_var.set("https://example.com/watch?v=abc")
        self.root.update()
        ticks = {"count": 0}

        def tick() -> None:
            ticks["count"] += 1
            if self.app.preview_handle is not None:
                self.root.after(20, tick)

        self.root.after(20, tick)
        self.app._start_preview()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and self.app.preview_info is None:
            self.root.update()
            time.sleep(0.01)
        self.assertGreater(ticks["count"], 5)
        self.assertIsNotNone(self.app.preview_info)
        self.assertEqual(self.app.preview_info.title, "GUI test video")


if __name__ == "__main__":
    unittest.main()
