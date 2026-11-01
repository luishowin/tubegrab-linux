"""Tests for URL validation, formatting, filenames, and metadata summaries."""

from __future__ import annotations

import unittest

from tubegrab.utils import (
    ValidationError,
    format_bytes,
    format_duration,
    format_speed,
    safe_filename,
    summarize_formats,
    truncate_text,
    validate_url,
)


class UrlValidationTests(unittest.TestCase):
    def test_accepts_http_and_https(self) -> None:
        self.assertEqual(
            validate_url("  https://www.youtube.com/watch?v=abc123  "),
            "https://www.youtube.com/watch?v=abc123",
        )
        self.assertEqual(
            validate_url("http://example.com/path?x=1"),
            "http://example.com/path?x=1",
        )

    def test_accepts_unicode_paths(self) -> None:
        self.assertEqual(
            validate_url("https://example.com/vidéo/テスト"),
            "https://example.com/vidéo/テスト",
        )

    def test_rejects_empty_and_scheme_less(self) -> None:
        for value in ("", "   ", "youtube.com/watch?v=x", "//example.com/x"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_url(value)

    def test_rejects_unsafe_schemes(self) -> None:
        for value in (
            "file:///etc/passwd",
            "javascript:alert(1)",
            "ftp://example.com/video",
            "data:text/plain,hello",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_url(value)

    def test_rejects_control_characters_and_spaces(self) -> None:
        for value in (
            "https://example.com/watch?v=a\nb",
            "https://example.com/watch?v=a b",
            "https://example.com/\x00",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    validate_url(value)

    def test_rejects_missing_host_and_too_long(self) -> None:
        with self.assertRaises(ValidationError):
            validate_url("https:///watch?v=x")
        with self.assertRaises(ValidationError):
            validate_url("https://example.com/" + "a" * 5000)


class FormattingTests(unittest.TestCase):
    def test_duration(self) -> None:
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(59), "0:59")
        self.assertEqual(format_duration(60), "1:00")
        self.assertEqual(format_duration(3661), "1:01:01")
        self.assertEqual(format_duration(None), "—")
        self.assertEqual(format_duration("not a number"), "—")
        self.assertEqual(format_duration(-1), "—")

    def test_bytes_and_speed(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1024), "1.0 KiB")
        self.assertEqual(format_bytes(1024 * 1024 * 3.5), "3.5 MiB")
        self.assertEqual(format_speed(None), "")
        self.assertEqual(format_speed(2048), "2.0 KiB/s")
        self.assertEqual(format_bytes("bad"), "—")

    def test_truncate_text(self) -> None:
        self.assertEqual(truncate_text("one  two\nthree"), "one two three")
        self.assertEqual(truncate_text("abcdefghij", 5), "abcd…")
        self.assertEqual(truncate_text("", 5), "")


class FilenameTests(unittest.TestCase):
    def test_preserves_unicode_and_removes_path_separators(self) -> None:
        result = safe_filename("ViDeO: 日本語 / part\\two?")
        self.assertIn("日本語", result)
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)
        self.assertTrue(result)

    def test_removes_control_characters_and_leading_dots(self) -> None:
        result = safe_filename("\x00..hidden\x1f name")
        self.assertFalse(result.startswith("."))
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x1f", result)

    def test_limits_utf8_bytes(self) -> None:
        result = safe_filename("日本語" * 200, max_bytes=50)
        self.assertLessEqual(len(result.encode("utf-8")), 50)
        self.assertTrue(result)

    def test_empty_name_has_fallback(self) -> None:
        self.assertEqual(safe_filename("..."), "untitled")
        self.assertEqual(safe_filename(""), "untitled")


class FormatSummaryTests(unittest.TestCase):
    def test_filters_storyboards_and_deduplicates(self) -> None:
        formats = [
            {"height": 1080, "vcodec": "av01", "acodec": "none", "ext": "mp4", "format_id": "1"},
            {"height": 720, "vcodec": "vp9", "acodec": "none", "ext": "webm", "format_id": "2"},
            {"height": 1080, "vcodec": "vp9", "acodec": "none", "ext": "webm", "format_id": "3"},
            {"height": 90, "vcodec": "none", "acodec": "none", "ext": "mhtml", "format_id": "sb"},
            {"height": 720, "vcodec": "none", "acodec": "opus", "ext": "webm", "abr": 160.2},
            {"height": 720, "vcodec": "none", "acodec": "mp4a", "ext": "m4a", "abr": 128},
            {"vcodec": "none", "acodec": "opus", "ext": "webm", "abr": 128.4},
            "not a format",
        ]
        summary = summarize_formats(formats)
        self.assertEqual(summary.heights, [1080, 720])
        self.assertEqual(len(summary.audio), 2)
        opus = next(item for item in summary.audio if item.codec == "Opus")
        self.assertEqual(opus.bitrate_kbps, 160)
        self.assertIn("1080p", summary.resolution_text)
        self.assertIn("Opus", summary.audio_text)

    def test_missing_formats(self) -> None:
        summary = summarize_formats(None)
        self.assertEqual(summary.heights, [])
        self.assertEqual(summary.audio, [])
        self.assertIn("unavailable", summary.resolution_text.lower())


if __name__ == "__main__":
    unittest.main()
