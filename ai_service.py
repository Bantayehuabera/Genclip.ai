"""Gemini API service for analyzing video transcripts and selecting viral-worthy clips."""

import json
import os
import re
from typing import List

from models import ClipSuggestion, TranscriptSegment


def _format_transcript_for_prompt(segments: List[TranscriptSegment], max_chars: int = 45000) -> str:
    """Format timestamped transcript lines compactly for Gemini analysis."""
    lines = []
    total = 0
    for seg in segments:
        line = f"[{seg.start:.1f}s] {seg.text}"
        if total + len(line) + 1 > max_chars:
            lines.append("... [transcript truncated for length]")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _extract_json_payload(raw_text: str) -> dict:
    """Safely parse JSON from Gemini response, stripping code fences if present."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    return json.loads(cleaned)


def analyze_transcript_with_gemini(
    video_title: str,
    segments: List[TranscriptSegment],
    video_duration: float,
    desired_clips: int = 6,
) -> List[ClipSuggestion]:
    """Use the Gemini API to identify 5-10 strong short-form moments (15-60s each)."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Get a free API key at "
            "https://aistudio.google.com/apikey and add it to your .env file."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai package is not installed. Run: pip install -r backend/requirements.txt"
        ) from exc

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    transcript_text = _format_transcript_for_prompt(segments)
    desired_clips = max(5, min(10, int(desired_clips)))

    prompt = f"""You are an expert short-form video editor for YouTube Shorts, TikTok, and Instagram Reels.

Analyze the timestamped transcript below from the video "{video_title}" (total length ~{video_duration:.1f} seconds).

Identify {desired_clips} of the strongest standalone moments that would work well as short-form clips:
- Funny moments, punchlines, or surprising reactions
- Strong hooks, bold statements, or counterintuitive insights
- Engaging mini-stories, practical advice, or lively exchanges

Rules:
1. Every clip MUST be between 15 and 60 seconds long (unless the entire video is shorter than 20 seconds).
2. Use accurate start_time and end_time in seconds strictly within [0, {video_duration:.1f}].
3. Clips should start cleanly on a hook and end on a complete thought.
4. For each clip, provide:
   - start_time (number, seconds)
   - end_time (number, seconds)
   - title (punchy, curiosity-driven, <= 70 chars)
   - description (1-2 engaging sentences for Shorts/Reels/TikTok)
   - hashtags (4-6 relevant hashtags starting with #)
   - viral_score (integer 1-100 estimating engagement characteristics such as hook strength, clarity, emotional resonance, and pacing — NOT a guarantee of views)
   - score_reason (1 short sentence explaining why this moment is engaging)
   - category (one of: "Funny", "Insight", "Story", "Reaction", "Debate", "Tip")
   - highlight_words (4-8 single impactful keywords from that clip to emphasize in animated captions)
   - excerpt (short 1-2 sentence quote from that moment)

Return ONLY valid JSON matching this exact schema:
{{
  "clips": [
    {{
      "start_time": 12.0,
      "end_time": 45.5,
      "title": "...",
      "description": "...",
      "hashtags": ["#shorts", "#example"],
      "viral_score": 88,
      "score_reason": "...",
      "category": "Insight",
      "highlight_words": ["secret", "mistake"],
      "excerpt": "..."
    }}
  ]
}}

TRANSCRIPT:
{transcript_text}
"""

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )

    if not response or not getattr(response, "text", None):
        raise RuntimeError("Gemini API returned an empty response.")

    try:
        payload = _extract_json_payload(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini returned invalid JSON: {exc}") from exc

    raw_clips = payload.get("clips", [])
    if not isinstance(raw_clips, list) or not raw_clips:
        raise RuntimeError("Gemini did not return any clip suggestions for this transcript.")

    validated: List[ClipSuggestion] = []
    max_dur = max(video_duration, 15.0)
    for idx, item in enumerate(raw_clips[:10], start=1):
        try:
            start = max(0.0, float(item.get("start_time", 0.0)))
            end = min(max_dur, float(item.get("end_time", start + 30.0)))
            if end <= start + 3.0:
                end = min(max_dur, start + 25.0)
            dur = round(end - start, 2)
            if dur <= 1.0:
                continue

            raw_tags = item.get("hashtags", [])
            hashtags = []
            for tag in raw_tags if isinstance(raw_tags, list) else []:
                t = str(tag).strip()
                if not t:
                    continue
                if not t.startswith("#"):
                    t = "#" + re.sub(r"\s+", "", t)
                hashtags.append(t)

            hl_words = [
                str(w).strip()
                for w in (item.get("highlight_words") or [])
                if str(w).strip()
            ][:10]

            score = int(item.get("viral_score", 75))
            score = max(1, min(100, score))

            validated.append(
                ClipSuggestion(
                    id=f"clip_{idx:02d}",
                    start_time=round(start, 2),
                    end_time=round(end, 2),
                    duration=dur,
                    title=str(item.get("title", f"Clip {idx:02d}")).strip()[:100],
                    description=str(item.get("description", "")).strip(),
                    hashtags=hashtags[:8],
                    viral_score=score,
                    score_reason=str(
                        item.get(
                            "score_reason",
                            "Strong opening hook and self-contained pacing.",
                        )
                    ).strip(),
                    category=str(item.get("category", "Highlight")).strip(),
                    highlight_words=hl_words,
                    excerpt=str(item.get("excerpt", "")).strip(),
                )
            )
        except (TypeError, ValueError):
            continue

    if not validated:
        raise RuntimeError("Could not parse valid timestamped clips from Gemini output.")

    validated.sort(key=lambda c: c.viral_score, reverse=True)
    return validated
