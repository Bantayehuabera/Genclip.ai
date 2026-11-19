"""Pydantic models for ClipGenius AI API."""

from typing import List, Optional
from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    start: float = Field(..., ge=0)
    duration: float = Field(..., ge=0)
    text: str


class VideoMetadata(BaseModel):
    video_id: Optional[str] = None
    source_type: str = Field(..., description="'youtube' or 'upload'")
    title: str
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    author: Optional[str] = None
    local_video_id: Optional[str] = None
    local_video_url: Optional[str] = None


class ClipSuggestion(BaseModel):
    id: str
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
    duration: float = Field(..., gt=0)
    title: str
    description: str
    hashtags: List[str] = Field(default_factory=list)
    viral_score: int = Field(..., ge=1, le=100)
    score_reason: str
    category: str = "highlight"
    highlight_words: List[str] = Field(default_factory=list)
    excerpt: str = ""


class AnalyzeRequest(BaseModel):
    youtube_url: Optional[str] = None
    local_video_id: Optional[str] = None
    rights_confirmed: bool = False
    desired_clips: int = Field(default=6, ge=5, le=10)


class AnalyzeResponse(BaseModel):
    metadata: VideoMetadata
    transcript_source: str
    transcript_segments: List[TranscriptSegment]
    clips: List[ClipSuggestion]


class RenderClipRequest(BaseModel):
    local_video_id: str
    clip_id: str
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
    title: str = "clip"
    add_captions: bool = True
    smart_crop: bool = True
    highlight_words: List[str] = Field(default_factory=list)
    transcript_segments: List[TranscriptSegment] = Field(default_factory=list)
    rights_confirmed: bool = False


class RenderClipResponse(BaseModel):
    clip_id: str
    filename: str
    download_url: str
    duration: float
    smart_crop_used: bool
    captions_added: bool
