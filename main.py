"""ClipGenius AI — FastAPI Backend Entry Point."""

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from models import (
    AnalyzeRequest,
    AnalyzeResponse,
    RenderClipRequest,
    RenderClipResponse,
    VideoMetadata,
)
from services.ai_service import analyze_transcript_with_gemini
from services.video_service import (
    check_ffmpeg_available,
    probe_video_info,
    render_vertical_mp4,
)
from services.youtube_service import (
    fetch_youtube_metadata,
    fetch_youtube_transcript,
    transcribe_local_video_whisper,
)

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

FRONTEND_DIR = BASE_DIR / "frontend"
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
EXPORTS_DIR = STORAGE_DIR / "exports"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

# In-memory registry mapping local_video_id -> file metadata
UPLOADED_VIDEOS: Dict[str, Dict] = {}

app = FastAPI(
    title="ClipGenius AI",
    description="AI-powered vertical short-form video clipping MVP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Return live dependency & API key configuration status."""
    gemini_ready = bool(
        os.getenv("GEMINI_API_KEY", "").strip()
        and os.getenv("GEMINI_API_KEY", "").strip() != "your_gemini_api_key_here"
    )
    ffmpeg_ready = check_ffmpeg_available()
    try:
        import cv2  # noqa: F401
        smart_crop_ready = True
    except ImportError:
        smart_crop_ready = False
    try:
        import faster_whisper  # noqa: F401
        whisper_ready = True
    except ImportError:
        whisper_ready = False

    return {
        "status": "ok",
        "gemini_configured": gemini_ready,
        "ffmpeg_available": ffmpeg_ready,
        "smart_crop_available": smart_crop_ready,
        "whisper_available": whisper_ready,
    }


@app.post("/api/upload-video")
async def upload_authorized_video(file: UploadFile = File(...)):
    """Upload a local video file that the user owns or is authorized to edit."""
    original_name = file.filename or "video.mp4"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTS))}.",
        )

    video_id = uuid.uuid4().hex[:12]
    dest_path = UPLOADS_DIR / f"{video_id}{ext}"

    try:
        with open(dest_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded video: {exc}") from exc
    finally:
        await file.close()

    try:
        duration, width, height = probe_video_info(str(dest_path))
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    info = {
        "id": video_id,
        "filename": original_name,
        "path": str(dest_path),
        "duration": round(duration, 2),
        "width": width,
        "height": height,
        "video_url": f"/api/uploads/{video_id}",
    }
    UPLOADED_VIDEOS[video_id] = info
    return info


@app.get("/api/uploads/{video_id}")
async def stream_uploaded_video(video_id: str):
    """Serve an uploaded authorized video for in-browser clip preview."""
    info = UPLOADED_VIDEOS.get(video_id)
    if not info or not os.path.isfile(info["path"]):
        raise HTTPException(status_code=404, detail="Uploaded video not found.")
    return FileResponse(info["path"], media_type="video/mp4")


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_video(req: AnalyzeRequest):
    """Analyze a YouTube video (metadata + captions) and/or authorized local video with Gemini AI."""
    if not req.rights_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Please confirm that you own or have permission to edit this video before analyzing.",
        )

    if not req.youtube_url and not req.local_video_id:
        raise HTTPException(
            status_code=400,
            detail="Provide a YouTube URL, upload an authorized video file, or both.",
        )

    metadata: VideoMetadata
    segments = []
    transcript_source = ""
    local_info = UPLOADED_VIDEOS.get(req.local_video_id) if req.local_video_id else None

    if req.local_video_id and not local_info:
        raise HTTPException(
            status_code=404,
            detail="Uploaded video session expired or not found. Please upload the video again.",
        )

    # Step 1: Retrieve metadata & transcript honestly (no fake fallback)
    if req.youtube_url:
        try:
            metadata = await fetch_youtube_metadata(req.youtube_url)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if local_info:
            metadata.local_video_id = local_info["id"]
            metadata.local_video_url = local_info["video_url"]
            if not metadata.duration_seconds:
                metadata.duration_seconds = local_info["duration"]

        # Try legitimate YouTube captions first; fall back to local Whisper ONLY if user uploaded authorized video
        try:
            segments, transcript_source = fetch_youtube_transcript(metadata.video_id)
        except RuntimeError as yt_err:
            if local_info:
                try:
                    segments, transcript_source = transcribe_local_video_whisper(local_info["path"])
                except Exception as whisper_err:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{yt_err} Whisper fallback also failed: {whisper_err}",
                    ) from whisper_err
            else:
                raise HTTPException(status_code=422, detail=str(yt_err)) from yt_err
    else:
        # Authorized local video upload only
        metadata = VideoMetadata(
            source_type="upload",
            title=Path(local_info["filename"]).stem,
            duration_seconds=local_info["duration"],
            local_video_id=local_info["id"],
            local_video_url=local_info["video_url"],
        )
        try:
            segments, transcript_source = transcribe_local_video_whisper(local_info["path"])
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Infer duration from last transcript segment if YouTube Data API v3 key was not provided
    if not metadata.duration_seconds and segments:
        last = segments[-1]
        metadata.duration_seconds = round(last.start + last.duration, 2)

    total_duration = metadata.duration_seconds or 60.0

    # Step 2: Run Gemini AI analysis on the real transcript
    try:
        clips = analyze_transcript_with_gemini(
            video_title=metadata.title,
            segments=segments,
            video_duration=total_duration,
            desired_clips=req.desired_clips,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI analysis failed: {exc}") from exc

    return AnalyzeResponse(
        metadata=metadata,
        transcript_source=transcript_source,
        transcript_segments=segments,
        clips=clips,
    )


@app.post("/api/render-clip", response_model=RenderClipResponse)
async def render_clip(req: RenderClipRequest):
    """Render an actual downloadable 9:16 vertical MP4 clip with FFmpeg from an authorized video."""
    if not req.rights_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Rights confirmation is required before rendering MP4 clips.",
        )

    local_info = UPLOADED_VIDEOS.get(req.local_video_id)
    if not local_info or not os.path.isfile(local_info["path"]):
        raise HTTPException(
            status_code=400,
            detail=(
                "To export a downloadable MP4 without bypassing YouTube protections, "
                "please upload your authorized video file first."
            ),
        )

    if req.end_time <= req.start_time + 1.0:
        raise HTTPException(
            status_code=400,
            detail="End time must be at least 1 second after start time.",
        )

    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", req.title).strip("_")[:40] or req.clip_id
    out_filename = f"{safe_slug}_{uuid.uuid4().hex[:6]}_9x16.mp4"
    out_path = EXPORTS_DIR / out_filename

    try:
        clip_dur, smart_crop_used, captions_added = render_vertical_mp4(
            source_video_path=local_info["path"],
            output_mp4_path=str(out_path),
            start_time=req.start_time,
            end_time=req.end_time,
            transcript_segments=req.transcript_segments,
            highlight_words=req.highlight_words,
            add_captions=req.add_captions,
            smart_crop=req.smart_crop,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RenderClipResponse(
        clip_id=req.clip_id,
        filename=out_filename,
        download_url=f"/api/exports/{out_filename}",
        duration=clip_dur,
        smart_crop_used=smart_crop_used,
        captions_added=captions_added,
    )


@app.get("/api/exports/{filename}")
async def download_exported_clip(filename: str):
    """Download a rendered vertical MP4 clip."""
    safe_name = os.path.basename(filename)
    file_path = EXPORTS_DIR / safe_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Rendered clip not found.")
    return FileResponse(
        str(file_path),
        media_type="video/mp4",
        filename=safe_name,
    )


# Serve frontend static files
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
