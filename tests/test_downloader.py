"""Tests for yt-dlp command construction and error/format parsing."""

from __future__ import annotations

import unittest
from pathlib import Path

from tubegrab.downloader import (
    PROGRESS_PREFIX,
    DownloadError,
    build_download_command,
    build_metadata_command,
    map_error,
    parse_media_info,
    parse_progress_line,
)


class CommandTests(unittest.TestCase):
    def test_metadata_command(self) -> None:
        command = build_metadata_command(["/usr/bin/yt-dlp"], "https://example.com/v")
        self.assertIn("--dump-single-json", command)
        self.assertIn("--skip-download", command)
        self.assertIn("--playlist-items", command)
        self.assertEqual(command[-2:], ["--", "https://example.com/v"])

    def test_video_best_uses_mkv_without_forced_mp4(self) -> None:
        command = build_download_command(
            ["yt-dlp"], "video", None, Path("/tmp/videos"), "https://example.com/v"
        )
        self.assertIn("bv*+ba/b", command)
        self.assertIn("--merge-output-format", command)
        self.assertEqual(command[command.index("--merge-output-format") + 1], "mkv")
        self.assertNotIn("mp4", command)
        self.assertIn("--no-overwrites", command)
        self.assertIn("--no-quiet", command)
        self.assertEqual(command[-2:], ["--", "https://example.com/v"])
        template = command[command.index("-o") + 1]
        self.assertIn("%(id)s", template)
        self.assertIn("%(ext)s", template)

    def test_video_quality_is_capped_and_falls_back_at_or_below(self) -> None:
        command = build_download_command(
            ["yt-dlp"], "video", 1080, Path("/tmp/videos"), "https://example.com/v"
        )
        selector = command[command.index("-f") + 1]
        self.assertIn("height<=1080", selector)
        self.assertIn("/b[height<=1080]", selector)
        self.assertNotIn("height<=2160", selector)

    def test_low_quality_selector_is_supported(self) -> None:
        command = build_download_command(
            ["yt-dlp"], "video", 144, Path("/tmp/videos"), "https://example.com/v"
        )
        selector = command[command.index("-f") + 1]
        self.assertIn("height<=144", selector)

    def test_audio_original_does_not_convert_to_mp3(self) -> None:
        command = build_download_command(
            ["yt-dlp"], "audio", None, Path("/tmp/videos"), "https://example.com/v"
        )
        self.assertIn("-x", command)
        self.assertEqual(command[command.index("--audio-format") + 1], "best")
        self.assertNotIn("mp3", command)

    def test_mp3_uses_high_quality_vbr(self) -> None:
        command = build_download_command(
            ["yt-dlp"], "mp3", None, Path("/tmp/videos"), "https://example.com/v"
        )
        self.assertEqual(command[command.index("--audio-format") + 1], "mp3")
        self.assertEqual(command[command.index("--audio-quality") + 1], "0")

    def test_unicode_output_path_is_a_single_argument(self) -> None:
        folder = Path("/tmp/ダウンロード with space")
        command = build_download_command(
            ["yt-dlp"], "video", None, folder, "https://example.com/v"
        )
        self.assertEqual(command[command.index("-P") + 1], str(folder))

    def test_invalid_mode_and_quality_raise(self) -> None:
        with self.assertRaises(ValueError):
            build_download_command(["yt-dlp"], "other", None, Path("/tmp"), "https://e.com")
        with self.assertRaises(ValueError):
            build_download_command(["yt-dlp"], "video", 123, Path("/tmp"), "https://e.com")


class ProgressTests(unittest.TestCase):
    def test_video_progress(self) -> None:
        update = parse_progress_line(
            f"{PROGRESS_PREFIX}downloading|1024|4096|NA|NA|NA|2048|3|137|av01|none|1080"
        )
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.percent, 25.0)
        self.assertIn("Video", update.phase)
        self.assertIn("1080p", update.phase)
        self.assertFalse(update.indeterminate)
        self.assertEqual(update.speed, 2048)

    def test_audio_fragment_progress(self) -> None:
        update = parse_progress_line(
            f"{PROGRESS_PREFIX}downloading|NA|NA|NA|3|10|NA|NA|251|none|opus|NA"
        )
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.percent, 30.0)
        self.assertEqual(update.phase, "Audio stream")

    def test_indeterminate_and_finished(self) -> None:
        update = parse_progress_line(
            f"{PROGRESS_PREFIX}downloading|NA|NA|NA|NA|NA|NA|NA|137|av01|none|NA"
        )
        self.assertIsNotNone(update)
        assert update is not None
        self.assertTrue(update.indeterminate)
        self.assertIsNone(update.percent)

        finished = parse_progress_line(
            f"{PROGRESS_PREFIX}finished|100|100|NA|NA|NA|NA|NA|137|av01|none|720"
        )
        self.assertIsNotNone(finished)
        assert finished is not None
        self.assertEqual(finished.percent, 100.0)

    def test_non_progress_lines_are_ignored(self) -> None:
        self.assertIsNone(parse_progress_line("[download] Destination: foo"))
        self.assertIsNone(parse_progress_line(f"{PROGRESS_PREFIX}too|few"))


class MetadataParsingTests(unittest.TestCase):
    def test_parses_title_uploader_and_formats(self) -> None:
        data = {
            "title": "  A test video  ",
            "uploader": "Example Channel",
            "duration": 125.4,
            "thumbnail": "https://i.example.com/thumb.webp",
            "extractor_key": "Youtube",
            "webpage_url": "https://example.com/v",
            "formats": [
                {"height": 1080, "vcodec": "av01", "acodec": "none", "ext": "mp4"},
                {"height": 720, "vcodec": "vp9", "acodec": "none", "ext": "webm"},
                {"vcodec": "none", "acodec": "opus", "ext": "webm", "abr": 160},
            ],
        }
        info = parse_media_info(data, "https://example.com/v")
        self.assertEqual(info.title, "A test video")
        self.assertEqual(info.uploader, "Example Channel")
        self.assertEqual(info.duration, 125.4)
        self.assertEqual(info.heights, [1080, 720])
        self.assertEqual(info.audio[0].codec, "Opus")
        self.assertEqual(info.extractor, "Youtube")

    def test_missing_title_does_not_fabricate_one(self) -> None:
        info = parse_media_info({"formats": []}, "https://example.com/v")
        self.assertIsNone(info.title)
        self.assertEqual(info.display_title, "https://example.com/v")
        self.assertEqual(info.heights, [])

    def test_playlist_uses_first_entry(self) -> None:
        data = {
            "_type": "playlist",
            "entries": [
                {"title": "First", "formats": []},
                {"title": "Second", "formats": []},
            ],
        }
        info = parse_media_info(data, "https://example.com/list")
        self.assertEqual(info.title, "First")

    def test_invalid_payload_raises(self) -> None:
        with self.assertRaises(DownloadError):
            parse_media_info(None, "https://example.com/v")
        with self.assertRaises(DownloadError):
            parse_media_info({"_type": "playlist", "entries": []}, "https://example.com/list")


class ErrorMappingTests(unittest.TestCase):
    def test_specific_errors(self) -> None:
        cases = {
            "ERROR: [youtube] abc: Private video. Sign in if you've been granted access": "private",
            "ERROR: This video is unavailable": "unavailable",
            "ERROR: Sign in to confirm your age": "age-restricted",
            "ERROR: Sign in to confirm you're not a bot": "bot check",
            "ERROR: Unsupported URL: https://example.com/": "not supported",
            "ERROR: HTTP Error 404: Not Found": "HTTP 404",
            "ERROR: HTTP Error 403: Forbidden": "HTTP 403",
            "ERROR: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in name resolution>": "internet connection",
            "ERROR: Requested format is not available": "quality",
            "ERROR: [Errno 28] No space left on device": "disk space",
            "ERROR: ffmpeg not found": "FFmpeg",
            "ERROR: Postprocessing: Conversion failed!": "postprocessing",
        }
        for detail, expected in cases.items():
            with self.subTest(detail=detail):
                self.assertIn(expected.lower(), map_error(detail).lower())

    def test_unknown_error_includes_a_short_detail(self) -> None:
        message = map_error("ERROR: something unusual happened")
        self.assertIn("Download failed", message)
        self.assertIn("something unusual", message)

    def test_mp3_fallback_wording(self) -> None:
        self.assertIn("audio", map_error("ERROR: mystery", mode="mp3").lower())


if __name__ == "__main__":
    unittest.main()
