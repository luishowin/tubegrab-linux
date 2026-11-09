"""yt-dlp integration: commands, metadata, progress, cancellation, errors."""

from __future__ import annotations

import glob
import importlib.util
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .utils import (
    AudioFormat,
    FormatSummary,
    OUTPUT_TEMPLATE,
    VALID_CONTAINERS,
    is_relative_to,
    safe_filename,
    summarize_formats,
    validate_url,
)

LOGGER = logging.getLogger("tubegrab.downloader")

PROGRESS_PREFIX = "@TGPROG@"
OUTPUT_PREFIX = "@TGOUT@"
PROGRESS_TEMPLATE = (
    "download:"
    + PROGRESS_PREFIX
    + "%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    "%(progress.total_bytes_estimate)s|%(progress.fragment_index)s|"
    "%(progress.fragment_count)s|%(progress.speed)s|%(progress.eta)s|"
    "%(info.format_id)s|%(info.vcodec)s|%(info.acodec)s|%(info.height)s"
)
METADATA_TIMEOUT = 60.0
THUMBNAIL_TIMEOUT = 20.0
THUMBNAIL_MAX_BYTES = 8 * 1024 * 1024
METADATA_FLAGS = (
    "--dump-single-json",
    "--skip-download",
    "--no-playlist",
    "--no-colors",
    "--playlist-items",
    "1",
    "--socket-timeout",
    "15",
    "--retries",
    "2",
)
COMMON_DOWNLOAD_FLAGS = (
    "--no-playlist",
    "--playlist-items",
    "1",
    "--newline",
    "--no-colors",
    "--no-quiet",
    "--no-overwrites",
    "--socket-timeout",
    "20",
    "--retries",
    "10",
    "--fragment-retries",
    "10",
    "--progress-template",
    PROGRESS_TEMPLATE,
    "--print",
    f"after_move:{OUTPUT_PREFIX}%(filepath)s",
    "-o",
    OUTPUT_TEMPLATE,
)


class DownloadCancelled(Exception):
    message = "Download cancelled."


class DownloadError(Exception):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail

    @property
    def user_message(self) -> str:
        return str(self)


@dataclass(frozen=True)
class DependencyStatus:
    ytdlp_command: list[str] | None
    ffmpeg: str | None
    ffprobe: str | None
    ytdlp_version: str | None = None
    js_runtime: str | None = None
    js_runtimes_supported: bool = False

    @property
    def has_ytdlp(self) -> bool:
        return bool(self.ytdlp_command)

    @property
    def has_ffmpeg(self) -> bool:
        return bool(self.ffmpeg)


@dataclass(frozen=True)
class MediaInfo:
    url: str
    title: str | None = None
    uploader: str | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    extractor: str | None = None
    webpage_url: str | None = None
    heights: list[int] = field(default_factory=list)
    audio: list[AudioFormat] = field(default_factory=list)
    video_codecs: list[str] = field(default_factory=list)
    containers: list[str] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        return self.title or self.url

    @property
    def summary(self) -> FormatSummary:
        return FormatSummary(
            heights=list(self.heights),
            audio=list(self.audio),
            video_codecs=list(self.video_codecs),
            containers=list(self.containers),
        )


@dataclass(frozen=True)
class ProgressUpdate:
    percent: float | None
    phase: str
    speed: float | None = None
    eta: float | None = None
    indeterminate: bool = False


@dataclass(frozen=True)
class DownloadResult:
    final_path: Path | None
    already_exists: bool = False
    message: str = "Download complete."


def _candidate_executables(name: str) -> list[str]:
    candidates: list[str] = []
    found = shutil.which(name)
    if found:
        candidates.append(found)
    for location in (
        Path("/usr/bin") / name,
        Path("/usr/local/bin") / name,
        Path.home() / ".local" / "bin" / name,
    ):
        text = str(location)
        if text not in candidates and location.is_file() and os.access(location, os.X_OK):
            candidates.append(text)
    return candidates


def find_ytdlp_command() -> list[str] | None:
    override = os.environ.get("TUBEGRAB_YTDLP", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return [str(path)]
        LOGGER.warning("TUBEGRAB_YTDLP is set but is not executable: %s", override)

    for candidate in _candidate_executables("yt-dlp"):
        return [candidate]
    # The Python module is a useful fallback for pip/pipx installations and for
    # development environments where only the module is on this interpreter.
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return None


def find_ffmpeg() -> str | None:
    for candidate in _candidate_executables("ffmpeg"):
        return candidate
    return None


def find_ffprobe() -> str | None:
    for candidate in _candidate_executables("ffprobe"):
        return candidate
    return None


def find_js_runtime() -> str | None:
    """Return a yt-dlp EJS runtime descriptor such as ``node:/usr/bin/node``."""

    override = os.environ.get("TUBEGRAB_JS_RUNTIME", "").strip()
    if override:
        return override
    for name in ("deno", "node", "bun"):
        found = shutil.which(name)
        if found:
            return f"{name}:{found}"
    # GNOME's launch environment often omits version-manager shims, so look in
    # the usual per-user tool directories as a fallback.
    patterns = (
        ("node", "~/.local/share/mise/installs/node/*/bin/node"),
        ("node", "~/.nvm/versions/node/*/bin/node"),
        ("bun", "~/.bun/bin/bun"),
        ("deno", "~/.deno/bin/deno"),
    )
    for name, pattern in patterns:
        matches = sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)
        for match in matches:
            if os.path.isfile(match) and os.access(match, os.X_OK):
                return f"{name}:{match}"
    return None


def supports_js_runtimes(command: list[str] | None) -> bool:
    if not command:
        return False
    try:
        result = subprocess.run(
            [*command, "--help"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "--js-runtimes" in (result.stdout or "")


def _tool_version(command: list[str] | None) -> str | None:
    if not command:
        return None
    try:
        result = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    first = (result.stdout or "").strip().splitlines()
    return first[0].strip() if first else None


def detect_dependencies() -> DependencyStatus:
    ytdlp = find_ytdlp_command()
    js_runtime = find_js_runtime()
    return DependencyStatus(
        ytdlp_command=ytdlp,
        ffmpeg=find_ffmpeg(),
        ffprobe=find_ffprobe(),
        ytdlp_version=_tool_version(ytdlp),
        js_runtime=js_runtime,
        js_runtimes_supported=bool(js_runtime) and supports_js_runtimes(ytdlp),
    )


def mode_requires_ffmpeg(mode: str) -> bool:
    return mode in {"video", "mp3"}


def build_metadata_command(
    command: list[str],
    url: str,
    js_runtime: str | None = None,
) -> list[str]:
    args = [*command, *METADATA_FLAGS]
    if js_runtime:
        args.extend(["--js-runtimes", js_runtime])
    args.extend(["--", url])
    return args


def build_download_command(
    command: list[str],
    mode: str,
    quality: int | None,
    output_dir: Path,
    url: str,
    js_runtime: str | None = None,
    restart: bool = False,
    container: str = "auto",
) -> list[str]:
    """Build a download command as an argument list (never a shell string)."""

    if mode not in {"video", "audio", "mp3"}:
        raise ValueError(f"Unknown download mode: {mode}")
    if quality is not None and quality not in {2160, 1440, 1080, 720, 480, 360, 240, 144}:
        raise ValueError(f"Unsupported video quality: {quality}")
    if container not in VALID_CONTAINERS:
        raise ValueError(f"Unsupported video container: {container}")

    args = [*command, *COMMON_DOWNLOAD_FLAGS]
    if js_runtime:
        args.extend(["--js-runtimes", js_runtime])
    if restart:
        args.append("--no-continue")
    args.extend(["-P", str(output_dir)])
    if mode == "video":
        height = "" if quality is None else f"[height<={quality}]"
        fallback = f"bv*{height}+ba/b{height}"
        if container == "mp4":
            selector = f"bv*[ext=mp4]{height}+ba[ext=m4a]/{fallback}"
            merge_format = "mp4/mkv"
        elif container == "webm":
            selector = f"bv*[ext=webm]{height}+ba[ext=webm]/{fallback}"
            merge_format = "webm/mkv"
        else:
            selector = fallback
            merge_format = "mkv"
        args.extend(["-f", selector, "--merge-output-format", merge_format])
    elif mode == "audio":
        # "best" extracts the source audio without a lossy conversion.
        args.extend(["-f", "ba/b", "-x", "--audio-format", "best"])
    else:
        args.extend(
            [
                "-f",
                "ba/b",
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
            ]
        )
    args.extend(["--", url])
    return args


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def parse_progress_line(line: str) -> ProgressUpdate | None:
    """Parse one machine-readable progress line from yt-dlp."""

    if not line.startswith(PROGRESS_PREFIX):
        return None
    payload = line[len(PROGRESS_PREFIX) :]
    fields = payload.split("|")
    if len(fields) < 11:
        return None
    fields += [""] * (12 - len(fields))
    status = fields[0].strip().lower()
    downloaded = _number(fields[1])
    total = _number(fields[2]) or _number(fields[3])
    fragment_index = _number(fields[4])
    fragment_count = _number(fields[5])
    speed = _number(fields[6])
    eta = _number(fields[7])
    vcodec = fields[9].strip().lower()
    acodec = fields[10].strip().lower()
    height = _number(fields[11])

    video = vcodec not in {"", "none", "na"}
    audio = acodec not in {"", "none", "na"}
    if video and not audio:
        phase = f"Video · {int(height)}p" if height else "Video stream"
    elif audio and not video:
        phase = "Audio stream"
    else:
        phase = "Downloading"

    percent: float | None = None
    if total and downloaded is not None and total > 0:
        percent = max(0.0, min(100.0, downloaded / total * 100.0))
    elif fragment_index is not None and fragment_count and fragment_count > 0:
        percent = max(0.0, min(100.0, fragment_index / fragment_count * 100.0))
    if status == "finished":
        percent = 100.0
    return ProgressUpdate(
        percent=percent,
        phase=phase,
        speed=speed,
        eta=eta,
        indeterminate=percent is None,
    )


def parse_media_info(data: object, requested_url: str) -> MediaInfo:
    if not isinstance(data, dict):
        raise DownloadError("The site returned video information in an unexpected format.")

    entries = data.get("entries")
    if data.get("_type") == "playlist" and isinstance(entries, list):
        first = next((entry for entry in entries if isinstance(entry, dict)), None)
        if first is None:
            raise DownloadError("This playlist does not contain a downloadable video.")
        data = first

    title = data.get("title") if isinstance(data.get("title"), str) else None
    title = title.strip() if title and title.strip() else None
    uploader = None
    for key in ("uploader", "channel", "creator", "uploader_id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            uploader = value.strip()
            break
    duration = _number(data.get("duration"))

    thumbnail_url: str | None = None
    candidates = [data.get("thumbnail")]
    thumbnails = data.get("thumbnails")
    if isinstance(thumbnails, list):
        candidates.extend(
            item.get("url") for item in thumbnails if isinstance(item, dict)
        )
    for candidate in candidates:
        if isinstance(candidate, str):
            try:
                parts = urlsplit(candidate)
            except ValueError:
                continue
            if parts.scheme in {"http", "https"} and parts.netloc:
                thumbnail_url = candidate
                break

    summary = summarize_formats(data.get("formats"))
    extractor = data.get("extractor_key") or data.get("extractor")
    if not isinstance(extractor, str) or not extractor.strip():
        extractor = None
    webpage_url = data.get("webpage_url")
    if not isinstance(webpage_url, str) or not webpage_url:
        webpage_url = requested_url

    return MediaInfo(
        url=requested_url,
        title=title,
        uploader=uploader,
        duration=duration,
        thumbnail_url=thumbnail_url,
        extractor=extractor,
        webpage_url=webpage_url,
        heights=summary.heights,
        audio=summary.audio,
        video_codecs=summary.video_codecs,
        containers=summary.containers,
    )


def _last_error_line(detail: str) -> str:
    lines = [line.strip() for line in (detail or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.upper().startswith("ERROR:"):
            return line[6:].strip()
    return lines[-1] if lines else ""


def map_error(detail: str, mode: str | None = None) -> str:
    """Turn yt-dlp's diagnostic output into a concise user-facing message."""

    text = (detail or "").lower()
    last = _last_error_line(detail)

    def result(message: str) -> str:
        if last and last.lower() not in message.lower():
            return f"{message} ({last[:180]})"
        return message

    if "private video" in text or "this video is private" in text:
        return "This video is private."
    if "sign in to confirm your age" in text or "age-restricted" in text or "age restricted" in text:
        return "This video is age-restricted and requires sign-in. TubeGrab does not bypass access controls."
    if "confirm you're not a bot" in text or "confirm you are not a bot" in text or "not a bot" in text:
        return "The site requires a sign-in or bot check for this video. TubeGrab does not bypass access controls."
    if "members-only" in text or "join this channel" in text:
        return "This video is available to channel members only."
    if "drm" in text or "protected by drm" in text:
        return "This video is DRM-protected and cannot be downloaded with yt-dlp."
    if "this video is unavailable" in text or "video unavailable" in text or "has been removed" in text:
        return "This video is unavailable or has been removed."
    if "unsupported url" in text or "no suitable extractor" in text:
        return "This link is not supported by yt-dlp."
    if "is not a valid url" in text or "invalid url" in text:
        return "That does not look like a valid video URL."
    if "http error 404" in text or "not found" in text and "http" in text:
        return "The site could not find that page (HTTP 404)."
    if "http error 403" in text or "forbidden" in text:
        return "The site refused access to this video (HTTP 403)."
    if "no space left" in text:
        return "There is not enough free disk space in the download folder."
    if "permission denied" in text:
        return "TubeGrab cannot write to the download folder. Choose another folder."
    if ("ffmpeg" in text or "ffprobe" in text) and "not found" in text:
        return "FFmpeg was not found. Install it with: sudo dnf install ffmpeg-free"
    if "unknown encoder" in text or "conversion failed" in text or "postprocessing" in text:
        return (
            "Postprocessing failed. The installed FFmpeg may lack the required codec; "
            "try original-format audio or a full FFmpeg build."
        )
    if "requested format is not available" in text:
        return "The selected quality is not available for this video. Try another quality."
    if "unable to download webpage" in text or "urlopen error" in text:
        return "Could not reach the site. Check your internet connection."
    if (
        "name or service not known" in text
        or "temporary failure in name resolution" in text
        or "getaddrinfo" in text
    ):
        return "Could not resolve the site. Check your internet connection."
    if "timed out" in text or "timeout" in text:
        return "The download timed out. Check your connection and try again."
    if (
        "got error" in text
        or "giving up after" in text
        or "more expected" in text
        or "unable to download video data" in text
        or "content too short" in text
    ):
        return (
            "The server interrupted the transfer. Try Start over to discard the "
            "partial file and download again."
        )
    if "this live event will begin" in text or "premieres in" in text:
        return "This live stream has not started yet."
    if "no video formats found" in text or "no formats found" in text:
        return "No downloadable formats were found for this video."
    if "playlist" in text and "does not contain" in text:
        return "This playlist does not contain a downloadable item."

    fallback = "Download failed."
    if mode == "mp3":
        fallback = "Could not convert or download the audio."
    if last:
        return result(fallback)
    return fallback


class ProcessHandle:
    """Owns one subprocess inside a new process group and cancels it safely."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._kill_timer: threading.Timer | None = None

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def attach(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._process = process
            cancelled = self._cancelled
        if cancelled:
            self._signal(process, signal.SIGTERM)
            self._schedule_force_kill(process)

    def detach(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._process is process:
                self._process = None
            timer = self._kill_timer
            self._kill_timer = None
        if timer is not None:
            timer.cancel()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            process = self._process
        if process is None or process.poll() is not None:
            return
        self._signal(process, signal.SIGTERM)
        self._schedule_force_kill(process)

    def _schedule_force_kill(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._kill_timer is not None:
                return
            timer = threading.Timer(4.0, self._force_kill, args=(process,))
            timer.daemon = True
            self._kill_timer = timer
            timer.start()

    def _force_kill(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            self._signal(process, signal.SIGKILL)

    @staticmethod
    def _signal(process: subprocess.Popen[str], sig: int) -> None:
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(process.pid), sig)
            else:  # pragma: no cover - TubeGrab targets Linux
                process.kill() if sig == signal.SIGKILL else process.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _cleanup_partial_files(destinations: set[Path], output_dir: Path) -> None:
    for destination in destinations:
        if not is_relative_to(destination, output_dir):
            continue
        candidates: list[Path] = [destination]
        parent = destination.parent
        try:
            candidates.extend(parent.glob(destination.name + ".part*"))
            candidates.append(parent / (destination.name + ".ytdl"))
        except OSError:
            continue
        for path in candidates:
            try:
                if path.is_file() and is_relative_to(path, output_dir):
                    path.unlink()
                    LOGGER.info("Removed partial file %s", path)
            except OSError as exc:
                LOGGER.warning("Could not remove partial file %s: %s", path, exc)


class YtDlpDownloader:
    """Stateless facade around the yt-dlp executable/module."""

    def __init__(
        self,
        command: list[str],
        ffmpeg: str | None,
        logger: logging.Logger | None = None,
        js_runtime: str | None = None,
    ) -> None:
        self.command = list(command)
        self.ffmpeg = ffmpeg
        self.logger = logger or LOGGER
        self.js_runtime = js_runtime

    def fetch_info(self, url: str, handle: ProcessHandle | None = None) -> MediaInfo:
        validated = validate_url(url)
        handle = handle or ProcessHandle()
        args = build_metadata_command(self.command, validated, self.js_runtime)
        self.logger.info("Fetching information for %s", validated)
        self.logger.debug("Metadata command: %s", args)
        stdout, stderr, returncode = self._run_capture(args, handle, METADATA_TIMEOUT)
        if handle.cancelled:
            raise DownloadCancelled()
        if returncode != 0:
            detail = stderr or stdout
            self.logger.warning("Metadata extraction failed (%s): %s", returncode, detail.strip())
            raise DownloadError(map_error(detail), detail=detail)
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            self.logger.error("Invalid metadata JSON: %s", exc)
            raise DownloadError(
                "The site returned video information that TubeGrab could not read.",
                detail=stdout[-2000:],
            ) from exc
        return parse_media_info(data, validated)

    def _run_capture(
        self,
        args: list[str],
        handle: ProcessHandle,
        timeout: float,
    ) -> tuple[str, str, int]:
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_subprocess_env(),
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise DownloadError(
                "yt-dlp could not be started. Reinstall it or check the application log."
            ) from exc
        except OSError as exc:
            raise DownloadError(f"Could not start yt-dlp: {exc}") from exc

        handle.attach(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                handle.cancel()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    ProcessHandle._signal(process, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                raise DownloadError(
                    "Fetching video information timed out. Check your connection and try again.",
                    detail=(stderr or "") + (stdout or ""),
                ) from exc
        finally:
            handle.detach(process)
            if process.poll() is None:
                ProcessHandle._signal(process, signal.SIGKILL)
        if stderr:
            self.logger.debug("yt-dlp metadata stderr:\n%s", stderr.strip())
        return stdout or "", stderr or "", process.returncode or 0

    def download(
        self,
        url: str,
        mode: str,
        quality: int | None,
        output_dir: Path,
        handle: ProcessHandle | None = None,
        on_progress: Callable[[ProgressUpdate], None] | None = None,
        restart: bool = False,
        container: str = "auto",
    ) -> DownloadResult:
        validated = validate_url(url)
        if mode in {"video", "mp3"} and not self.ffmpeg:
            raise DownloadError(
                "FFmpeg is required for video merging and MP3 conversion. "
                "Install it with: sudo dnf install ffmpeg-free"
            )

        handle = handle or ProcessHandle()
        args = build_download_command(
            self.command,
            mode,
            quality,
            output_dir,
            validated,
            js_runtime=self.js_runtime,
            restart=restart,
            container=container,
        )
        if self.ffmpeg:
            marker = args.index("--") if "--" in args else len(args)
            args[marker:marker] = ["--ffmpeg-location", self.ffmpeg]
        self.logger.info(
            "Starting %s download to %s (quality=%s, container=%s, restart=%s, url=%s)",
            mode,
            output_dir,
            quality or "best",
            container,
            restart,
            validated,
        )
        self.logger.debug("Download command: %s", args)

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_subprocess_env(),
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise DownloadError(
                "yt-dlp could not be started. Reinstall it or check the application log."
            ) from exc
        except OSError as exc:
            raise DownloadError(f"Could not start yt-dlp: {exc}") from exc

        handle.attach(process)
        destinations: set[Path] = set()
        tail: list[str] = []
        final_path: Path | None = None
        already_exists = False

        def emit(update: ProgressUpdate) -> None:
            if on_progress is not None:
                try:
                    on_progress(update)
                except Exception:
                    self.logger.exception("Progress callback failed")

        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(PROGRESS_PREFIX):
                    update = parse_progress_line(line)
                    if update is not None:
                        emit(update)
                    continue

                self.logger.debug("yt-dlp: %s", line)
                tail.append(line)
                if len(tail) > 80:
                    del tail[:40]

                if line.startswith(OUTPUT_PREFIX):
                    value = line[len(OUTPUT_PREFIX) :].strip()
                    if value:
                        final_path = Path(value)
                    continue
                if "has already been downloaded" in line:
                    already_exists = True
                    match = re.search(r"\[download\]\s+(.+?)\s+has already been downloaded", line)
                    if match:
                        final_path = Path(match.group(1))
                    continue
                destination_match = re.match(r"\[download\]\s+Destination:\s+(.+)$", line)
                if destination_match:
                    destinations.add(Path(destination_match.group(1)))
                    continue
                if "[Merger]" in line and "Merging formats into" in line:
                    match = re.search(r'Merging formats into "(?P<path>.+)"', line)
                    if match:
                        final_path = Path(match.group("path"))
                    emit(ProgressUpdate(percent=None, phase="Merging video and audio…", indeterminate=True))
                    continue
                if "[ExtractAudio]" in line:
                    emit(ProgressUpdate(percent=None, phase="Converting audio…", indeterminate=True))
                    continue
                if "[VideoConvertor]" in line or "[VideoRemuxer]" in line:
                    emit(ProgressUpdate(percent=None, phase="Processing video…", indeterminate=True))

            returncode = process.wait()
        finally:
            handle.detach(process)
            if process.poll() is None:
                ProcessHandle._signal(process, signal.SIGKILL)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass

        if handle.cancelled:
            if returncode == 0 and final_path is not None and final_path.exists():
                # Cancellation arrived at the very end; keeping a valid finished
                # file is safer than deleting a complete download.
                return DownloadResult(
                    final_path=final_path,
                    already_exists=already_exists,
                    message="Download completed just as cancellation was requested.",
                )
            _cleanup_partial_files(destinations, output_dir)
            raise DownloadCancelled()

        if returncode != 0:
            detail = "\n".join(tail)
            self.logger.warning("Download failed (%s): %s", returncode, detail[-3000:])
            raise DownloadError(map_error(detail, mode), detail=detail)

        if already_exists:
            message = "Already downloaded; the existing file was left untouched."
        else:
            message = "Download complete."
        if final_path is not None:
            self.logger.info("Saved %s", final_path)
        else:
            self.logger.warning("yt-dlp finished without reporting a final file path")
        return DownloadResult(
            final_path=final_path,
            already_exists=already_exists,
            message=message,
        )


def fetch_thumbnail(
    info: MediaInfo,
    cache_dir: Path,
    ffmpeg: str | None,
    logger: logging.Logger | None = None,
) -> Path | None:
    """Download and convert a thumbnail to PNG for Tk (best effort)."""

    if not info.thumbnail_url or not ffmpeg:
        return None
    log = logger or LOGGER
    import hashlib
    import tempfile
    import urllib.request

    target: Path | None = None
    try:
        key = hashlib.sha256(info.thumbnail_url.encode("utf-8")).hexdigest()[:24]
        cache_dir.mkdir(parents=True, exist_ok=True)
        readable = safe_filename(
            Path(urlsplit(info.thumbnail_url).path).stem, 40, fallback="thumbnail"
        )
        target = cache_dir / f"{key}-{readable}.png"
        if target.is_file() and target.stat().st_size > 0:
            return target

        request = urllib.request.Request(
            info.thumbnail_url,
            headers={"User-Agent": "TubeGrab/1.1 (+https://github.com/yt-dlp/yt-dlp)"},
        )
        with urllib.request.urlopen(request, timeout=THUMBNAIL_TIMEOUT) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > THUMBNAIL_MAX_BYTES:
                log.warning("Thumbnail is too large; skipping.")
                return None
            payload = response.read(THUMBNAIL_MAX_BYTES + 1)
        if len(payload) > THUMBNAIL_MAX_BYTES:
            log.warning("Thumbnail exceeded the size limit; skipping.")
            return None

        suffix = Path(urlsplit(info.thumbnail_url).path).suffix or ".img"
        with tempfile.TemporaryDirectory(prefix="tubegrab-thumb-") as temp_dir:
            source = Path(temp_dir) / f"source{suffix}"
            source.write_bytes(payload)
            output = Path(temp_dir) / "thumbnail.png"
            result = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    "scale=480:270:force_original_aspect_ratio=increase,crop=480:270",
                    "-frames:v",
                    "1",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
                log.warning("Could not convert thumbnail: %s", (result.stderr or "").strip()[:500])
                return None
            temporary_target = cache_dir / f".{target.name}.{os.getpid()}.tmp"
            shutil.copyfile(output, temporary_target)
            os.replace(temporary_target, target)
        return target
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.warning("Could not fetch thumbnail: %s", exc)
        return None


__all__ = [
    "DependencyStatus",
    "DownloadCancelled",
    "DownloadError",
    "DownloadResult",
    "MediaInfo",
    "ProcessHandle",
    "ProgressUpdate",
    "YtDlpDownloader",
    "build_download_command",
    "build_metadata_command",
    "detect_dependencies",
    "fetch_thumbnail",
    "find_ytdlp_command",
    "map_error",
    "mode_requires_ffmpeg",
    "parse_media_info",
    "parse_progress_line",
]
