"""Tkinter interface for TubeGrab."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import APP_NAME, __version__
from .config import (
    MIN_HEIGHT,
    MIN_WIDTH,
    AppPaths,
    Config,
    load_config,
    save_config,
)
from .downloader import (
    DependencyStatus,
    DownloadCancelled,
    DownloadError,
    MediaInfo,
    ProcessHandle,
    YtDlpDownloader,
    detect_dependencies,
    fetch_thumbnail,
    mode_requires_ffmpeg,
)
from .logging_setup import LoggingState
from .queue import ACTIVE_STATUSES, JobStatus, QueueManager, DownloadJob
from .theme import (
    BG,
    FAINT,
    INSET,
    THUMB_BG,
    apply_theme,
)
from .utils import (
    ValidationError,
    folder_is_usable,
    format_duration,
    format_speed,
    open_path,
    truncate_text,
    validate_url,
)

LOGGER = logging.getLogger("tubegrab.app")

QUALITY_OPTIONS: tuple[tuple[str, int | None], ...] = (
    ("Best available", None),
    ("2160p (4K)", 2160),
    ("1440p", 1440),
    ("1080p", 1080),
    ("720p", 720),
    ("480p", 480),
    ("360p", 360),
    ("240p", 240),
    ("144p", 144),
)
QUALITY_LABEL_TO_VALUE = dict(QUALITY_OPTIONS)
QUALITY_VALUE_TO_LABEL = {value: label for label, value in QUALITY_OPTIONS}


def _quality_label(quality: int | None) -> str:
    if quality is None:
        return "Best available"
    return f"{quality}p"


def _mode_description(job: DownloadJob) -> str:
    if job.mode == "video":
        return f"Video · {_quality_label(job.quality)}"
    if job.mode == "mp3":
        return "Audio · MP3 V0"
    return "Audio · original"


class QueueRow:
    """One queue entry, updated in place so progress doesn't flicker."""

    def __init__(
        self,
        parent: tk.Widget,
        on_cancel: Any,
        on_retry: Any,
        on_remove: Any,
        on_open: Any,
    ) -> None:
        self.frame = ttk.Frame(parent, style="Queue.TFrame", padding=(12, 9))
        self.frame.columnconfigure(0, weight=1)

        left = ttk.Frame(self.frame, style="Queue.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(left, text="", style="QueueTitle.TLabel", anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.meta_label = ttk.Label(left, text="", style="QueueMuted.TLabel", anchor="w")
        self.meta_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.message_label = ttk.Label(
            left,
            text="",
            style="QueueError.TLabel",
            anchor="w",
            justify="left",
            wraplength=620,
        )
        self.message_label.grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.message_label.grid_remove()
        self.bar = ttk.Progressbar(
            left,
            style="Queue.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
        )
        self.bar.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self.bar.grid_remove()
        self._bar_mode: str | None = None
        self._bar_visible_applied: bool | None = None

        actions = ttk.Frame(self.frame, style="Queue.TFrame")
        actions.grid(row=0, column=1, sticky="ne", padx=(12, 0))
        self.cancel_button = ttk.Button(
            actions, text="Cancel", style="Small.TButton", command=lambda: on_cancel(self.job.id)
        )
        self.retry_button = ttk.Button(
            actions, text="Retry", style="Small.TButton", command=lambda: on_retry(self.job.id)
        )
        self.remove_button = ttk.Button(
            actions, text="Remove", style="SmallGhost.TButton", command=lambda: on_remove(self.job.id)
        )
        self.open_button = ttk.Button(
            actions, text="Open", style="Small.TButton", command=lambda: on_open(self.job.id)
        )
        self._buttons = (self.cancel_button, self.retry_button, self.open_button, self.remove_button)
        self._action_state: str | None = None
        self.job: DownloadJob = None  # type: ignore[assignment]

    def update(self, job: DownloadJob) -> None:
        self.job = job
        self.title_label.configure(text=truncate_text(job.display_title, 110))
        meta = f"{_mode_description(job)}  ·  {self._status_text(job)}"
        self.meta_label.configure(text=truncate_text(meta, 150))

        message = ""
        message_style = "QueueError.TLabel"
        if job.status == JobStatus.FAILED and job.message:
            message = job.message
        elif job.status == JobStatus.COMPLETED and job.already_exists:
            message = job.message
            message_style = "QueueSuccess.TLabel"
        if message:
            self.message_label.configure(text=truncate_text(message, 260), style=message_style)
            self.message_label.grid()
        else:
            self.message_label.grid_remove()

        self._update_buttons(job)
        self._update_bar(job)

        wraplength = max(260, self.frame.winfo_width() - 190)
        try:
            self.title_label.configure(wraplength=wraplength)
            self.meta_label.configure(wraplength=wraplength)
            self.message_label.configure(wraplength=wraplength)
        except tk.TclError:
            pass

    @staticmethod
    def _status_text(job: DownloadJob) -> str:
        if job.cancelling:
            return "Cancelling…"
        if job.status == JobStatus.QUEUED:
            return "Queued"
        if job.status == JobStatus.FETCHING:
            return "Fetching information…"
        if job.status == JobStatus.DOWNLOADING:
            phase = job.phase or "Downloading…"
            if phase.startswith("Video · "):
                phase = phase.removeprefix("Video · ")
            parts = [phase]
            if job.progress is not None:
                parts.append(f"{job.progress:.0f}%")
            speed = format_speed(job.speed)
            if speed:
                parts.append(speed)
            if job.eta:
                parts.append(f"ETA {format_duration(job.eta)}")
            return " · ".join(parts)
        if job.status == JobStatus.COMPLETED:
            return "Already downloaded" if job.already_exists else "Completed"
        if job.status == JobStatus.CANCELLED:
            return "Cancelled"
        if job.status == JobStatus.FAILED:
            return "Failed"
        return str(job.status)

    def _update_buttons(self, job: DownloadJob) -> None:
        if job.status in ACTIVE_STATUSES:
            state = "active"
        elif job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            state = "retry"
        elif job.status == JobStatus.COMPLETED:
            state = "completed"
        else:
            state = "queued"

        if state != self._action_state:
            self._action_state = state
            for button in self._buttons:
                button.pack_forget()
            if state == "active":
                self.cancel_button.pack(side="left")
            elif state == "retry":
                self.retry_button.pack(side="left", padx=(0, 4))
                self.remove_button.pack(side="left")
            elif state == "completed":
                self.open_button.pack(side="left", padx=(0, 4))
                self.remove_button.pack(side="left")
            else:
                self.remove_button.pack(side="left")

        if state == "active":
            self.cancel_button.configure(state="disabled" if job.cancelling else "normal")

    def _update_bar(self, job: DownloadJob) -> None:
        active = job.status in ACTIVE_STATUSES
        if not active:
            if self._bar_visible_applied is not False:
                self.bar.stop()
                self.bar.grid_remove()
                self._bar_visible_applied = False
            return

        if self._bar_visible_applied is not True:
            self.bar.grid()
            self._bar_visible_applied = True

        indeterminate = job.status == JobStatus.FETCHING or job.indeterminate or job.progress is None
        if indeterminate:
            if self._bar_mode != "indeterminate":
                self.bar.stop()
                self.bar.configure(mode="indeterminate")
                self.bar.start(16)
                self._bar_mode = "indeterminate"
        else:
            if self._bar_mode != "determinate":
                self.bar.stop()
                self.bar.configure(mode="determinate")
                self._bar_mode = "determinate"
            self.bar["value"] = max(0.0, min(100.0, job.progress or 0.0))


class QueueView(ttk.Frame):
    def __init__(
        self,
        master: tk.Widget,
        on_cancel: Any,
        on_retry: Any,
        on_remove: Any,
        on_open: Any,
    ) -> None:
        super().__init__(master, style="QueueOuter.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._callbacks = (on_cancel, on_retry, on_remove, on_open)
        self.rows: dict[str, QueueRow] = {}

        self.canvas = tk.Canvas(
            self,
            background=BG,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner = ttk.Frame(self.canvas, style="QueueOuter.TFrame")
        self.inner.columnconfigure(0, weight=1)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._scrollbar_visible = True

        self.empty_label = ttk.Label(
            self.inner,
            text="The queue is empty.  Add a link above to start downloading.",
            style="Muted.TLabel",
            anchor="center",
        )

        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel)
        self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        try:
            needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        except tk.TclError:
            return
        if needed == self._scrollbar_visible:
            return
        self._scrollbar_visible = needed
        if needed:
            self.scrollbar.grid()
        else:
            self.canvas.yview_moveto(0)
            self.scrollbar.grid_remove()

    def _on_wheel(self, event: tk.Event) -> None:
        try:
            under_pointer = self.canvas.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return
        if under_pointer is None:
            return
        path = str(under_pointer)
        if not (path == str(self.canvas) or path.startswith(str(self.canvas) + ".")):
            return
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 2, "units")

    def sync(self, jobs: list[DownloadJob]) -> None:
        ids = [job.id for job in jobs]
        for job_id in list(self.rows):
            if job_id not in ids:
                self.rows.pop(job_id).frame.destroy()

        if jobs:
            self.empty_label.pack_forget()
        else:
            self.empty_label.pack(fill="x", pady=(18, 10))

        for job in jobs:
            row = self.rows.get(job.id)
            if row is None:
                row = QueueRow(self.inner, *self._callbacks)
                self.rows[job.id] = row
                row.frame.pack(fill="x", pady=(0, 6))
            row.update(job)


class TubeGrabApp:
    def __init__(
        self,
        root: tk.Tk,
        paths: AppPaths,
        logger: logging.Logger,
        log_state: LoggingState,
        dependencies: DependencyStatus | None = None,
        downloader: YtDlpDownloader | Any | None = None,
    ) -> None:
        self.root = root
        self.paths = paths
        self.logger = logger
        self.log_state = log_state
        self.config = load_config(paths.config_file, logger)
        self.dependencies = dependencies or detect_dependencies()
        if downloader is not None:
            self.downloader = downloader
        elif self.dependencies.has_ytdlp:
            self.downloader = YtDlpDownloader(
                self.dependencies.ytdlp_command or [],
                self.dependencies.ffmpeg,
                logger,
            )
        else:
            self.downloader = None

        self.events: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.preview_info: MediaInfo | None = None
        self.preview_url: str | None = None
        self.preview_request_url: str | None = None
        self.preview_handle: ProcessHandle | None = None
        self.preview_generation = 0
        self._thumb_photo: tk.PhotoImage | None = None
        self._closing = False
        self._save_after: str | None = None
        self._poll_after: str | None = None
        self._focus_after: str | None = None
        self._log_window: tk.Toplevel | None = None
        self._log_text: tk.Text | None = None
        self._log_after: str | None = None

        self.root.title(APP_NAME)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._apply_window_geometry()
        self.fonts = apply_theme(root)

        try:
            icon_path = Path(__file__).resolve().parent / "assets" / "icon-64.png"
            self._window_icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._window_icon)
        except (tk.TclError, OSError):
            self._window_icon = None
            self.logger.debug("Window icon could not be loaded", exc_info=True)

        self.url_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=self.config.mode)
        self.quality_var = tk.StringVar(
            value=QUALITY_VALUE_TO_LABEL.get(self.config.video_quality, "Best available")
        )
        self.folder_var = tk.StringVar(value=self.config.output_dir)
        self.status_var = tk.StringVar(value="Ready")
        self.preview_title_var = tk.StringVar(value="No preview yet")
        self.preview_meta_var = tk.StringVar(value="Paste a link and choose Preview.")
        self.preview_res_var = tk.StringVar(value="")
        self.preview_audio_var = tk.StringVar(value="")
        self.preview_status_var = tk.StringVar(value="")
        self.input_error_var = tk.StringVar(value="")
        self.queue_count_var = tk.StringVar(value="0 items")

        self.queue_manager = (
            QueueManager(self.downloader, lambda: self.events.put(("queue",)), logger)
            if self.downloader is not None
            else None
        )
        if self.queue_manager is not None:
            self.queue_manager.start()

        self._build_ui()
        self._update_dependency_banner()
        self._update_mode_controls()
        self._update_action_states()
        self._sync_queue()

        self.url_var.trace_add("write", self._on_url_changed)
        self.mode_var.trace_add("write", self._on_mode_changed)
        self.quality_var.trace_add("write", self._on_quality_changed)
        self.folder_var.trace_add("write", self._on_folder_changed)

        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.root.bind("<Control-q>", lambda _event: self.request_close())
        self.root.bind("<Control-l>", lambda _event: self._focus_url())
        self.root.bind("<Control-o>", lambda _event: self._choose_folder())
        self.root.bind("<Escape>", lambda _event: self._cancel_active())
        self.root.report_callback_exception = self._report_callback_exception
        self._poll_after = self.root.after(80, self._poll_events)
        self._focus_after = self.root.after(250, self._focus_url)

    # ------------------------------------------------------------------ layout

    def _apply_window_geometry(self) -> None:
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = max(MIN_WIDTH, min(self.config.window_width, max(MIN_WIDTH, screen_width - 80)))
        height = max(MIN_HEIGHT, min(self.config.window_height, max(MIN_HEIGHT, screen_height - 80)))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        header = ttk.Frame(self.root, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        header.columnconfigure(0, weight=1)
        title_row = ttk.Frame(header, style="Header.TFrame")
        title_row.grid(row=0, column=0, sticky="w")
        ttk.Label(title_row, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(
            title_row,
            text=f"  {__version__}",
            style="Faint.TLabel",
        ).pack(side="left", pady=(7, 0))
        ttk.Label(
            header,
            text="A small desktop downloader for video and audio.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 0))

        self.banner = ttk.Label(
            self.root,
            text="",
            style="Warning.TLabel",
            wraplength=900,
            justify="left",
        )
        self.banner.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.banner.grid_remove()
        self.banner.bind(
            "<Configure>",
            lambda event: self.banner.configure(wraplength=max(400, event.width - 4)),
        )

        card = ttk.Frame(self.root, style="Card.TFrame", padding=(16, 14))
        card.grid(row=2, column=0, sticky="ew", padx=20)
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Video or audio link", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        url_row = ttk.Frame(card, style="Card.TFrame")
        url_row.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        url_row.columnconfigure(0, weight=1)
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, font=self.fonts.base)
        self.url_entry.grid(row=0, column=0, sticky="ew", ipady=2)
        self.preview_button = ttk.Button(
            url_row, text="Preview", command=self._start_preview
        )
        self.preview_button.grid(row=0, column=1, padx=(8, 0))
        self.download_button = ttk.Button(
            url_row,
            text="Download",
            style="Accent.TButton",
            command=self._add_download,
        )
        self.download_button.grid(row=0, column=2, padx=(8, 0))

        hint = ttk.Frame(card, style="Card.TFrame")
        hint.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        ttk.Label(
            hint,
            text="Enter to download  ·  Ctrl+Enter to preview",
            style="CardMuted.TLabel",
        ).pack(side="left")
        self.input_error_label = ttk.Label(
            card,
            textvariable=self.input_error_var,
            style="CardError.TLabel",
            wraplength=780,
            justify="left",
        )
        self.input_error_label.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.input_error_label.grid_remove()

        content = ttk.Frame(card, style="Card.TFrame")
        content.grid(row=4, column=0, sticky="nsew", pady=(14, 0))
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)

        settings = ttk.Frame(content, style="Card.TFrame")
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        settings.columnconfigure(0, weight=1, minsize=400)
        ttk.Label(settings, text="Download type", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        modes = ttk.Frame(settings, style="Card.TFrame")
        modes.grid(row=1, column=0, sticky="w", pady=(5, 12))
        for index, (mode, label) in enumerate(
            (("video", "Video"), ("audio", "Audio · original"), ("mp3", "Audio · MP3"))
        ):
            ttk.Radiobutton(
                modes,
                text=label,
                value=mode,
                variable=self.mode_var,
                style="Segment.Toolbutton",
            ).pack(side="left", padx=(0 if index == 0 else 5, 0))

        self.quality_label = ttk.Label(settings, text="Video quality", style="CardMuted.TLabel")
        self.quality_label.grid(row=2, column=0, sticky="w")
        quality_row = ttk.Frame(settings, style="Card.TFrame")
        quality_row.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        quality_row.columnconfigure(0, weight=1)
        self.quality_combo = ttk.Combobox(
            quality_row,
            textvariable=self.quality_var,
            values=[label for label, _ in QUALITY_OPTIONS],
            state="readonly",
            width=18,
        )
        self.quality_combo.grid(row=0, column=0, sticky="w")
        self.quality_note = ttk.Label(
            settings,
            text="",
            style="CardMuted.TLabel",
            wraplength=400,
            justify="left",
        )
        self.quality_note.grid(row=4, column=0, sticky="w", pady=(5, 12))

        ttk.Label(settings, text="Save to", style="CardMuted.TLabel").grid(
            row=5, column=0, sticky="w"
        )
        folder_row = ttk.Frame(settings, style="Card.TFrame")
        folder_row.grid(row=6, column=0, sticky="ew", pady=(5, 0))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ttk.Button(
            folder_row, text="Browse", style="Small.TButton", command=self._choose_folder
        )
        self.browse_button.grid(row=0, column=1, padx=(6, 0))
        self.open_folder_button = ttk.Button(
            folder_row, text="Open", style="Small.TButton", command=self._open_folder
        )
        self.open_folder_button.grid(row=0, column=2, padx=(4, 0))

        preview = ttk.Frame(content, style="Inset.TFrame", padding=(12, 10))
        preview.grid(row=0, column=1, sticky="nsew")
        preview.columnconfigure(1, weight=1)
        preview.rowconfigure(0, weight=1)
        ttk.Label(preview, text="Preview", style="InsetSection.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        self.thumb_box = tk.Frame(preview, width=240, height=135, background=THUMB_BG)
        self.thumb_box.grid(row=1, column=0, rowspan=5, sticky="nw", padx=(0, 12))
        self.thumb_box.grid_propagate(False)
        self.thumb_label = tk.Label(
            self.thumb_box,
            text="No preview",
            background=THUMB_BG,
            foreground=FAINT,
            font=self.fonts.small,
        )
        self.thumb_label.pack(fill="both", expand=True)

        text_frame = ttk.Frame(preview, style="Inset.TFrame")
        text_frame.grid(row=1, column=1, rowspan=5, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        self.preview_title = ttk.Label(
            text_frame,
            textvariable=self.preview_title_var,
            style="InsetTitle.TLabel",
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.preview_title.grid(row=0, column=0, sticky="w")
        self.preview_meta = ttk.Label(
            text_frame,
            textvariable=self.preview_meta_var,
            style="InsetMuted.TLabel",
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.preview_meta.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.preview_res = ttk.Label(
            text_frame,
            textvariable=self.preview_res_var,
            style="InsetMuted.TLabel",
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.preview_res.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.preview_audio = ttk.Label(
            text_frame,
            textvariable=self.preview_audio_var,
            style="InsetMuted.TLabel",
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.preview_audio.grid(row=3, column=0, sticky="w", pady=(3, 0))
        self.preview_status = ttk.Label(
            text_frame,
            textvariable=self.preview_status_var,
            style="InsetError.TLabel",
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.preview_status.grid(row=4, column=0, sticky="w", pady=(8, 0))

        def resize_preview(event: tk.Event) -> None:
            wrap = max(180, event.width - 4)
            for label in (
                self.preview_title,
                self.preview_meta,
                self.preview_res,
                self.preview_audio,
                self.preview_status,
            ):
                label.configure(wraplength=wrap)

        text_frame.bind("<Configure>", resize_preview)

        queue_area = ttk.Frame(self.root, style="TFrame")
        queue_area.grid(row=3, column=0, sticky="nsew", padx=20, pady=(16, 0))
        queue_area.columnconfigure(0, weight=1)
        queue_area.rowconfigure(1, weight=1)
        queue_header = ttk.Frame(queue_area, style="TFrame")
        queue_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        queue_header.columnconfigure(1, weight=1)
        ttk.Label(queue_header, text="Queue", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            queue_header,
            textvariable=self.queue_count_var,
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.clear_button = ttk.Button(
            queue_header,
            text="Clear finished",
            style="Ghost.TButton",
            command=self._clear_finished,
        )
        self.clear_button.grid(row=0, column=2, sticky="e")

        self.queue_view = QueueView(
            queue_area,
            on_cancel=self._cancel_job,
            on_retry=self._retry_job,
            on_remove=self._remove_job,
            on_open=self._open_job_folder,
        )
        self.queue_view.grid(row=1, column=0, sticky="nsew")

        status = ttk.Frame(self.root, style="Status.TFrame")
        status.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(
            status,
            textvariable=self.status_var,
            style="Status.TLabel",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(20, 10), pady=6)
        self.status_open_button = ttk.Button(
            status,
            text="Open folder",
            style="StatusSmall.TButton",
            command=self._open_folder,
        )
        self.status_open_button.grid(row=0, column=1, padx=(0, 4), pady=4)
        self.details_button = ttk.Button(
            status,
            text="Details",
            style="StatusSmall.TButton",
            command=self._show_details,
        )
        self.details_button.grid(row=0, column=2, padx=(0, 14), pady=4)

        self.url_entry.bind("<Return>", lambda _event: self._add_download())
        self.url_entry.bind("<Control-Return>", lambda _event: self._start_preview())

    # --------------------------------------------------------------- appearance

    def _update_dependency_banner(self) -> None:
        messages: list[str] = []
        if not self.dependencies.has_ytdlp:
            messages.append(
                "yt-dlp was not found. Preview and downloading are disabled. "
                "Install it with: sudo dnf install yt-dlp"
            )
        if not self.dependencies.has_ffmpeg:
            messages.append(
                "FFmpeg was not found. Video merging and MP3 conversion are unavailable; "
                "original-format audio still works. Install it with: sudo dnf install ffmpeg-free"
            )
        if messages:
            self.banner.configure(text="\n".join(messages))
            self.banner.grid()
        else:
            self.banner.grid_remove()

    def _update_mode_controls(self) -> None:
        mode = self.mode_var.get()
        if mode == "video":
            self.quality_label.configure(text="Video quality")
            self.quality_combo.grid()
            self.quality_note.configure(
                text="Source quality. Separate video and audio streams are merged into MKV without re-encoding."
            )
        elif mode == "audio":
            self.quality_label.configure(text="Audio quality")
            self.quality_combo.grid_remove()
            self.quality_note.configure(
                text="Best available source audio, kept in its original codec (typically Opus or AAC). No lossy conversion."
            )
        else:
            self.quality_label.configure(text="Audio conversion")
            self.quality_combo.grid_remove()
            self.quality_note.configure(
                text="Converts the best source audio to MP3 V0 VBR (~245 kbps). This conversion is lossy."
            )
        self._update_action_states()

    def _update_action_states(self) -> None:
        has_url = bool(self.url_var.get().strip())
        available = self.dependencies.has_ytdlp
        self.download_button.configure(state="normal" if has_url and available else "disabled")
        self.preview_button.configure(
            state="normal" if has_url and available and self.preview_handle is None else "disabled"
        )
        folder = self._current_folder()
        can_open = folder is not None and folder_is_usable(folder)
        self.status_open_button.configure(state="normal" if can_open else "disabled")
        self.open_folder_button.configure(state="normal" if can_open else "disabled")

    def _current_folder(self) -> Path | None:
        raw = self.folder_var.get().strip()
        if not raw:
            return None
        try:
            folder = Path(raw).expanduser()
        except (OSError, ValueError):
            return None
        return folder if folder.is_absolute() else None

    def _show_input_error(self, message: str) -> None:
        self.input_error_var.set(message)
        self.input_error_label.grid()
        try:
            self.root.bell()
        except tk.TclError:
            pass

    def _clear_input_error(self) -> None:
        self.input_error_var.set("")
        self.input_error_label.grid_remove()

    # ------------------------------------------------------------------- folder

    def _choose_folder(self) -> None:
        current = self._current_folder()
        initial = current if current is not None and current.is_dir() else Path.home()
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose download folder",
            initialdir=str(initial),
            mustexist=True,
        )
        if selected:
            self.folder_var.set(selected)
            self._schedule_save()

    def _open_folder(self) -> None:
        folder = self._current_folder()
        if folder is None or not folder.is_dir():
            self._show_input_error("That download folder does not exist yet.")
            return
        ok, error = open_path(folder)
        if not ok:
            self._show_input_error(f"Could not open the folder: {error}")

    def _open_job_folder(self, job_id: str) -> None:
        if self.queue_manager is None:
            return
        job = next((item for item in self.queue_manager.snapshot() if item.id == job_id), None)
        if job is None:
            return
        if not job.output_dir.is_dir():
            self._show_input_error("That download folder no longer exists.")
            return
        ok, error = open_path(job.output_dir)
        if not ok:
            self._show_input_error(f"Could not open the folder: {error}")

    # ----------------------------------------------------------------- preview

    def _start_preview(self) -> None:
        if self.dependencies.ytdlp_command is None or self.downloader is None:
            self._show_input_error("yt-dlp is not available. Install it before previewing a link.")
            return
        try:
            url = validate_url(self.url_var.get())
        except ValidationError as exc:
            self._show_input_error(str(exc))
            return

        self._cancel_preview()
        self._clear_input_error()
        self._clear_preview()
        self._thumb_photo = None
        self.thumb_label.configure(image="", text="Loading…")
        self.preview_generation += 1
        generation = self.preview_generation
        handle = ProcessHandle()
        self.preview_handle = handle
        self.preview_request_url = url
        self.preview_status_var.set("")
        self.preview_title_var.set("Fetching information…")
        self.preview_meta_var.set(url)
        self.preview_res_var.set("")
        self.preview_audio_var.set("")
        self.preview_button.configure(text="Fetching…", state="disabled")
        self.logger.info("Preview requested for %s", url)

        thread = threading.Thread(
            target=self._preview_worker,
            args=(url, generation, handle),
            name="tubegrab-preview",
            daemon=True,
        )
        thread.start()

    def _preview_worker(self, url: str, generation: int, handle: ProcessHandle) -> None:
        try:
            assert self.downloader is not None
            info = self.downloader.fetch_info(url, handle)
            if generation != self.preview_generation:
                return
            self.events.put(("preview_info", generation, info))
            if info.thumbnail_url:
                try:
                    thumbnail = fetch_thumbnail(
                        info,
                        self.paths.thumbnail_dir,
                        self.dependencies.ffmpeg,
                        self.logger,
                    )
                except Exception:
                    self.logger.exception("Unexpected thumbnail failure")
                    thumbnail = None
                self.events.put(("preview_thumb", generation, thumbnail))
        except DownloadCancelled:
            self.events.put(("preview_cancelled", generation))
        except DownloadError as exc:
            self.events.put(("preview_error", generation, exc.user_message, exc.detail))
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.logger.exception("Unexpected preview failure")
            self.events.put(("preview_error", generation, "Could not fetch preview information.", str(exc)))

    def _handle_preview_info(self, generation: int, info: MediaInfo) -> None:
        if generation != self.preview_generation:
            return
        if self.url_var.get().strip() != info.url:
            return
        self.preview_info = info
        self.preview_url = info.url
        self.preview_handle = None
        self.preview_button.configure(text="Preview", state="normal")
        self._update_action_states()
        if not info.thumbnail_url:
            self.thumb_label.configure(image="", text="No preview")
        self.preview_title_var.set(info.display_title)
        details = []
        if info.uploader:
            details.append(info.uploader)
        if info.duration is not None:
            details.append(format_duration(info.duration))
        if info.extractor:
            details.append(info.extractor.replace("Youtube", "YouTube"))
        self.preview_meta_var.set("  ·  ".join(details) if details else "Information from the site")
        summary = info.summary
        self.preview_res_var.set(f"Video: {summary.resolution_text}")
        self.preview_audio_var.set(f"Audio: {summary.audio_text}")
        self.preview_status_var.set("")
        self.logger.info("Preview ready: %s", info.display_title)

    def _handle_preview_thumb(self, generation: int, path: Path | None) -> None:
        if generation != self.preview_generation:
            return
        if path is None:
            self.thumb_label.configure(image="", text="No preview")
            return
        try:
            image = tk.PhotoImage(file=str(path))
            self._thumb_photo = image.subsample(2, 2)
            self.thumb_label.configure(image=self._thumb_photo, text="")
        except tk.TclError:
            self.logger.warning("Could not display thumbnail %s", path, exc_info=True)
            self._thumb_photo = None
            self.thumb_label.configure(image="", text="No preview")

    def _handle_preview_error(self, generation: int, message: str, detail: str) -> None:
        if generation != self.preview_generation:
            return
        if detail:
            self.logger.debug("Preview failure details:\n%s", detail)
        self.preview_handle = None
        self.preview_button.configure(text="Preview", state="normal")
        self._clear_preview()
        self.preview_title_var.set("Preview unavailable")
        self.preview_meta_var.set("")
        self.preview_status_var.set(message)
        self._update_action_states()

    def _cancel_preview(self) -> None:
        handle = self.preview_handle
        self.preview_handle = None
        self.preview_generation += 1
        if handle is not None:
            handle.cancel()
        if hasattr(self, "preview_button"):
            self.preview_button.configure(text="Preview")
        self.preview_request_url = None

    def _clear_preview(self) -> None:
        self.preview_info = None
        self.preview_url = None
        self._thumb_photo = None
        self.thumb_label.configure(image="", text="No preview")
        self.preview_title_var.set("No preview yet")
        self.preview_meta_var.set("Paste a link and choose Preview.")
        self.preview_res_var.set("")
        self.preview_audio_var.set("")
        self.preview_status_var.set("")

    # -------------------------------------------------------------- downloading

    def _add_download(self) -> None:
        if self.queue_manager is None or self.dependencies.ytdlp_command is None:
            self._show_input_error(
                "yt-dlp is not available. Install it with: sudo dnf install yt-dlp"
            )
            return
        try:
            url = validate_url(self.url_var.get())
        except ValidationError as exc:
            self._show_input_error(str(exc))
            return

        mode = self.mode_var.get()
        if mode not in {"video", "audio", "mp3"}:
            self._show_input_error("Choose a valid download type.")
            return
        if mode_requires_ffmpeg(mode) and not self.dependencies.has_ffmpeg:
            self._show_input_error(
                "FFmpeg is required for video merging and MP3 conversion. "
                "Install it with: sudo dnf install ffmpeg-free"
            )
            return

        raw_folder = self.folder_var.get().strip()
        if not raw_folder:
            self._show_input_error("Choose a download folder.")
            return
        folder = Path(raw_folder).expanduser()
        if not folder.is_absolute():
            self._show_input_error("Choose an absolute download folder.")
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show_input_error(f"Cannot create the download folder: {exc}")
            return
        if not folder_is_usable(folder):
            self._show_input_error("The download folder is not writable.")
            return

        quality = QUALITY_LABEL_TO_VALUE.get(self.quality_var.get())
        info = self.preview_info if self.preview_url == url else None
        try:
            _job_id, added = self.queue_manager.add(url, mode, quality, folder, info=info)
        except (ValidationError, ValueError) as exc:
            self._show_input_error(str(exc))
            return

        if not added:
            self._show_input_error("That download is already in the queue.")
            return

        self.logger.info("Added %s to the queue", url)
        self.config.output_dir = str(folder)
        self.config.mode = mode
        self.config.video_quality = quality
        self._schedule_save()
        self._clear_input_error()
        self.url_var.set("")
        self._clear_preview()
        self.url_entry.focus_set()
        self._sync_queue()

    def _cancel_job(self, job_id: str) -> None:
        if self.queue_manager is None:
            return
        active = self.queue_manager.active_job()
        if active is not None and active.id == job_id:
            self.queue_manager.cancel_active()

    def _cancel_active(self) -> None:
        if self.queue_manager is not None:
            self.queue_manager.cancel_active()

    def _retry_job(self, job_id: str) -> None:
        if self.queue_manager is not None:
            self.queue_manager.retry(job_id)

    def _remove_job(self, job_id: str) -> None:
        if self.queue_manager is not None:
            self.queue_manager.remove(job_id)

    def _clear_finished(self) -> None:
        if self.queue_manager is not None:
            self.queue_manager.clear_finished()

    # ------------------------------------------------------------------ status

    def _sync_queue(self) -> None:
        jobs = self.queue_manager.snapshot() if self.queue_manager is not None else []
        self.queue_view.sync(jobs)
        count = len(jobs)
        self.queue_count_var.set(f"{count} item" if count == 1 else f"{count} items")
        self.clear_button.configure(
            state="normal"
            if any(job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED} for job in jobs)
            else "disabled"
        )

        active = next((job for job in jobs if job.status in ACTIVE_STATUSES), None)
        if active is not None:
            phase = "Cancelling…" if active.cancelling else active.phase or "Working…"
            self.status_var.set(truncate_text(f"{active.display_title}  —  {phase}", 130))
        elif jobs:
            failed = sum(1 for job in jobs if job.status == JobStatus.FAILED)
            if failed:
                self.status_var.set(f"{failed} failed download{'s' if failed != 1 else ''} in the queue")
            else:
                self.status_var.set(f"Ready  ·  {count} queue item{'s' if count != 1 else ''}")
        elif self.dependencies.has_ytdlp:
            self.status_var.set("Ready")
        else:
            self.status_var.set("yt-dlp is not installed")
        self._update_action_states()

    def _poll_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "queue":
                    self._sync_queue()
                elif kind == "preview_info":
                    self._handle_preview_info(event[1], event[2])
                elif kind == "preview_thumb":
                    self._handle_preview_thumb(event[1], event[2])
                elif kind == "preview_error":
                    self._handle_preview_error(event[1], event[2], event[3])
                elif kind == "preview_cancelled":
                    if event[1] == self.preview_generation:
                        self.preview_handle = None
                        self.preview_button.configure(text="Preview", state="normal")
                        self._update_action_states()
        except queue.Empty:
            pass
        self._poll_after = self.root.after(80, self._poll_events)

    # ------------------------------------------------------------------- state

    def _on_url_changed(self, *_args: Any) -> None:
        raw = self.url_var.get()
        if self.input_error_var.get():
            self._clear_input_error()
        if raw.strip() != self.preview_url and (
            self.preview_url is not None
            or self.preview_info is not None
            or self.preview_status_var.get()
        ):
            self._clear_preview()
        if self.preview_handle is not None and raw.strip() != self.preview_request_url:
            self._cancel_preview()
            self._clear_preview()
        self._update_action_states()

    def _on_mode_changed(self, *_args: Any) -> None:
        self._update_mode_controls()
        self._schedule_save()

    def _on_quality_changed(self, *_args: Any) -> None:
        self._schedule_save()

    def _on_folder_changed(self, *_args: Any) -> None:
        self._update_action_states()
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._closing:
            return
        if self._save_after is not None:
            try:
                self.root.after_cancel(self._save_after)
            except tk.TclError:
                pass
        self._save_after = self.root.after(700, self._save_config)

    def _collect_config(self) -> Config:
        quality = QUALITY_LABEL_TO_VALUE.get(self.quality_var.get())
        mode = self.mode_var.get()
        raw_folder = self.folder_var.get().strip()
        try:
            folder = Path(raw_folder).expanduser() if raw_folder else None
        except (OSError, ValueError):
            folder = None
        output_dir = str(folder) if folder is not None and folder.is_absolute() else self.config.output_dir
        return Config(
            output_dir=output_dir,
            mode=mode if mode in {"video", "audio", "mp3"} else "video",
            video_quality=quality,
            window_width=self.root.winfo_width(),
            window_height=self.root.winfo_height(),
        ).normalised()

    def _save_config(self) -> None:
        self._save_after = None
        save_config(self.paths.config_file, self._collect_config(), self.logger)

    # ------------------------------------------------------------------- details

    def _show_details(self) -> None:
        if self._log_window is not None and self._log_window.winfo_exists():
            self._log_window.deiconify()
            self._log_window.lift()
            self._refresh_log()
            return

        window = tk.Toplevel(self.root)
        window.title(f"{APP_NAME} — Activity details")
        window.geometry("780x460")
        window.minsize(560, 300)
        window.configure(background=BG)
        window.transient(self.root)
        if self._window_icon is not None:
            try:
                window.iconphoto(True, self._window_icon)
            except tk.TclError:
                pass
        self._log_window = window

        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        header = ttk.Frame(window, style="TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Activity details", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        log_path = str(self.log_state.log_file) if self.log_state.log_file else "not available"
        ttk.Label(
            header,
            text=f"Diagnostic log: {log_path}",
            style="Faint.TLabel",
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        text_frame = ttk.Frame(window, style="TFrame")
        text_frame.grid(row=2, column=0, sticky="nsew", padx=16)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text = tk.Text(
            text_frame,
            wrap="word",
            background=INSET,
            foreground="#d8d8d8",
            insertbackground="#d8d8d8",
            selectbackground="#31557a",
            selectforeground="#ffffff",
            font=self.fonts.mono,
            padx=10,
            pady=8,
            relief="flat",
            borderwidth=0,
            state="disabled",
            height=10,
        )
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        text.configure(yscrollcommand=scrollbar.set)
        self._log_text = text

        buttons = ttk.Frame(window, style="TFrame")
        buttons.grid(row=3, column=0, sticky="ew", padx=16, pady=(10, 14))
        buttons.columnconfigure(0, weight=1)
        ttk.Button(buttons, text="Clear view", style="Ghost.TButton", command=self._clear_log_view).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(buttons, text="Copy", style="TButton", command=self._copy_log).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(
            buttons,
            text="Open log file",
            style="TButton",
            command=self._open_log_file,
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(buttons, text="Close", style="TButton", command=self._close_details).grid(
            row=0, column=3, padx=(8, 0)
        )

        window.protocol("WM_DELETE_WINDOW", self._close_details)
        self._refresh_log()
        window.bind("<Escape>", lambda _event: self._close_details())

    def _refresh_log(self) -> None:
        if self._log_window is None or not self._log_window.winfo_exists():
            return
        if self._log_text is None:
            return
        if self._log_after is not None:
            try:
                self.root.after_cancel(self._log_after)
            except tk.TclError:
                pass
            self._log_after = None
        content = self.log_state.memory.text()
        if not content:
            content = "No activity yet."
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("1.0", content + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")
        self._log_after = self.root.after(1000, self._refresh_log)

    def _clear_log_view(self) -> None:
        self.log_state.memory.clear()
        self._refresh_log()

    def _copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_state.memory.text())

    def _open_log_file(self) -> None:
        path = self.log_state.log_file
        if path is None or not path.exists():
            self._show_input_error("The diagnostic log file is not available.")
            return
        ok, error = open_path(path)
        if not ok:
            self._show_input_error(f"Could not open the log file: {error}")

    def _close_details(self) -> None:
        if self._log_after is not None:
            try:
                self.root.after_cancel(self._log_after)
            except tk.TclError:
                pass
            self._log_after = None
        window = self._log_window
        self._log_window = None
        self._log_text = None
        if window is not None and window.winfo_exists():
            window.destroy()

    # ------------------------------------------------------------------- close

    def prefill_url(self, url: str) -> None:
        self.url_var.set(url)
        self.url_entry.icursor("end")
        self.url_entry.focus_set()

    def _focus_url(self) -> None:
        try:
            self.url_entry.focus_set()
            self.url_entry.selection_range(0, "end")
        except tk.TclError:
            pass

    def _report_callback_exception(self, exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
        self.logger.error(
            "Unhandled Tk callback exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        try:
            messagebox.showerror(
                APP_NAME,
                "An unexpected error occurred. Open Details to see the diagnostic log.",
                parent=self.root,
            )
        except tk.TclError:
            pass

    def request_close(self, confirm: bool = True) -> None:
        if self._closing:
            return
        active = self.queue_manager.active_job() if self.queue_manager is not None else None
        if confirm and active is not None:
            proceed = messagebox.askyesno(
                APP_NAME,
                "A download is still in progress. Quit and cancel it?",
                parent=self.root,
            )
            if not proceed:
                return
        self._closing = True
        if self._save_after is not None:
            try:
                self.root.after_cancel(self._save_after)
            except tk.TclError:
                pass
            self._save_after = None
        try:
            self._save_config()
        except Exception:
            self.logger.exception("Could not save configuration while closing")
        for timer_name in ("_poll_after", "_focus_after"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
                setattr(self, timer_name, None)
        self._cancel_preview()
        if self.queue_manager is not None:
            self.queue_manager.shutdown(timeout=6.0)
        if self._log_after is not None:
            try:
                self.root.after_cancel(self._log_after)
            except tk.TclError:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
