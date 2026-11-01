"""Configuration and XDG path handling for TubeGrab."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from .utils import default_output_dir

LOGGER = logging.getLogger("tubegrab.config")

VALID_MODES = {"video", "audio", "mp3"}
VALID_QUALITIES = {None, 2160, 1440, 1080, 720, 480, 360, 240, 144}
DEFAULT_WIDTH = 1040
DEFAULT_HEIGHT = 700
MIN_WIDTH = 900
MIN_HEIGHT = 620


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    state_dir: Path
    cache_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def log_file(self) -> Path:
        return self.state_dir / "tubegrab.log"

    @property
    def thumbnail_dir(self) -> Path:
        return self.cache_dir / "thumbnails"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AppPaths":
        environment = os.environ if env is None else env
        home = Path(environment.get("HOME") or Path.home())

        def base(variable: str, fallback: Path) -> Path:
            raw = environment.get(variable, "")
            if raw:
                candidate = Path(raw).expanduser()
                if candidate.is_absolute():
                    return candidate
            return fallback

        return cls(
            config_dir=base("XDG_CONFIG_HOME", home / ".config") / "tubegrab",
            state_dir=base("XDG_STATE_HOME", home / ".local" / "state") / "tubegrab",
            cache_dir=base("XDG_CACHE_HOME", home / ".cache") / "tubegrab",
        )


@dataclass
class Config:
    output_dir: str
    mode: str = "video"
    video_quality: int | None = None
    window_width: int = DEFAULT_WIDTH
    window_height: int = DEFAULT_HEIGHT
    schema_version: int = 1

    @classmethod
    def defaults(cls) -> "Config":
        return cls(output_dir=str(default_output_dir()))

    def normalised(self) -> "Config":
        mode = self.mode if self.mode in VALID_MODES else "video"
        quality = self.video_quality if self.video_quality in VALID_QUALITIES else None
        output_dir = (self.output_dir or "").strip() or str(default_output_dir())
        width = _bounded_int(self.window_width, MIN_WIDTH, 4000, DEFAULT_WIDTH)
        height = _bounded_int(self.window_height, MIN_HEIGHT, 3000, DEFAULT_HEIGHT)
        return replace(
            self,
            output_dir=output_dir,
            mode=mode,
            video_quality=quality,
            window_width=width,
            window_height=height,
            schema_version=1,
        )


def _bounded_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def load_config(path: Path, logger: logging.Logger | None = None) -> Config:
    """Load settings, falling back to defaults when the file is absent or bad."""

    log = logger or LOGGER
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config.defaults()
    except OSError as exc:
        log.warning("Could not read configuration %s: %s", path, exc)
        return Config.defaults()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        log.warning("Configuration %s is invalid (%s); using defaults.", path, exc)
        return Config.defaults()

    if not isinstance(data, dict):
        log.warning("Configuration %s is not an object; using defaults.", path)
        return Config.defaults()

    defaults = Config.defaults()
    config = Config(
        output_dir=data.get("output_dir") if isinstance(data.get("output_dir"), str) else defaults.output_dir,
        mode=data.get("mode") if isinstance(data.get("mode"), str) else defaults.mode,
        video_quality=data.get("video_quality") if isinstance(data.get("video_quality"), int) else None,
        window_width=data.get("window_width", defaults.window_width),
        window_height=data.get("window_height", defaults.window_height),
    )
    return config.normalised()


def save_config(path: Path, config: Config, logger: logging.Logger | None = None) -> bool:
    """Atomically save settings.  Returns ``False`` and logs on failure."""

    log = logger or LOGGER
    data = config.normalised()
    payload = {
        "schema_version": 1,
        "output_dir": data.output_dir,
        "mode": data.mode,
        "video_quality": data.video_quality,
        "window_width": data.window_width,
        "window_height": data.window_height,
    }

    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError as exc:
        log.warning("Could not save configuration %s: %s", path, exc)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return False
