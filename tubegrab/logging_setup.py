"""Logging setup: a rotating file for diagnostics and a small in-app buffer."""

from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import AppPaths

LOGGER_NAME = "tubegrab"


class MemoryLogHandler(logging.Handler):
    """Thread-safe in-memory log buffer used by the Details window."""

    def __init__(self, maximum: int = 1000) -> None:
        super().__init__(level=logging.INFO)
        self._records: deque[str] = deque(maxlen=maximum)
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - defensive logging path
            self.handleError(record)
            return
        with self._lock:
            self._records.append(message)

    def text(self) -> str:
        with self._lock:
            return "\n".join(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class LoggingState:
    def __init__(
        self,
        logger: logging.Logger,
        memory: MemoryLogHandler,
        log_file: Path | None,
    ) -> None:
        self.logger = logger
        self.memory = memory
        self.log_file = log_file


def configure_logging(paths: AppPaths) -> LoggingState:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()

    memory = MemoryLogHandler()
    logger.addHandler(memory)

    log_file: Path | None = paths.log_file
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)
    except OSError as exc:
        log_file = None
        logger.warning("Could not open the log file in %s: %s", paths.state_dir, exc)

    # Keep terminal runs useful for development without duplicating messages in
    # a normal desktop launch (stderr is usually not visible there).
    if sys.stderr is not None and sys.stderr.isatty():
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.INFO)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(stream)

    logger.debug("TubeGrab logging started (file=%s)", log_file)
    return LoggingState(logger=logger, memory=memory, log_file=log_file)


def install_thread_exception_hook(logger: logging.Logger) -> None:
    previous = threading.excepthook

    def hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        logger.error(
            "Unhandled exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if previous is not None:
            previous(args)

    threading.excepthook = hook

