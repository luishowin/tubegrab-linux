"""Tkinter interface for TubeGrab."""

from __future__ import annotations

import logging
import math
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
from .theme import apply_theme, current_fonts, current_palette
from .widgets import (
    Card,
    PopupSelect,
    RoundedButton,
    ScrollFrame,
    SearchField,
    SegmentedControl,
    ThinProgress,
    draw_round_rect,
    load_icon,
    separator,
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
URL_STACK_WIDTH = 740
GRID_STACK_WIDTH = 820


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
        on_restart: Any,
        on_remove: Any,
        on_open: Any,
    ) -> None:
        palette = current_palette()
        fonts = current_fonts()
        self._palette = palette
        self._fonts = fonts
        self.frame = tk.Frame(parent, background=palette.card)
        self.frame.columnconfigure(1, weight=1)
        self.separator = tk.Frame(self.frame, height=1, background=palette.sep)
        self.separator.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.separator.grid_propagate(False)

        self.thumb = tk.Canvas(
            self.frame,
            width=76,
            height=43,
            background=palette.card,
            borderwidth=0,
            highlightthickness=0,
        )
        self.thumb.grid(row=1, column=0, rowspan=4, sticky="nw", padx=(14, 12), pady=10)
        self._thumb_photo: tk.PhotoImage | None = None
        self._thumb_key: tuple[str, int] | None = None
        self._draw_placeholder()

        self.meta = tk.Frame(self.frame, background=palette.card)
        self.meta.grid(row=1, column=1, sticky="nsew", pady=(10, 10))
        self.meta.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(
            self.meta,
            text="",
            style="QueueTitle.TLabel",
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        status_row = tk.Frame(self.meta, background=palette.card)
        status_row.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.status_icon = tk.Label(
            status_row,
            text="",
            image="",
            background=palette.card,
            borderwidth=0,
        )
        self.status_icon.pack(side="left", padx=(0, 4))
        self.status_label = tk.Label(
            status_row,
            text="",
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
            anchor="w",
        )
        self.status_label.pack(side="left")
        self.meta_separator = tk.Label(
            status_row,
            text="·",
            background=palette.card,
            foreground=palette.text3,
            font=fonts.small,
        )
        self.meta_separator.pack(side="left", padx=6)
        self.meta_label = tk.Label(
            status_row,
            text="",
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
            anchor="w",
        )
        self.meta_label.pack(side="left")

        self.message_label = tk.Label(
            self.meta,
            text="",
            background=palette.card,
            foreground=palette.red,
            font=fonts.small,
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.message_label.grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.message_label.grid_remove()

        self.progress = ThinProgress(self.meta, background=palette.card)
        self.progress.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self.progress.grid_remove()
        self._progress_visible = False

        actions = tk.Frame(self.frame, background=palette.card)
        actions.grid(row=1, column=2, sticky="ne", padx=(12, 14), pady=10)
        self.cancel_button = RoundedButton(
            actions,
            "Cancel",
            style="small",
            background=palette.card,
            command=lambda: on_cancel(self.job.id),
        )
        self.retry_button = RoundedButton(
            actions,
            "Retry",
            style="small",
            background=palette.card,
            command=lambda: on_retry(self.job.id),
        )
        self.restart_button = RoundedButton(
            actions,
            "Start over",
            style="small",
            background=palette.card,
            command=lambda: on_restart(self.job.id),
        )
        self.open_button = RoundedButton(
            actions,
            "Show",
            style="small",
            background=palette.card,
            command=lambda: on_open(self.job.id),
        )
        self.remove_button = RoundedButton(
            actions,
            "",
            style="ghost",
            background=palette.card,
            image=load_icon("x"),
            width=28,
            height=28,
            command=lambda: on_remove(self.job.id),
        )
        self._buttons = (
            self.cancel_button,
            self.retry_button,
            self.restart_button,
            self.open_button,
            self.remove_button,
        )
        self._action_state: str | None = None
        self._wraplength = 560
        self.job: DownloadJob = None  # type: ignore[assignment]
        self.meta.bind("<Configure>", self._on_meta_configure, add="+")

    def _on_meta_configure(self, event: tk.Event) -> None:
        """Wrap text to the real column width instead of a fixed guess."""

        wraplength = max(120, event.width - 2)
        if wraplength == self._wraplength:
            return
        self._wraplength = wraplength
        self.title_label.configure(wraplength=wraplength)
        self.message_label.configure(wraplength=wraplength)

    def _draw_placeholder(self) -> None:
        self.thumb.delete("all")
        palette = self._palette
        colors = (palette.thumb_top, palette.thumb_middle, palette.thumb_bottom)
        width, height = 76, 43
        for index in range(9):
            t = index / 8
            if t < 0.5:
                color = _blend(colors[0], colors[1], t * 2)
            else:
                color = _blend(colors[1], colors[2], (t - 0.5) * 2)
            y1 = int(index * height / 9)
            y2 = int((index + 1) * height / 9) + 1
            self.thumb.create_rectangle(0, y1, width, y2, fill=color, outline="")
        self.thumb.create_polygon(
            34,
            15,
            34,
            28,
            45,
            21.5,
            fill="#ffffff",
            outline="",
            tags="glyph",
        )
        self._thumb_photo = None

    def set_thumbnail(self, source: tk.PhotoImage | None) -> None:
        if source is None:
            if self._thumb_key is not None:
                self._thumb_key = None
                self._draw_placeholder()
            return
        key = (str(source), id(source))
        if self._thumb_key == key:
            return
        self._thumb_key = key
        # Round up so the image never exceeds the thumbnail canvas; a fractional
        # downscale has to be letterboxed instead of cropped.
        factor = max(
            1, math.ceil(source.width() / 76), math.ceil(source.height() / 43)
        )
        photo = source.subsample(factor, factor) if factor > 1 else source
        self._thumb_photo = photo
        self.thumb.delete("all")
        self.thumb.create_rectangle(0, 0, 76, 43, fill=self._palette.thumb_bottom, outline="")
        self.thumb.create_image(38, 21.5, image=photo)

    def update(self, job: DownloadJob, thumbnail: tk.PhotoImage | None = None) -> None:
        self.job = job
        self.set_thumbnail(thumbnail)
        self.title_label.configure(text=truncate_text(job.display_title, 110))
        self.meta_label.configure(text=truncate_text(_mode_description(job), 90))
        status = self._status_text(job)
        self.status_label.configure(text=truncate_text(status, 80))
        if job.status == JobStatus.COMPLETED:
            self.status_label.configure(foreground=self._palette.green)
            self.status_icon.configure(image=load_icon("check"))
            self.status_icon.image = load_icon("check")  # type: ignore[attr-defined]
        elif job.status == JobStatus.FAILED:
            self.status_label.configure(foreground=self._palette.red)
            self.status_icon.configure(image=load_icon("x"))
            self.status_icon.image = load_icon("x")  # type: ignore[attr-defined]
        else:
            self.status_label.configure(foreground=self._palette.text2)
            self.status_icon.configure(image="")
            self.status_icon.image = None  # type: ignore[attr-defined]

        message = ""
        if job.status == JobStatus.FAILED and job.message:
            message = job.message
        elif job.status == JobStatus.COMPLETED and job.already_exists:
            message = job.message
        if message:
            self.message_label.configure(
                text=truncate_text(message, 260),
                foreground=(
                    self._palette.green
                    if job.status == JobStatus.COMPLETED
                    else self._palette.red
                ),
            )
            self.message_label.grid()
        else:
            self.message_label.grid_remove()

        self._update_buttons(job)
        self._update_bar(job)

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
            if phase.startswith("Video · ") or phase.startswith("Audio · "):
                phase = "Downloading"
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
                self.retry_button.pack(side="left", padx=(0, 6))
                self.restart_button.pack(side="left", padx=(0, 6))
                self.remove_button.pack(side="left")
            elif state == "completed":
                self.open_button.pack(side="left", padx=(0, 6))
                self.remove_button.pack(side="left")
            else:
                self.remove_button.pack(side="left")

        if state == "active":
            self.cancel_button.configure(state="disabled" if job.cancelling else "normal")

    def _update_bar(self, job: DownloadJob) -> None:
        active = job.status in ACTIVE_STATUSES
        if not active:
            if self._progress_visible:
                self.progress.grid_remove()
                self._progress_visible = False
            return

        if not self._progress_visible:
            self.progress.grid()
            self._progress_visible = True
        indeterminate = job.status == JobStatus.FETCHING or job.indeterminate or job.progress is None
        self.progress.set_value(None if indeterminate else job.progress)


class QueueView(tk.Frame):
    def __init__(
        self,
        master: tk.Widget,
        on_cancel: Any,
        on_retry: Any,
        on_restart: Any,
        on_remove: Any,
        on_open: Any,
    ) -> None:
        palette = current_palette()
        super().__init__(master, background=palette.card)
        self.columnconfigure(0, weight=1)
        self._callbacks = (on_cancel, on_retry, on_restart, on_remove, on_open)
        self.rows: dict[str, QueueRow] = {}

        self.empty_label = tk.Label(
            self,
            text="The queue is empty. Add a link above to start downloading.",
            background=palette.card,
            foreground=palette.text2,
            font=current_fonts().small,
            anchor="center",
        )

    def sync(
        self,
        jobs: list[DownloadJob],
        thumbnails: dict[str, tk.PhotoImage] | None = None,
    ) -> None:
        ids = [job.id for job in jobs]
        for job_id in list(self.rows):
            if job_id not in ids:
                self.rows.pop(job_id).frame.destroy()

        if jobs:
            self.empty_label.pack_forget()
        else:
            self.empty_label.pack(fill="x", pady=(22, 22))

        for job in jobs:
            row = self.rows.get(job.id)
            if row is None:
                row = QueueRow(self, *self._callbacks)
                self.rows[job.id] = row
                row.frame.pack(fill="x")
            photo = thumbnails.get(job.url) if thumbnails else None
            row.update(job, photo)


def _blend(start: str, end: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    first = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
    second = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
    values = tuple(round(a + (b - a) * amount) for a, b in zip(first, second))
    return "#{:02x}{:02x}{:02x}".format(*values)


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
                js_runtime=(
                    self.dependencies.js_runtime
                    if self.dependencies.js_runtimes_supported
                    else None
                ),
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
        self._job_thumbnails: dict[str, tk.PhotoImage] = {}

        self.root.title(APP_NAME)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._apply_window_geometry()
        self.fonts = apply_theme(root)
        self.palette = current_palette()
        try:
            font_system = str(root.tk.call("::tk::pkgconfig", "get", "fontsystem"))
        except tk.TclError:
            font_system = ""
        if font_system and font_system != "xft":
            self.logger.warning(
                "This Python's Tk was built without Xft (%s); text will not be antialiased. "
                "Use the system python3-tkinter build for smooth text.",
                font_system,
            )

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
        self._preview_full_title = "No preview yet"
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
        palette = self.palette
        fonts = self.fonts
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.page = ScrollFrame(root, background=palette.content, padding=(24, 24))
        self.page.grid(row=0, column=0, sticky="nsew")
        page = self.page.inner
        page.columnconfigure(0, weight=1)

        self.banner = ttk.Label(
            page,
            text="",
            style="Warning.TLabel",
            wraplength=880,
            justify="left",
        )
        self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.banner.grid_remove()
        self.banner.bind(
            "<Configure>",
            lambda event: self.banner.configure(wraplength=max(400, event.width - 4)),
        )

        link_section = tk.Frame(page, background=palette.content)
        link_section.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        link_section.columnconfigure(0, weight=1)

        self.url_row = url_row = tk.Frame(link_section, background=palette.content)
        url_row.grid(row=0, column=0, sticky="ew")
        url_row.columnconfigure(0, weight=1)

        self.url_field = SearchField(
            url_row,
            self.url_var,
            placeholder="Paste a video or audio link",
            font=fonts.base,
            icon=load_icon("link"),
            background=palette.content,
        )
        self.url_field.grid(row=0, column=0, sticky="ew")
        self.url_entry = self.url_field.entry
        self.paste_button = RoundedButton(
            self.url_field,
            "Paste",
            style="pill",
            background=palette.field,
            command=self._paste_url,
        )
        self.url_field.set_accessory(self.paste_button)

        self.preview_button = RoundedButton(
            url_row,
            "Preview",
            style="secondary",
            background=palette.content,
            command=self._start_preview,
        )
        self.preview_button.grid(row=0, column=1, padx=(10, 0))

        self.download_button = RoundedButton(
            url_row,
            "Download",
            style="primary",
            background=palette.content,
            image=load_icon("download"),
            command=self._add_download,
        )
        self.download_button.grid(row=0, column=2, padx=(10, 0))

        hint = tk.Frame(link_section, background=palette.content)
        hint.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._shortcut_chip(hint, "Return", "Download")
        self._shortcut_chip(hint, "Ctrl+Enter", "Preview", padx=(14, 0))

        self.input_error_label = tk.Label(
            link_section,
            textvariable=self.input_error_var,
            background=palette.content,
            foreground=palette.red,
            font=fonts.small,
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.input_error_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.input_error_label.grid_remove()

        self.grid_section = grid_section = tk.Frame(page, background=palette.content)
        grid_section.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        grid_section.columnconfigure(0, weight=0, minsize=440)
        grid_section.columnconfigure(1, weight=1)
        grid_section.rowconfigure(0, weight=1)

        self.options_column = options_column = tk.Frame(grid_section, background=palette.content)
        options_column.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        tk.Label(
            options_column,
            text="OPTIONS",
            background=palette.content,
            foreground=palette.text2,
            font=fonts.section,
        ).pack(anchor="w", padx=4, pady=(0, 6))

        self.options_card = options_card = Card(options_column, padding=(2, 2), background=palette.content)
        options_card.pack(fill="x")
        options = options_card.body
        options.columnconfigure(0, weight=1)

        format_row = tk.Frame(options, background=palette.card)
        format_row.grid(row=0, column=0, sticky="ew")
        format_row.columnconfigure(0, weight=1)
        tk.Label(
            format_row,
            text="Format",
            background=palette.card,
            foreground=palette.text,
            font=fonts.base,
        ).grid(row=0, column=0, sticky="w", padx=(14, 10), pady=10)
        self.mode_control = SegmentedControl(
            format_row,
            self.mode_var,
            (("video", "Video"), ("audio", "Audio"), ("mp3", "MP3")),
            background=palette.card,
        )
        self.mode_control.grid(row=0, column=1, sticky="e", padx=(10, 12), pady=8)

        separator(options).grid(row=1, column=0, sticky="ew")

        quality_row = tk.Frame(options, background=palette.card)
        quality_row.grid(row=2, column=0, sticky="ew")
        quality_row.columnconfigure(0, weight=1)
        self.quality_label = tk.Label(
            quality_row,
            text="Quality",
            background=palette.card,
            foreground=palette.text,
            font=fonts.base,
        )
        self.quality_label.grid(row=0, column=0, sticky="w", padx=(14, 10), pady=10)
        self.quality_combo = PopupSelect(
            quality_row,
            self.quality_var,
            [label for label, _value in QUALITY_OPTIONS],
            background=palette.card,
            chevron=load_icon("chevron"),
            command=self._on_quality_changed,
        )
        self.quality_combo.grid(row=0, column=1, sticky="e", padx=(10, 14), pady=8)
        self.quality_static = tk.Label(
            quality_row,
            text="",
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
        )
        self.quality_static.grid(row=0, column=1, sticky="e", padx=(10, 14), pady=8)
        self.quality_static.grid_remove()

        separator(options).grid(row=3, column=0, sticky="ew")

        save_row = tk.Frame(options, background=palette.card)
        save_row.grid(row=4, column=0, sticky="ew")
        save_row.columnconfigure(1, weight=1)
        tk.Label(
            save_row,
            text="Save to",
            background=palette.card,
            foreground=palette.text,
            font=fonts.base,
        ).grid(row=0, column=0, sticky="w", padx=(14, 10), pady=10)

        path_row = tk.Frame(save_row, background=palette.card)
        path_row.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=8)
        path_row.columnconfigure(1, weight=1)
        tk.Label(path_row, image=load_icon("folder"), background=palette.card).grid(
            row=0, column=0, padx=(0, 5)
        )
        self.folder_entry = tk.Entry(
            path_row,
            textvariable=self.folder_var,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=palette.card,
            foreground=palette.text2,
            insertbackground=palette.text,
            font=fonts.small,
            width=6,
        )
        self.folder_entry.grid(row=0, column=1, sticky="ew")
        self.browse_button = RoundedButton(
            path_row,
            "Choose…",
            style="small",
            background=palette.card,
            command=self._choose_folder,
        )
        self.browse_button.grid(row=0, column=2, padx=(6, 0))
        self.open_folder_button = RoundedButton(
            path_row,
            "Open",
            style="ghost",
            background=palette.card,
            width=44,
            command=self._open_folder,
        )
        self.open_folder_button.grid(row=0, column=3, padx=(2, 0))

        self.quality_note = ttk.Label(
            grid_section,
            text="",
            style="Muted.TLabel",
            wraplength=880,
            justify="left",
        )
        self.quality_note.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(7, 0))

        self.preview_column = preview_column = tk.Frame(grid_section, background=palette.content)
        preview_column.grid(row=0, column=1, sticky="nsew")
        tk.Label(
            preview_column,
            text="PREVIEW",
            background=palette.content,
            foreground=palette.text2,
            font=fonts.section,
        ).pack(anchor="w", padx=4, pady=(0, 6))

        self.preview_card = Card(
            preview_column,
            padding=(16, 16),
            autosize=False,
            height=1,
            background=palette.content,
        )
        self.preview_card.pack(fill="both", expand=True)
        preview_body = self.preview_card.body
        preview_body.columnconfigure(0, weight=1)
        preview_body.rowconfigure(0, weight=1)

        self.preview_empty = tk.Frame(preview_body, background=palette.card)
        self.preview_empty.grid(row=0, column=0, sticky="nsew")
        empty_inner = tk.Frame(self.preview_empty, background=palette.card)
        empty_inner.place(relx=0.5, rely=0.5, anchor="center")
        glyph = tk.Canvas(
            empty_inner,
            width=56,
            height=56,
            background=palette.card,
            borderwidth=0,
            highlightthickness=0,
        )
        draw_round_rect(glyph, 0, 0, 56, 56, 14, fill=palette.fill, background=palette.card)
        glyph.create_image(28, 28, image=load_icon("play"))
        glyph.pack(pady=(0, 12))
        tk.Label(
            empty_inner,
            text="No Preview",
            background=palette.card,
            foreground=palette.text,
            font=fonts.base_bold,
        ).pack()
        tk.Label(
            empty_inner,
            text="Paste a link and choose Preview.",
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
        ).pack(pady=(3, 0))

        self.preview_detail = tk.Frame(preview_body, background=palette.card)
        self.preview_detail.grid(row=0, column=0, sticky="nsew")
        self.preview_detail.grid_remove()
        self.preview_detail.columnconfigure(1, weight=1)

        self.thumb_box = tk.Frame(
            self.preview_detail,
            background=palette.fill,
            width=160,
            height=90,
        )
        self.thumb_box.grid(row=0, column=0, sticky="nw", padx=(0, 14))
        self.thumb_box.grid_propagate(False)
        self.thumb_label = tk.Label(
            self.thumb_box,
            text="No preview",
            background=palette.fill,
            foreground=palette.text2,
            font=fonts.small,
        )
        self.thumb_label.pack(fill="both", expand=True)

        preview_text = tk.Frame(self.preview_detail, background=palette.card)
        preview_text.grid(row=0, column=1, sticky="nsew")
        preview_text.columnconfigure(0, weight=1)

        self.preview_title = tk.Label(
            preview_text,
            textvariable=self.preview_title_var,
            background=palette.card,
            foreground=palette.text,
            font=fonts.base_bold,
            anchor="w",
            justify="left",
            wraplength=320,
            height=2,
        )
        self.preview_title.grid(row=0, column=0, sticky="ew")
        self.preview_meta = tk.Label(
            preview_text,
            textvariable=self.preview_meta_var,
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
            anchor="w",
            justify="left",
            height=1,
        )
        self.preview_meta.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.preview_res = tk.Label(
            preview_text,
            textvariable=self.preview_res_var,
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
            anchor="w",
            justify="left",
            height=1,
        )
        self.preview_res.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.preview_audio = tk.Label(
            preview_text,
            textvariable=self.preview_audio_var,
            background=palette.card,
            foreground=palette.text2,
            font=fonts.small,
            anchor="w",
            justify="left",
            height=1,
        )
        self.preview_audio.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.preview_status = tk.Label(
            preview_text,
            textvariable=self.preview_status_var,
            background=palette.card,
            foreground=palette.red,
            font=fonts.small,
            anchor="w",
            justify="left",
            height=1,
        )
        self.preview_status.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.preview_status.grid_remove()

        def resize_preview(event: tk.Event) -> None:
            self.preview_title.configure(wraplength=max(140, event.width - 4))
            self._refresh_preview_title(max(140, event.width - 4))

        preview_text.bind("<Configure>", resize_preview)

        queue_section = tk.Frame(page, background=palette.content)
        queue_section.grid(row=3, column=0, sticky="ew")
        queue_section.columnconfigure(0, weight=1)
        queue_header = tk.Frame(queue_section, background=palette.content)
        queue_header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 6))
        queue_header.columnconfigure(0, weight=1)
        tk.Label(
            queue_header,
            textvariable=self.queue_count_var,
            background=palette.content,
            foreground=palette.text2,
            font=fonts.section,
        ).grid(row=0, column=0, sticky="w")
        self.clear_button = RoundedButton(
            queue_header,
            "Clear Finished",
            style="link",
            background=palette.content,
            command=self._clear_finished,
        )
        self.clear_button.grid(row=0, column=1, sticky="e")

        self.queue_card = Card(queue_section, padding=(2, 2), background=palette.content)
        self.queue_card.grid(row=1, column=0, sticky="ew")
        self.queue_view = QueueView(
            self.queue_card.body,
            on_cancel=self._cancel_job,
            on_retry=self._retry_job,
            on_restart=self._restart_job,
            on_remove=self._remove_job,
            on_open=self._open_job_folder,
        )
        self.queue_view.pack(fill="x")

        status = tk.Frame(root, background=palette.content, height=30)
        status.grid(row=1, column=0, sticky="ew")
        status.grid_propagate(False)
        self.status_label = tk.Label(
            status,
            textvariable=self.status_var,
            background=palette.content,
            foreground=palette.text2,
            font=fonts.small,
            anchor="w",
        )
        self.status_label.pack_forget()

        self._narrow_url: bool | None = None
        self._narrow_grid: bool | None = None
        page.bind("<Configure>", self._on_page_resize, add="+")
        self.options_card.bind(
            "<Configure>",
            lambda _event: self._sync_stacked_preview_height(),
            add="+",
        )
        self.root.after_idle(
            lambda: self._apply_responsive_layout(self.page.inner.winfo_width())
        )

        self.url_entry.bind("<Return>", lambda _event: self._add_download())
        self.url_entry.bind("<Control-Return>", lambda _event: self._start_preview())

    def _shortcut_chip(
        self,
        parent: tk.Widget,
        keys: str,
        label: str,
        *,
        padx: tuple[int, int] = (0, 0),
    ) -> None:
        palette = self.palette
        chip = tk.Label(
            parent,
            text=keys,
            background=palette.fill,
            foreground=palette.text2,
            font=self.fonts.tiny,
            padx=5,
            pady=1,
        )
        chip.pack(side="left", padx=padx)
        tk.Label(
            parent,
            text=label,
            background=palette.content,
            foreground=palette.text2,
            font=self.fonts.small,
        ).pack(side="left", padx=(5, 0))

    def _on_page_resize(self, event: tk.Event) -> None:
        self._apply_responsive_layout(event.width)

    def _apply_responsive_layout(self, width: int) -> None:
        if width < 200:
            return
        url_narrow = width < URL_STACK_WIDTH
        grid_narrow = width < GRID_STACK_WIDTH

        if url_narrow != self._narrow_url:
            self._narrow_url = url_narrow
            if url_narrow:
                self.url_field.grid_configure(
                    row=0, column=0, columnspan=2, sticky="ew"
                )
                self.preview_button.grid_configure(
                    row=1, column=0, sticky="ew", padx=(0, 5), pady=(8, 0)
                )
                self.download_button.grid_configure(
                    row=1, column=1, sticky="ew", padx=(5, 0), pady=(8, 0)
                )
                self.url_row.columnconfigure(0, weight=1)
                self.url_row.columnconfigure(1, weight=1)
                self.url_row.columnconfigure(2, weight=0)
            else:
                self.url_field.grid_configure(
                    row=0, column=0, columnspan=1, sticky="ew"
                )
                self.preview_button.grid_configure(
                    row=0, column=1, sticky="", padx=(10, 0), pady=0
                )
                self.download_button.grid_configure(
                    row=0, column=2, sticky="", padx=(10, 0), pady=0
                )
                self.url_row.columnconfigure(0, weight=1)
                self.url_row.columnconfigure(1, weight=0)
                self.url_row.columnconfigure(2, weight=0)

        if grid_narrow != self._narrow_grid:
            self._narrow_grid = grid_narrow
            if grid_narrow:
                self.options_column.grid_configure(
                    row=0, column=0, columnspan=2, sticky="nsew", padx=0, pady=0
                )
                self.preview_column.grid_configure(
                    row=1, column=0, columnspan=2, sticky="nsew", padx=0, pady=(14, 0)
                )
                self.grid_section.columnconfigure(0, weight=1, minsize=0)
                self.grid_section.columnconfigure(1, weight=0, minsize=0)
            else:
                self.options_column.grid_configure(
                    row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 20), pady=0
                )
                self.preview_column.grid_configure(
                    row=0, column=1, columnspan=1, sticky="nsew", padx=0, pady=0
                )
                self.grid_section.columnconfigure(0, weight=0, minsize=440)
                self.grid_section.columnconfigure(1, weight=1, minsize=0)

        self._sync_stacked_preview_height()

    def _sync_stacked_preview_height(self) -> None:
        if self._narrow_grid:
            height = max(138, self.options_card.winfo_height())
            if height > 1 and self.preview_card.winfo_height() != height:
                self.preview_card.configure(height=height)
        else:
            try:
                current = int(self.preview_card.cget("height"))
            except (ValueError, tk.TclError):
                current = 0
            if current != 1:
                self.preview_card.configure(height=1)

    def _paste_url(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self._show_input_error("The clipboard is empty.")
            return
        self.url_var.set(text.strip())
        self._clear_input_error()
        try:
            self.url_entry.icursor("end")
            self.url_entry.focus_set()
        except tk.TclError:
            pass

    def _show_preview_empty(self) -> None:
        self.preview_detail.grid_remove()
        self.preview_empty.grid()

    def _show_preview_detail(self) -> None:
        self.preview_empty.grid_remove()
        self.preview_detail.grid()

    def _refresh_preview_title(self, width: int | None = None) -> None:
        if width is None:
            parent = self.preview_title.master
            width = max(140, (parent.winfo_width() or self.preview_title.winfo_width()) - 4)
        words = (self._preview_full_title or "").split()
        if not words:
            self.preview_title_var.set("")
            return
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if not current or self.fonts.base_bold.measure(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) <= 2:
            self.preview_title_var.set("\n".join(lines))
            return
        second = lines[1]
        while second and self.fonts.base_bold.measure(second + "…") > width and " " in second:
            second = second.rsplit(" ", 1)[0]
        self.preview_title_var.set(lines[0] + "\n" + second.rstrip(" ,.;:") + "…")

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
            self.quality_static.grid_remove()
            self.quality_combo.grid()
            self.quality_note.configure(
                text="Source quality. Separate video and audio streams are merged into MKV without re-encoding."
            )
        elif mode == "audio":
            self.quality_label.configure(text="Audio quality")
            self.quality_combo.grid_remove()
            self.quality_static.configure(text="Original codec")
            self.quality_static.grid()
            self.quality_note.configure(
                text="Best available source audio, kept in its original codec (typically Opus or AAC). No lossy conversion."
            )
        else:
            self.quality_label.configure(text="Audio conversion")
            self.quality_combo.grid_remove()
            self.quality_static.configure(text="MP3 V0")
            self.quality_static.grid()
            self.quality_note.configure(
                text="Converts the best source audio to MP3 V0 VBR (~245 kbps). This conversion is lossy."
            )
        self._update_action_states()

    def _update_action_states(self) -> None:
        has_url = bool(self.url_var.get().strip())
        available = self.dependencies.has_ytdlp
        can_download = has_url and available
        self.download_button.configure(
            state="normal" if can_download else "disabled",
            image=load_icon("download") if can_download else load_icon("download-muted"),
        )
        self.preview_button.configure(
            state="normal" if has_url and available and self.preview_handle is None else "disabled"
        )
        folder = self._current_folder()
        can_open = folder is not None and folder_is_usable(folder)
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
        self.preview_status.grid_remove()
        self._preview_full_title = "Fetching information…"
        self._refresh_preview_title()
        self.preview_meta_var.set(truncate_text(url, 34))
        self.preview_res_var.set("")
        self.preview_audio_var.set("")
        self.preview_button.configure(text="Fetching…", state="disabled")
        self._show_preview_detail()
        self.root.after_idle(self._refresh_preview_title)
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
        self._show_preview_detail()
        if not info.thumbnail_url:
            self.thumb_label.configure(image="", text="No preview")
        self._preview_full_title = info.display_title
        self._refresh_preview_title()
        self.root.after_idle(self._refresh_preview_title)
        details = []
        if info.uploader:
            details.append(info.uploader)
        if info.duration is not None:
            details.append(format_duration(info.duration))
        if info.extractor:
            details.append(info.extractor.replace("Youtube", "YouTube"))
        meta = "  ·  ".join(details) if details else "Information from the site"
        self.preview_meta_var.set(truncate_text(meta, 34))
        summary = info.summary
        self.preview_res_var.set(truncate_text(f"Video: {summary.resolution_text}", 34))
        self.preview_audio_var.set(truncate_text(f"Audio: {summary.audio_text}", 34))
        self.preview_status_var.set("")
        self.preview_status.grid_remove()
        self.logger.info("Preview ready: %s", info.display_title)

    def _handle_preview_thumb(self, generation: int, path: Path | None) -> None:
        if generation != self.preview_generation:
            return
        if path is None:
            self.thumb_label.configure(image="", text="No preview")
            return
        try:
            image = tk.PhotoImage(file=str(path))
            if self.preview_url:
                self._job_thumbnails[self.preview_url] = image
            factor = max(1, (image.width() + 159) // 160, (image.height() + 89) // 90)
            self._thumb_photo = image.subsample(factor, factor)
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
        self._show_preview_detail()
        self._preview_full_title = "Preview unavailable"
        self._refresh_preview_title()
        self.preview_meta_var.set("")
        self.preview_status_var.set(truncate_text(message, 60))
        self.preview_status.grid()
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
        self._preview_full_title = "No preview yet"
        self._refresh_preview_title()
        self.preview_meta_var.set("Paste a link and choose Preview.")
        self.preview_res_var.set("")
        self.preview_audio_var.set("")
        self.preview_status_var.set("")
        self.preview_status.grid_remove()
        self._show_preview_empty()

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

    def _restart_job(self, job_id: str) -> None:
        if self.queue_manager is not None:
            self.queue_manager.retry(job_id, restart=True)

    def _remove_job(self, job_id: str) -> None:
        if self.queue_manager is not None:
            self.queue_manager.remove(job_id)

    def _clear_finished(self) -> None:
        if self.queue_manager is not None:
            self.queue_manager.clear_finished()

    # ------------------------------------------------------------------ status

    def _sync_queue(self) -> None:
        jobs = self.queue_manager.snapshot() if self.queue_manager is not None else []
        self.queue_view.sync(jobs, self._job_thumbnails)
        count = len(jobs)
        self.queue_count_var.set(
            f"QUEUE · {count} ITEM" if count == 1 else f"QUEUE · {count} ITEMS"
        )
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
        self._update_status_visibility()
        self._update_action_states()

    def _update_status_visibility(self) -> None:
        text = self.status_var.get().strip()
        if not text or text.startswith("Ready"):
            self.status_label.pack_forget()
        elif not self.status_label.winfo_ismapped():
            self.status_label.pack(side="left", padx=(20, 0))

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
            log_path = self.log_state.log_file
            message = "An unexpected error occurred."
            if log_path is not None:
                message = f"{message} See the diagnostic log at {log_path}"
            messagebox.showerror(
                APP_NAME,
                message,
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
        try:
            self.root.destroy()
        except tk.TclError:
            pass
