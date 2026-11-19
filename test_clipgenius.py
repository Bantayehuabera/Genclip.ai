"""Automated unit and FFmpeg integration tests for ClipGenius AI."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import TranscriptSegment
from services.youtube_service import extract_youtube_id, _parse_iso8601_duration
from services.video_service import (
    check_ffmpeg_available,
    generate_animated_ass_subtitles,
    probe_video_info,
    render_vertical_mp4,
)


class TestClipGeniusCore(unittest.TestCase):
    def test_extract_youtube_id(self):
        self.assertEqual(
            extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_youtube_id("https://youtu.be/dQw4w9WgXcQ?t=42"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertIsNone(extract_youtube_id("https://example.com/not-youtube"))

    def test_parse_iso8601_duration(self):
        self.assertEqual(_parse_iso8601_duration("PT1H2M3S"), 3723.0)
        self.assertEqual(_parse_iso8601_duration("PT15M20S"), 920.0)
        self.assertEqual(_parse_iso8601_duration("PT45S"), 45.0)
        self.assertIsNone(_parse_iso8601_duration("invalid"))

    def test_generate_animated_ass_subtitles(self):
        segments = [
            TranscriptSegment(start=1.0, duration=3.0, text="This secret trick doubles your editing speed"),
            TranscriptSegment(start=4.5, duration=2.5, text="Try it on your next short video"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            ass_path = os.path.join(tmpdir, "captions.ass")
            ok = generate_animated_ass_subtitles(
                segments=segments,
                clip_start=0.5,
                clip_end=7.0,
                highlight_words=["secret", "speed"],
                output_ass_path=ass_path,
            )
            self.assertTrue(ok)
            content = Path(ass_path).read_text(encoding="utf-8")
            self.assertIn("PlayResX: 1080", content)
            self.assertIn("PlayResY: 1920", content)
            self.assertIn(r"\c&H0038D9FF&", content)
            self.assertIn("secret", content)

    @unittest.skipUnless(check_ffmpeg_available(), "FFmpeg not installed")
    def test_real_ffmpeg_vertical_mp4_render(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_mp4 = os.path.join(tmpdir, "sample_16x9.mp4")
            out_mp4 = os.path.join(tmpdir, "clip_9x16.mp4")

            # Generate a 4-second 1280x720 synthetic test video with audio
            gen_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc=duration=4:size=1280x720:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                src_mp4,
            ]
            proc = subprocess.run(gen_cmd, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)

            segments = [
                TranscriptSegment(start=0.2, duration=2.5, text="Welcome to ClipGenius AI vertical test"),
            ]
            dur, _smart_crop_used, captions_added = render_vertical_mp4(
                source_video_path=src_mp4,
                output_mp4_path=out_mp4,
                start_time=0.5,
                end_time=3.0,
                transcript_segments=segments,
                highlight_words=["ClipGenius", "vertical"],
                add_captions=True,
                smart_crop=True,
            )
            self.assertTrue(os.path.isfile(out_mp4))
            self.assertGreater(os.path.getsize(out_mp4), 1000)
            self.assertTrue(captions_added)
            self.assertAlmostEqual(dur, 2.5, delta=0.2)

            out_dur, out_w, out_h = probe_video_info(out_mp4)
            self.assertEqual(out_w, 1080)
            self.assertEqual(out_h, 1920)
            self.assertGreater(out_dur, 2.0)


if __name__ == "__main__":
    unittest.main()
