"""YouTube metadata, legitimate caption retrieval, and local Whisper transcription."""

import os
import re
from typing import List, Optional, Tuple
import httpx

from models import TranscriptSegment, VideoMetadata

YOUTUBE_ID_PATTERNS = [
    re.compile(r"(?:v=|/v/|/embed/|/shorts/)([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
]


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a standard YouTube URL."""
    if not url:
        return None
    url = url.strip()
    for pattern in YOUTUBE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _parse_iso8601_duration(duration_str: str) -> Optional[float]:
    """Parse ISO-8601 duration strings (e.g. PT12M34S) from YouTube Data API v3."""
    match = re.match(
        r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$",
        duration_str or "",
    )
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return float(hours * 3600 + minutes * 60 + seconds)


async def fetch_youtube_metadata(youtube_url: str) -> VideoMetadata:
    """Retrieve public YouTube video metadata via official oEmbed (and optional Data API v3).

    Does not bypass any YouTube restrictions or access controls.
    """
    video_id = extract_youtube_id(youtube_url)
    if not video_id:
        raise ValueError(
            "Invalid YouTube URL. Please paste a standard YouTube link "
            "(for example, https://www.youtube.com/watch?v=VIDEO_ID)."
        )

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    oembed_url = "https://www.youtube.com/oembed"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(oembed_url, params={"url": canonical_url, "format": "json"})
        if resp.status_code == 401 or resp.status_code == 403:
            raise PermissionError(
                "This YouTube video is private, age-restricted, or embedding-disabled and cannot be accessed."
            )
        if resp.status_code == 404:
            raise ValueError("YouTube video not found. Check the URL and try again.")
        if resp.status_code != 200:
            raise RuntimeError(
                f"Could not retrieve YouTube metadata (HTTP {resp.status_code})."
            )
        data = resp.json()

        duration_seconds: Optional[float] = None
        yt_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if yt_api_key:
            api_resp = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"id": video_id, "part": "contentDetails", "key": yt_api_key},
            )
            if api_resp.status_code == 200:
                items = api_resp.json().get("items", [])
                if items:
                    iso_dur = items[0].get("contentDetails", {}).get("duration", "")
                    duration_seconds = _parse_iso8601_duration(iso_dur)

    return VideoMetadata(
        video_id=video_id,
        source_type="youtube",
        title=data.get("title", f"YouTube Video ({video_id})"),
        thumbnail_url=data.get("thumbnail_url")
        or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        duration_seconds=duration_seconds,
        author=data.get("author_name"),
    )


def fetch_youtube_transcript(video_id: str) -> Tuple[List[TranscriptSegment], str]:
    """Fetch legitimately available captions for a YouTube video.

    Uses youtube-transcript-api against public caption tracks only.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api is not installed. Run: pip install -r backend/requirements.txt"
        ) from exc

    try:
        # Support both youtube-transcript-api >= 1.0 (instance API) and 0.6.x (class API)
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            raw_segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        else:
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
            raw_segments = [
                {"start": s.start, "duration": s.duration, "text": s.text}
                for s in fetched
            ]
    except Exception as exc:
        raise RuntimeError(
            "Captions could not be retrieved for this YouTube video (captions may be disabled, "
            "unavailable in English, or restricted). If you own or have permission to edit this "
            "video, upload your local video file to transcribe it with Whisper instead. "
            f"Details: {exc}"
        ) from exc

    segments: List[TranscriptSegment] = []
    for seg in raw_segments:
        text = re.sub(r"\s+", " ", str(seg.get("text", ""))).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=round(float(seg.get("start", 0.0)), 2),
                duration=round(max(0.1, float(seg.get("duration", 1.0))), 2),
                text=text,
            )
        )

    if not segments:
        raise RuntimeError("Retrieved YouTube caption track was empty.")

    return segments, "youtube_captions"


def transcribe_local_video_whisper(video_path: str) -> Tuple[List[TranscriptSegment], str]:
    """Transcribe an authorized local video file using free local faster-whisper."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Local audio transcription requires 'faster-whisper'. Install it with:\n"
            "  pip install faster-whisper\n"
            "Or provide a YouTube URL with available captions alongside your authorized video file."
        ) from exc

    model_size = os.getenv("WHISPER_MODEL", "base").strip() or "base"
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    raw_segments, _info = model.transcribe(video_path, vad_filter=True)

    segments: List[TranscriptSegment] = []
    for seg in raw_segments:
        text = re.sub(r"\s+", " ", seg.text or "").strip()
        if not text:
            continue
        dur = max(0.1, float(seg.end) - float(seg.start))
        segments.append(
            TranscriptSegment(
                start=round(float(seg.start), 2),
                duration=round(dur, 2),
                text=text,
            )
        )

    if not segments:
        raise RuntimeError("Whisper completed but detected no spoken dialogue in this video.")

    return segments, f"whisper_{model_size}"
