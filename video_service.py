"""FFmpeg 9:16 vertical video clipping, animated ASS captions, and optional smart cropping."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

from models import TranscriptSegment


def check_ffmpeg_available() -> bool:
    """Verify ffmpeg and ffprobe are installed and available on PATH."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_video_info(video_path: str) -> Tuple[float, int, int]:
    """Return (duration_seconds, width, height) using ffprobe."""
    if not shutil.which("ffprobe"):
        raise RuntimeError(
            "FFprobe is not installed. Please install FFmpeg (https://ffmpeg.org/download.html)."
        )
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Could not inspect video file with ffprobe: {proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    duration = float(data.get("format", {}).get("duration") or 0.0)
    streams = data.get("streams", [])
    width = int(streams[0].get("width", 1920)) if streams else 1920
    height = int(streams[0].get("height", 1080)) if streams else 1080
    return duration, width, height


def detect_speaker_center_x(
    video_path: str,
    start_time: float,
    end_time: float,
    video_width: int,
) -> Optional[int]:
    """Sample frames in the clip window with OpenCV face detection to estimate speaker X-center.

    Returns the median face center X coordinate in pixels, or None if OpenCV is unavailable
    or no faces are detected (falling back gracefully to center crop).
    """
    try:
        import cv2
    except ImportError:
        return None

    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    if not os.path.isfile(cascade_path):
        return None

    face_cascade = cv2.CascadeClassifier(cascade_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    centers = []
    try:
        duration = max(1.0, end_time - start_time)
        sample_count = min(10, max(3, int(duration // 4)))
        for idx in range(sample_count):
            t_sec = start_time + (duration * (idx + 0.5) / sample_count)
            cap.set(cv2.CAP_PROP_POS_MSEC, t_sec * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=5, minSize=(48, 48)
            )
            if len(faces) > 0:
                # Pick largest detected face (primary speaker)
                x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
                centers.append(int(x + w / 2))
    finally:
        cap.release()

    if not centers:
        return None

    centers.sort()
    median_x = centers[len(centers) // 2]
    return max(0, min(video_width, median_x))


def _format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cc."""
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def generate_animated_ass_subtitles(
    segments: List[TranscriptSegment],
    clip_start: float,
    clip_end: float,
    highlight_words: List[str],
    output_ass_path: str,
) -> bool:
    """Generate a vertical 1080x1920 ASS subtitle file with pop-in animation and highlighted keywords.

    Returns True if at least one subtitle line was written.
    """
    hl_set = {
        re.sub(r"[^a-z0-9]", "", w.lower())
        for w in highlight_words
        if w and w.strip()
    }

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,66,&H00FFFFFF,&H0000D7FF,&H000B0C14,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,290,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogues = []
    for seg in segments:
        seg_start = seg.start
        seg_end = seg.start + seg.duration
        if seg_end <= clip_start or seg_start >= clip_end:
            continue

        rel_start = max(0.0, seg_start - clip_start)
        rel_end = min(clip_end - clip_start, seg_end - clip_start)
        if rel_end - rel_start < 0.15:
            continue

        words = seg.text.split()
        if not words:
            continue

        # Split long transcript lines into punchy 4-5 word chunks for Shorts readability
        chunk_size = 5
        chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
        chunk_dur = (rel_end - rel_start) / len(chunks)

        for c_idx, chunk in enumerate(chunks):
            c_start = rel_start + c_idx * chunk_dur
            c_end = rel_start + (c_idx + 1) * chunk_dur
            styled_tokens = []
            for tok in chunk:
                norm = re.sub(r"[^a-z0-9]", "", tok.lower())
                safe_tok = _escape_ass_text(tok)
                if norm and norm in hl_set:
                    # Vivid gold/yellow highlight with slight scale boost for key words
                    styled_tokens.append(
                        r"{\c&H0038D9FF&\fscx112\fscy112}"
                        + safe_tok
                        + r"{\c&H00FFFFFF&\fscx100\fscy100}"
                    )
                else:
                    styled_tokens.append(safe_tok)

            # Subtle pop-in scale animation at line start
            anim_prefix = r"{\fscx92\fscy92\t(0,110,\fscx100\fscy100)}"
            line_text = anim_prefix + " ".join(styled_tokens)
            dialogues.append(
                f"Dialogue: 0,{_format_ass_time(c_start)},{_format_ass_time(c_end)},Default,,0,0,0,,{line_text}"
            )

    if not dialogues:
        return False

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(dialogues) + "\n")
    return True


def _escape_ffmpeg_filter_path(path: str) -> str:
    """Escape file paths for FFmpeg libass filter syntax (cross-platform Windows/macOS/Linux)."""
    p = path.replace("\\", "/")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


def render_vertical_mp4(
    source_video_path: str,
    output_mp4_path: str,
    start_time: float,
    end_time: float,
    transcript_segments: List[TranscriptSegment],
    highlight_words: List[str],
    add_captions: bool = True,
    smart_crop: bool = True,
) -> Tuple[float, bool, bool]:
    """Render a real 1080x1920 9:16 MP4 clip with FFmpeg, optional smart crop, and animated captions.

    Returns (clip_duration, smart_crop_used, captions_added).
    """
    if not check_ffmpeg_available():
        raise RuntimeError(
            "FFmpeg is not installed or not on PATH. Install FFmpeg to render MP4 clips."
        )

    duration, src_w, src_h = probe_video_info(source_video_path)
    if duration <= 0:
        raise RuntimeError("Source video has invalid duration.")

    start_time = max(0.0, min(start_time, max(0.0, duration - 1.0)))
    end_time = max(start_time + 1.0, min(end_time, duration))
    clip_dur = round(end_time - start_time, 2)

    # Calculate 9:16 crop window from source dimensions
    target_aspect = 9.0 / 16.0
    src_aspect = src_w / float(src_h)
    smart_crop_used = False

    if src_aspect > target_aspect:
        # Landscape / standard video: crop horizontally to 9:16
        crop_h = src_h
        crop_w = int(round(src_h * target_aspect))
        crop_w = max(2, crop_w - (crop_w % 2))
        crop_y = 0
        crop_x = (src_w - crop_w) // 2

        if smart_crop:
            face_x = detect_speaker_center_x(source_video_path, start_time, end_time, src_w)
            if face_x is not None:
                crop_x = max(0, min(src_w - crop_w, face_x - crop_w // 2))
                smart_crop_used = True
    else:
        # Already vertical or taller than 9:16: crop vertically
        crop_w = src_w - (src_w % 2)
        crop_h = int(round(crop_w / target_aspect))
        crop_h = min(src_h, max(2, crop_h - (crop_h % 2)))
        crop_x = 0
        crop_y = (src_h - crop_h) // 2

    filters = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        "scale=1080:1920:flags=lanczos",
        "setsar=1",
    ]

    captions_added = False
    tmp_ass_file = None
    try:
        if add_captions and transcript_segments:
            fd, tmp_ass_file = tempfile.mkstemp(suffix=".ass", prefix="clipgenius_")
            os.close(fd)
            captions_added = generate_animated_ass_subtitles(
                segments=transcript_segments,
                clip_start=start_time,
                clip_end=end_time,
                highlight_words=highlight_words,
                output_ass_path=tmp_ass_file,
            )
            if captions_added:
                escaped_ass = _escape_ffmpeg_filter_path(tmp_ass_file)
                filters.append(f"ass='{escaped_ass}'")

        vf_chain = ",".join(filters)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_time:.3f}",
            "-i",
            source_video_path,
            "-t",
            f"{clip_dur:.3f}",
            "-vf",
            vf_chain,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            output_mp4_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not os.path.isfile(output_mp4_path):
            raise RuntimeError(
                f"FFmpeg failed while rendering vertical clip: {proc.stderr[-600:].strip()}"
            )
    finally:
        if tmp_ass_file and os.path.isfile(tmp_ass_file):
            try:
                os.remove(tmp_ass_file)
            except OSError:
                pass

    return clip_dur, smart_crop_used, captions_added
