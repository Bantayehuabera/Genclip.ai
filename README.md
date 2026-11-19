ClipGenius AI — Functional Short-Form Video Clipping MVP

ClipGenius AI is a lightweight, locally runnable full-stack web application that analyzes long videos with the Gemini API to find 5–10 engaging moments (15–60 seconds each), generates short-form titles, descriptions, hashtags, and viral potential scores, and exports actual downloadable 9:16 vertical MP4 clips with animated word-highlighting captions and optional face-centered smart cropping using FFmpeg.



Project Structure

clipgenius-ai/
├── README.md
├── .env.example
├── backend/
│   ├── main.py                     # FastAPI server + REST API + static frontend hosting
│   ├── models.py                   # Pydantic request/response schemas
│   ├── requirements.txt            # Python dependencies
│   ├── services/
│   │   ├── youtube_service.py      # YouTube oEmbed metadata, legitimate captions, local Whisper
│   │   ├── ai_service.py           # Gemini API transcript analyzer (5-10 clips + metadata)
│   │   └── video_service.py        # FFmpeg 9:16 crop, animated ASS captions, OpenCV smart crop
│   └── tests/
│       └── test_clipgenius.py      # Automated unit & FFmpeg integration tests
└── frontend/
    ├── index.html                  # Responsive dark-theme dashboard
    ├── styles.css                  # Purple-blue dark UI styling
    └── app.js                      # Upload, analysis, preview, timestamp edit & MP4 download


External APIs, Costs & Free Alternatives

Capability	Default Used	Cost / Free Alternative
AI Clip Selection & Titles	Gemini API (gemini-2.5-flash)	Free tier available in Google AI Studio (no credit card required for free tier rate limits).
YouTube Metadata	Official YouTube oEmbed + optional YouTube Data API v3	100% Free. oEmbed requires no API key; YouTube Data API v3 (optional, for exact duration) has a generous free quota in Google Cloud Console.
Transcription	Legitimate YouTube Captions (youtube-transcript-api) or local Whisper (faster-whisper)	100% Free. Local faster-whisper runs on your own CPU with zero API fees.
Video Clipping & Captions	FFmpeg + ASS subtitles + optional OpenCV smart crop	100% Free & open source, running locally on your computer.


Rights & Compliance Notice


ClipGenius AI does not bypass YouTube download protections, age/privacy restrictions, or access controls.

To export downloadable MP4 clips, upload the authorized video file (MP4/MOV/MKV/WebM) that you own, recorded yourself, downloaded from your own YouTube Studio, or have explicit permission to edit.

Viral potential scores (1–100%) estimate engagement characteristics (hook strength, clarity, pacing) and are not a guarantee of views.



Step-by-Step Setup & Installation

1. Install Prerequisites


Python 3.10+: Download from python.org.

FFmpeg (required for MP4 rendering and animated captions):
Windows: winget install Gyan.FFmpeg (then restart your terminal)
macOS: brew install ffmpeg
Ubuntu / Debian Linux: sudo apt update && sudo apt install -y ffmpeg
Verify with: ffmpeg -version


2. Create a Virtual Environment & Install Python Dependencies

From inside the clipgenius-ai/ folder:


python -m venv .venv

# Activate on Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Activate on macOS / Linux:
source .venv/bin/activate

# Install core dependencies:
pip install -r backend/requirements.txt

# (Optional) Install free local Whisper for transcribing uploaded videos without YouTube captions:
pip install faster-whisper

3. Configure Your Free Gemini API Key


Visit Google AI Studio and generate a free GEMINI_API_KEY.

Copy .env.example to .env in the clipgenius-ai/ root folder:
cp .env.example .env

Open .env and paste your key:
GEMINI_API_KEY=AIzaSy...your_key_here
GEMINI_MODEL=gemini-2.5-flash


4. Run the Application

From the clipgenius-ai/ folder:


uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

Open your browser to: http://127.0.0.1:8000



How to Use & Test

End-to-End Manual Walkthrough


Check the status pills in the top-right corner (Gemini API Ready, FFmpeg Ready, Smart Crop Ready).

Paste a YouTube URL (with captions enabled) and/or click Upload Video File to attach your authorized local MP4.

Check the rights confirmation box and click Analyze Video.

Review the 5–10 AI-suggested clips, preview moments directly in the 9:16 cards, adjust Start / End timestamps, star your favorites, and click Render 9:16 MP4.

Click the green Download MP4 button to save the finished vertical video with burned-in animated captions.


Run the Automated Test Suite

python -m unittest discover -s backend/tests -v

This verifies YouTube URL parsing, animated ASS caption generation with keyword highlighting, and an actual FFmpeg 1080×1920 vertical MP4 render on a generated test clip.


