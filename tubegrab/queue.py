"""Sequential download queue, independent of Tkinter."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from .downloader import (
    DownloadCancelled,
    DownloadError,
    DownloadResult,
    MediaInfo,
    ProcessHandle,
    ProgressUpdate,
)
from .utils import validate_url

LOGGER = logging.getLogger("tubegrab.queue")


class JobStatus(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


ACTIVE_STATUSES = {JobStatus.FETCHING, JobStatus.DOWNLOADING}
FINISHED_STATUSES = {JobStatus.COMPLETED, JobStatus.CANCELLED}


class DownloadService(Protocol):
    def fetch_info(self, url: str, handle: ProcessHandle) -> MediaInfo: ...

    def download(
        self,
        url: str,
        mode: str,
        quality: int | None,
        output_dir: Path,
        handle: ProcessHandle,
        on_progress: Callable[[ProgressUpdate], None] | None = None,
        restart: bool = False,
    ) -> DownloadResult: ...


@dataclass
class DownloadJob:
    id: str
    url: str
    mode: str
    quality: int | None
    output_dir: Path
    status: JobStatus = JobStatus.QUEUED
    title: str | None = None
    info: MediaInfo | None = None
    progress: float | None = None
    phase: str = ""
    speed: float | None = None
    eta: float | None = None
    indeterminate: bool = False
    message: str = ""
    final_path: Path | None = None
    already_exists: bool = False
    cancelling: bool = False
    restart: bool = False

    @property
    def display_title(self) -> str:
        return self.title or (self.info.display_title if self.info else "") or self.url

    @property
    def duplicate_key(self) -> tuple[str, str, int | None, str]:
        return (self.url, self.mode, self.quality, str(self.output_dir))


class QueueManager:
    """Own a FIFO worker thread and a thread-safe list of jobs.

    The UI only reads :meth:`snapshot` and calls the public commands.  All
    mutations that matter happen under ``self._lock``; the callback merely tells
    the Tk event pump that something changed.
    """

    def __init__(
        self,
        downloader: DownloadService,
        on_change: Callable[[], None],
        logger: logging.Logger | None = None,
    ) -> None:
        self.downloader = downloader
        self.on_change = on_change
        self.logger = logger or LOGGER
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._jobs: list[DownloadJob] = []
        self._active_id: str | None = None
        self._active_handle: ProcessHandle | None = None
        self._worker: threading.Thread | None = None
        self._stop = False

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop = False
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="tubegrab-queue",
                daemon=True,
            )
            self._worker.start()

    def add(
        self,
        url: str,
        mode: str,
        quality: int | None,
        output_dir: Path,
        info: MediaInfo | None = None,
    ) -> tuple[str, bool]:
        validated = validate_url(url)
        if mode not in {"video", "audio", "mp3"}:
            raise ValueError(f"Unknown mode: {mode}")
        output = Path(output_dir)
        key = (validated, mode, quality, str(output))

        with self._condition:
            for job in self._jobs:
                if job.status in {JobStatus.QUEUED, *ACTIVE_STATUSES} and job.duplicate_key == key:
                    return job.id, False
            job = DownloadJob(
                id=uuid.uuid4().hex[:10],
                url=validated,
                mode=mode,
                quality=quality,
                output_dir=output,
                title=info.title if info else None,
                info=info if info and info.url == validated else None,
            )
            self._jobs.append(job)
            self._condition.notify_all()
        self.logger.info("Queued %s (%s, quality=%s)", validated, mode, quality or "best")
        self._changed()
        return job.id, True

    def snapshot(self) -> list[DownloadJob]:
        with self._lock:
            return [replace(job) for job in self._jobs]

    def active_job(self) -> DownloadJob | None:
        with self._lock:
            if self._active_id is None:
                return None
            for job in self._jobs:
                if job.id == self._active_id:
                    return replace(job)
            return None

    def cancel_active(self) -> bool:
        with self._lock:
            job = next((item for item in self._jobs if item.id == self._active_id), None)
            if job is None or job.status not in ACTIVE_STATUSES:
                return False
            job.cancelling = True
            job.phase = "Cancelling…"
            handle = self._active_handle
        if handle is not None:
            handle.cancel()
        self.logger.info("Cancellation requested for job %s", job.id)
        self._changed()
        return True

    def retry(self, job_id: str, restart: bool = False) -> bool:
        with self._condition:
            job = next((item for item in self._jobs if item.id == job_id), None)
            if job is None or job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                return False
            job.status = JobStatus.QUEUED
            job.progress = None
            job.phase = ""
            job.speed = None
            job.eta = None
            job.indeterminate = False
            job.message = ""
            job.final_path = None
            job.already_exists = False
            job.cancelling = False
            job.restart = restart
            self._condition.notify_all()
        self.logger.info("Retrying job %s (restart=%s)", job_id, restart)
        self._changed()
        return True

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = next((item for item in self._jobs if item.id == job_id), None)
            if job is None or job.status in ACTIVE_STATUSES:
                return False
            self._jobs = [item for item in self._jobs if item.id != job_id]
        self.logger.info("Removed job %s", job_id)
        self._changed()
        return True

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self._jobs)
            self._jobs = [job for job in self._jobs if job.status not in FINISHED_STATUSES]
            removed = before - len(self._jobs)
        if removed:
            self.logger.info("Cleared %s finished job(s)", removed)
            self._changed()
        return removed

    def shutdown(self, timeout: float = 6.0) -> None:
        with self._lock:
            self._stop = True
            handle = self._active_handle
            self._condition.notify_all()
        if handle is not None:
            handle.cancel()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
            if worker.is_alive():
                self.logger.warning("Queue worker did not stop within %.1fs", timeout)

    def _changed(self) -> None:
        try:
            self.on_change()
        except Exception:
            self.logger.exception("Queue change callback failed")

    def _next_queued_locked(self) -> DownloadJob | None:
        return next((job for job in self._jobs if job.status == JobStatus.QUEUED), None)

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                job = self._next_queued_locked()
                while job is None and not self._stop:
                    self._condition.wait(timeout=0.5)
                    job = self._next_queued_locked()
                if self._stop:
                    return
                assert job is not None
                self._active_id = job.id
                self._active_handle = ProcessHandle()
                handle = self._active_handle
                job.cancelling = False
                job.progress = None
                job.indeterminate = False
                job.phase = "Fetching information…" if job.info is None else "Starting…"
                job.message = ""
                job.status = JobStatus.FETCHING if job.info is None else JobStatus.DOWNLOADING
            self._changed()

            try:
                if job.info is None:
                    info = self.downloader.fetch_info(job.url, handle)
                    with self._lock:
                        job.info = info
                        job.title = info.title
                        job.status = JobStatus.DOWNLOADING
                        job.phase = "Starting download…"
                    self._changed()

                last_emit = 0.0

                def on_progress(update: ProgressUpdate) -> None:
                    nonlocal last_emit
                    with self._lock:
                        job.progress = update.percent
                        job.phase = update.phase
                        job.speed = update.speed
                        job.eta = update.eta
                        job.indeterminate = update.indeterminate
                        now = time.monotonic()
                        should_emit = now - last_emit >= 0.12
                        if should_emit:
                            last_emit = now
                    if should_emit:
                        self._changed()

                result = self.downloader.download(
                    job.url,
                    job.mode,
                    job.quality,
                    job.output_dir,
                    handle,
                    on_progress,
                    restart=job.restart,
                )
                with self._lock:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.phase = ""
                    job.speed = None
                    job.eta = None
                    job.indeterminate = False
                    job.message = result.message
                    job.final_path = result.final_path
                    job.already_exists = result.already_exists
                    job.cancelling = False
                self.logger.info("Job %s completed: %s", job.id, result.message)
            except DownloadCancelled:
                with self._lock:
                    job.status = JobStatus.CANCELLED
                    job.message = "Cancelled."
                    job.phase = ""
                    job.speed = None
                    job.eta = None
                    job.indeterminate = False
                    job.cancelling = False
                self.logger.info("Job %s cancelled", job.id)
            except DownloadError as exc:
                with self._lock:
                    job.status = JobStatus.FAILED
                    job.message = exc.user_message
                    job.phase = ""
                    job.speed = None
                    job.eta = None
                    job.indeterminate = False
                    job.cancelling = False
                self.logger.error("Job %s failed: %s", job.id, exc.user_message)
                if exc.detail:
                    self.logger.debug("Failure details for %s:\n%s", job.id, exc.detail)
            except Exception as exc:  # keep the queue alive for unexpected failures
                with self._lock:
                    job.status = JobStatus.FAILED
                    job.message = "An unexpected error occurred. See Details for the diagnostic log."
                    job.phase = ""
                    job.speed = None
                    job.eta = None
                    job.indeterminate = False
                    job.cancelling = False
                self.logger.exception("Unexpected failure in job %s", job.id)
            finally:
                with self._lock:
                    if self._active_id == job.id:
                        self._active_id = None
                    self._active_handle = None
                self._changed()
