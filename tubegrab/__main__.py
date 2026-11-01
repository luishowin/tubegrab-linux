"""Command-line entry point for TubeGrab."""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Sequence

from . import APP_NAME, __version__
from .config import AppPaths
from .logging_setup import configure_logging, install_thread_exception_hook


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tubegrab",
        description="Download video and audio with yt-dlp and FFmpeg.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="optional video URL to place in the link field on startup",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = AppPaths.from_env()
    log_state = configure_logging(paths)
    logger = log_state.logger
    install_thread_exception_hook(logger)

    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        message = (
            f"{APP_NAME} requires Python with Tkinter. "
            "On Fedora, install it with: sudo dnf install python3-tkinter"
        )
        logger.error(message)
        print(message, file=sys.stderr)
        return 1

    try:
        root = tk.Tk(className="TubeGrab")
    except tk.TclError as exc:
        logger.error("Could not open a graphical display: %s", exc)
        print(
            f"{APP_NAME} needs a graphical desktop session. "
            f"Start it from your desktop or run it with a working DISPLAY/WAYLAND_DISPLAY.",
            file=sys.stderr,
        )
        return 1

    try:
        from .app import TubeGrabApp

        app = TubeGrabApp(root, paths, logger, log_state)
        dependencies = app.dependencies
        logger.info(
            "%s %s started (yt-dlp=%s, ffmpeg=%s)",
            APP_NAME,
            __version__,
            dependencies.ytdlp_version or dependencies.ytdlp_command or "missing",
            dependencies.ffmpeg or "missing",
        )
        if args.url:
            app.prefill_url(args.url)

        def handle_signal(_signum: int, _frame: object) -> None:
            try:
                root.after(0, lambda: app.request_close(confirm=False))
            except (RuntimeError, tk.TclError):
                pass

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except (ValueError, OSError):
            pass

        root.mainloop()
        return 0
    except Exception:
        logger.exception("TubeGrab failed to start")
        try:
            messagebox.showerror(
                APP_NAME,
                "TubeGrab could not start. See the diagnostic log for details:\n"
                f"{log_state.log_file or paths.state_dir}",
                parent=root,
            )
        except tk.TclError:
            pass
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
