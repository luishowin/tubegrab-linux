"""Small, dependency-free helpers used by the rest of TubeGrab."""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

MAX_URL_LENGTH = 4096
MAX_FILENAME_BYTES = 150

# yt-dlp handles the real filename sanitising.  This template is deliberately
# defensive: a byte-limited title, the video id for uniqueness, and the real
# extension chosen by yt-dlp/FFmpeg.  The id prevents collisions between
# different videos that happen to have the same title.
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"

VALID_CONTAINERS = {"auto", "mp4", "webm"}

_CODEC_NAMES = {
    "av01": "AV1",
    "av1": "AV1",
    "vp09": "VP9",
    "vp9": "VP9",
    "avc1": "H.264",
    "avc3": "H.264",
    "h264": "H.264",
    "hev1": "HEVC",
    "hvc1": "HEVC",
    "h265": "HEVC",
    "theora": "Theora",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "mp4a": "AAC",
    "aac": "AAC",
    "mp3": "MP3",
    "flac": "FLAC",
    "alac": "ALAC",
    "ac-3": "AC-3",
    "ec-3": "E-AC-3",
    "dts": "DTS",
    "pcm_s16le": "PCM",
    "pcm_s24le": "PCM",
    "none": "Unknown",
}

_VIDEO_CODEC_ORDER = ("AV1", "VP9", "H.264", "HEVC", "Theora")
_CONTAINER_NAMES = {"mp4": "MP4", "webm": "WebM", "mkv": "MKV", "mov": "MOV"}
_CONTAINER_ORDER = ("MP4", "WebM", "MKV", "MOV")


class ValidationError(ValueError):
    """Raised when user input cannot be used safely."""


def validate_url(raw: str) -> str:
    """Return a trimmed, validated HTTP(S) URL or raise :class:`ValidationError`."""

    url = (raw or "").strip()
    if not url:
        raise ValidationError("Paste a video link first.")
    if len(url) > MAX_URL_LENGTH:
        raise ValidationError("That link is too long.")
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValidationError("The link contains control characters.")
    if any(char.isspace() for char in url):
        raise ValidationError("The link must not contain spaces.")

    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError as exc:
        raise ValidationError("That does not look like a valid URL.") from exc

    if parts.scheme.lower() not in {"http", "https"}:
        raise ValidationError("Only http:// and https:// links are supported.")
    if not parts.netloc or not hostname:
        raise ValidationError("The link is missing a site name.")
    if hostname.strip() != hostname or not re.fullmatch(r"[^\s/\\?#@]+", hostname):
        raise ValidationError("The link contains an invalid site name.")
    return url


def format_duration(seconds: object) -> str:
    """Format a duration in seconds as ``M:SS`` or ``H:MM:SS``."""

    try:
        value = float(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value) or value < 0:
        return "—"
    total = int(round(value))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_bytes(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number) or number < 0:
        return "—"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return "—"


def format_speed(value: object) -> str:
    if value is None:
        return ""
    text = format_bytes(value)
    return "" if text == "—" else f"{text}/s"


def truncate_text(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", "ignore").rstrip()


def safe_filename(name: str, max_bytes: int = MAX_FILENAME_BYTES, fallback: str = "untitled") -> str:
    """Make a readable, filesystem-safe single filename component.

    Unicode is preserved.  Path separators, control characters, and characters
    that are troublesome on portable filesystems are replaced.
    """

    value = unicodedata.normalize("NFC", name or "")
    value = "".join(
        " " if char in "/\\" or ord(char) < 32 or ord(char) == 127 else char
        for char in value
    )
    value = value.replace(":", " -").replace("*", "_").replace("?", "_")
    value = value.replace('"', "'").replace("<", "(").replace(">", ")").replace("|", "_")
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = fallback
    value = _truncate_utf8(value, max(1, max_bytes))
    value = value.rstrip(" .")
    return value or fallback


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def codec_name(codec: object) -> str:
    text = str(codec or "").strip().lower()
    if not text or text == "none":
        return ""
    for key, label in _CODEC_NAMES.items():
        if text == key or text.startswith(key):
            return label
    return text.split(".", 1)[0].upper()


@dataclass(frozen=True)
class AudioFormat:
    codec: str
    extension: str
    bitrate_kbps: int | None

    @property
    def label(self) -> str:
        bitrate = f" · {self.bitrate_kbps} kbps" if self.bitrate_kbps else ""
        return f"{self.codec}{bitrate}"


@dataclass
class FormatSummary:
    heights: list[int] = field(default_factory=list)
    audio: list[AudioFormat] = field(default_factory=list)
    video_codecs: list[str] = field(default_factory=list)
    containers: list[str] = field(default_factory=list)

    @property
    def resolution_text(self) -> str:
        if not self.heights:
            return "Resolutions unavailable"
        return ", ".join(f"{height}p" for height in self.heights)

    @property
    def audio_text(self) -> str:
        if not self.audio:
            return "Audio formats unavailable"
        return ", ".join(item.label for item in self.audio[:4])

    @property
    def video_codec_text(self) -> str:
        if not self.video_codecs:
            return "Video codecs unavailable"
        return ", ".join(self.video_codecs)

    @property
    def container_text(self) -> str:
        if not self.containers:
            return "Containers unavailable"
        return ", ".join(self.containers)


def _ordered_values(values: set[str], preference: tuple[str, ...]) -> list[str]:
    result = [item for item in preference if item in values]
    result.extend(sorted(item for item in values if item not in preference))
    return result


def summarize_formats(formats: object) -> FormatSummary:
    summary = FormatSummary()
    if not isinstance(formats, list):
        return summary

    heights: set[int] = set()
    audio_by_key: dict[tuple[str, str], AudioFormat] = {}
    video_codecs: set[str] = set()
    containers: set[str] = set()

    for entry in formats:
        if not isinstance(entry, dict):
            continue
        if entry.get("ext") == "mhtml":  # storyboard / thumbnails
            continue
        vcodec = str(entry.get("vcodec") or "none").lower()
        acodec = str(entry.get("acodec") or "none").lower()
        height = _number(entry.get("height"))
        if height is not None and height >= 144 and vcodec != "none":
            heights.add(int(height))
            codec = codec_name(vcodec)
            if codec:
                video_codecs.add(codec)
            extension = str(entry.get("ext") or "").strip().lower()
            if extension:
                containers.add(_CONTAINER_NAMES.get(extension, extension.upper()))

        if acodec != "none" and vcodec in {"none", ""}:
            codec = codec_name(acodec)
            if not codec:
                continue
            extension = str(entry.get("ext") or "").strip().lower()
            bitrate = _number(entry.get("abr")) or _number(entry.get("tbr"))
            kbps = int(round(bitrate)) if bitrate else None
            key = (codec, extension)
            candidate = AudioFormat(codec=codec, extension=extension, bitrate_kbps=kbps)
            existing = audio_by_key.get(key)
            if existing is None or (candidate.bitrate_kbps or 0) > (existing.bitrate_kbps or 0):
                audio_by_key[key] = candidate

    summary.heights = sorted(heights, reverse=True)
    summary.video_codecs = _ordered_values(video_codecs, _VIDEO_CODEC_ORDER)
    summary.containers = _ordered_values(containers, _CONTAINER_ORDER)
    summary.audio = sorted(
        audio_by_key.values(),
        key=lambda item: (item.bitrate_kbps or 0, item.codec),
        reverse=True,
    )
    return summary


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def default_output_dir() -> Path:
    """Choose a conventional default location without creating it yet."""

    home = Path.home()
    videos = home / "Videos"
    downloads = home / "Downloads"
    if videos.is_dir():
        return videos
    if downloads.is_dir():
        return downloads
    return downloads


def open_path(path: Path) -> tuple[bool, str]:
    """Open a folder/file with the desktop's normal handler.

    Returns ``(ok, error_message)``.  This is intentionally a plain subprocess
    call (never a shell); callers run it from the UI thread only after the user
    explicitly asks for it.
    """

    target = str(path)
    commands: list[list[str]] = []
    xdg_open = shutil.which("xdg-open")
    if xdg_open:
        commands.append([xdg_open, target])
    gio = shutil.which("gio")
    if gio:
        commands.append([gio, "open", target])
    if not commands:
        return False, "No desktop opener (xdg-open or gio) is available."

    last_error = ""
    for command in commands:
        try:
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, ""
        except OSError as exc:
            last_error = str(exc)
    return False, last_error or "Could not open the folder."


def folder_is_usable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
