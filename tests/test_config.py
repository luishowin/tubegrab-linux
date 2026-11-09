"""Tests for XDG paths and atomic configuration handling."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tubegrab.config import AppPaths, Config, load_config, save_config


class PathTests(unittest.TestCase):
    def test_from_env_uses_xdg_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_env(
                {
                    "HOME": tmp,
                    "XDG_CONFIG_HOME": str(Path(tmp) / "cfg"),
                    "XDG_STATE_HOME": str(Path(tmp) / "state"),
                    "XDG_CACHE_HOME": str(Path(tmp) / "cache"),
                }
            )
            self.assertEqual(paths.config_dir, Path(tmp) / "cfg" / "tubegrab")
            self.assertEqual(paths.state_dir, Path(tmp) / "state" / "tubegrab")
            self.assertEqual(paths.cache_dir, Path(tmp) / "cache" / "tubegrab")
            self.assertEqual(paths.log_file.name, "tubegrab.log")

    def test_from_env_falls_back_for_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = AppPaths.from_env(
                {"HOME": tmp, "XDG_CONFIG_HOME": "relative", "XDG_STATE_HOME": ""}
            )
            self.assertEqual(paths.config_dir, Path(tmp) / ".config" / "tubegrab")
            self.assertEqual(paths.state_dir, Path(tmp) / ".local/state" / "tubegrab")


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "config.json"

    def test_defaults_when_missing(self) -> None:
        config = load_config(self.path)
        self.assertEqual(config.mode, "video")
        self.assertIsNone(config.video_quality)
        self.assertEqual(config.video_container, "auto")
        self.assertTrue(config.output_dir)
        self.assertGreaterEqual(config.window_width, 900)

    def test_round_trip_and_permissions(self) -> None:
        original = Config(
            output_dir="/tmp/with space/日本語",
            mode="mp3",
            video_quality=1080,
            video_container="mp4",
            window_width=1100,
            window_height=720,
        )
        self.assertTrue(save_config(self.path, original))
        loaded = load_config(self.path)
        self.assertEqual(loaded.output_dir, original.output_dir)
        self.assertEqual(loaded.mode, "mp3")
        self.assertEqual(loaded.video_quality, 1080)
        self.assertEqual(loaded.video_container, "mp4")
        self.assertEqual(loaded.window_width, 1100)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").encode("utf-8")), self.path.stat().st_size)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_json_uses_defaults(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{ this is not json", encoding="utf-8")
        config = load_config(self.path)
        self.assertEqual(config.mode, "video")
        self.assertIsNone(config.video_quality)

    def test_invalid_values_are_sanitized(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "output_dir": "",
                    "mode": "nonsense",
                    "video_quality": 9999,
                    "video_container": "avi",
                    "window_width": 1,
                    "window_height": 999999,
                }
            ),
            encoding="utf-8",
        )
        config = load_config(self.path)
        self.assertEqual(config.mode, "video")
        self.assertIsNone(config.video_quality)
        self.assertEqual(config.video_container, "auto")
        self.assertTrue(config.output_dir)
        self.assertGreaterEqual(config.window_width, 900)
        self.assertLessEqual(config.window_height, 3000)

    def test_non_object_json_uses_defaults(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text('["unexpected"]', encoding="utf-8")
        config = load_config(self.path)
        self.assertEqual(config.mode, "video")

    def test_unwritable_path_returns_false(self) -> None:
        # A path whose parent is a regular file cannot be created.
        not_a_dir = Path(self.temp.name) / "file"
        not_a_dir.write_text("x", encoding="utf-8")
        result = save_config(not_a_dir / "config.json", Config.defaults())
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
