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
        container="auto",
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

    def test_input_error_is_shown(self) -> None:
        self.app._show_input_error("A friendly error")
        self.root.update()
        self.assertEqual(self.app.input_error_var.get(), "A friendly error")

    def test_page_margins_stay_fixed_when_resizing(self) -> None:
        self.root.deiconify()
        for geometry, expected_width in (("900x620", 900), ("1500x900", 1500)):
            self.root.geometry(geometry)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                self.root.update()
                if self.app.page.canvas.winfo_width() == expected_width:
                    break
                time.sleep(0.01)
            self.root.update_idletasks()
            self.assertEqual(self.app.page.canvas.winfo_width(), expected_width)
            self.assertEqual(self.app.page.canvas.canvasx(0), 0.0)
            self.assertEqual(self.app.page.canvas.canvasy(0), 0.0)
            self.assertEqual(self.app.page.inner.winfo_x(), 24)
            self.assertEqual(self.app.page.inner.winfo_y(), 24)

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

    def test_card_grows_and_shrinks_with_body_content(self) -> None:
        from tubegrab.widgets import Card

        window = tk.Toplevel(self.root)
        window.geometry("600x400")
        card = Card(window, padding=(2, 2))
        card.pack(fill="x")
        label = tk.Label(card.body, text="one line")
        label.pack()

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and card.winfo_height() < 20:
            window.update()
            time.sleep(0.01)
        short = card.winfo_height()
        self.assertGreater(short, 20)

        label.configure(text="\n".join(["line"] * 8))
        tall = short
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            window.update()
            tall = card.winfo_height()
            if tall > short + 40:
                break
            time.sleep(0.01)
        self.assertGreater(tall, short + 40)

        label.configure(text="one line")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            window.update()
            if card.winfo_height() < tall:
                break
            time.sleep(0.01)
        self.assertLess(card.winfo_height(), tall)

    def test_queue_row_text_fits_inside_card(self) -> None:
        from tubegrab.queue import DownloadJob, JobStatus

        self.root.deiconify()
        self.root.update()
        job = DownloadJob(
            id="long-title",
            url="https://example.com/watch?v=long",
            mode="video",
            quality=1080,
            output_dir=Path(self.temp.name),
            status=JobStatus.DOWNLOADING,
            title="【源兵衛川】水の都で過ごす一日。川の上をせせらぎとともに歩く癒しの時間。" * 2,
            progress=9.0,
            speed=13.5 * 1024 * 1024,
            eta=103.0,
            phase="Video · 1080p",
        )
        self.app.queue_view.sync([job])
        row = self.app.queue_view.rows["long-title"]
        card = self.app.queue_card
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.root.update()
            if (
                row.title_label.winfo_width() <= row.meta.winfo_width()
                and card.winfo_height() >= card.body.winfo_reqheight() + 4
            ):
                break
            time.sleep(0.01)

        card_bottom = card.winfo_rooty() + card.winfo_height()
        status_bottom = row.status_label.winfo_rooty() + row.status_label.winfo_height()
        self.assertLessEqual(status_bottom, card_bottom)
        self.assertLessEqual(row.title_label.winfo_width(), row.meta.winfo_width() + 2)

    def test_queue_thumbnail_is_not_cropped(self) -> None:
        from tubegrab.app import QueueRow

        def noop(*_args: object) -> None:
            return

        image = tk.PhotoImage(width=480, height=270)
        parent = tk.Frame(self.root)
        row = QueueRow(parent, noop, noop, noop, noop, noop)
        row.set_thumbnail(image)
        self.assertIsNotNone(row._thumb_photo)
        assert row._thumb_photo is not None
        self.assertLessEqual(row._thumb_photo.width(), 76)
        self.assertLessEqual(row._thumb_photo.height(), 43)

    def test_quality_slider_and_container_controls(self) -> None:
        from tubegrab.app import QUALITY_OPTIONS

        self.root.deiconify()
        self.root.update()
        labels = [label for _value, label in self.app.quality_slider._segments]
        self.assertEqual(labels, [label for label, _value in QUALITY_OPTIONS])
        self.app.quality_var.set("720p")
        self.root.update()
        self.assertTrue(self.app.quality_slider.grid_info())
        self.assertTrue(self.app.container_row.grid_info())
        self.assertEqual(self.app.container_var.get(), "auto")

        self.app.mode_var.set("audio")
        self.root.update()
        self.assertFalse(self.app.quality_slider.grid_info())
        self.assertFalse(self.app.container_row.grid_info())

        self.app.mode_var.set("video")
        self.root.update()
        self.assertTrue(self.app.quality_slider.grid_info())
        self.assertTrue(self.app.container_row.grid_info())

    def test_preview_lists_codecs_and_containers(self) -> None:
        url = "https://example.com/watch?v=codec"
        self.app.url_var.set(url)
        self.root.update()
        info = MediaInfo(
            url=url,
            title="Codec test",
            heights=[1080, 720],
            video_codecs=["AV1", "VP9", "H.264"],
            containers=["MP4", "WebM"],
        )
        self.app._handle_preview_info(self.app.preview_generation, info)
        self.root.update()
        self.assertIn("AV1", self.app.preview_codec_var.get())
        self.assertIn("H.264", self.app.preview_codec_var.get())
        self.assertIn("MP4", self.app.preview_container_var.get())
        self.assertIn("WebM", self.app.preview_container_var.get())

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
