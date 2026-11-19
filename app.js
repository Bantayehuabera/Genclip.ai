/* ClipGenius AI Frontend Logic */

const state = {
  localVideo: null,
  metadata: null,
  transcriptSegments: [],
  clips: [],
  favorites: new Set(),
  filterMode: "all", // 'all' | 'favorites'
  renderedExports: {}, // clipId -> RenderClipResponse
};

const els = {
  statusPills: document.getElementById("statusPills"),
  youtubeUrl: document.getElementById("youtubeUrl"),
  desiredClips: document.getElementById("desiredClips"),
  videoFileInput: document.getElementById("videoFileInput"),
  uploadBtn: document.getElementById("uploadBtn"),
  uploadStatus: document.getElementById("uploadStatus"),
  rightsCheckbox: document.getElementById("rightsCheckbox"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  errorBanner: document.getElementById("errorBanner"),
  loadingBox: document.getElementById("loadingBox"),
  loadingTitle: document.getElementById("loadingTitle"),
  loadingSub: document.getElementById("loadingSub"),
  metaSection: document.getElementById("metaSection"),
  metaThumb: document.getElementById("metaThumb"),
  metaThumbFallback: document.getElementById("metaThumbFallback"),
  metaSourceBadge: document.getElementById("metaSourceBadge"),
  metaTitle: document.getElementById("metaTitle"),
  metaAuthor: document.getElementById("metaAuthor"),
  metaDuration: document.getElementById("metaDuration"),
  metaClipCount: document.getElementById("metaClipCount"),
  clipsSection: document.getElementById("clipsSection"),
  clipsGrid: document.getElementById("clipsGrid"),
  filterAllBtn: document.getElementById("filterAllBtn"),
  filterFavBtn: document.getElementById("filterFavBtn"),
  favCount: document.getElementById("favCount"),
};

function formatTime(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rem = s % 60;
  if (h > 0) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(rem).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(rem).padStart(2, "0")}`;
}

function showError(msg) {
  els.errorBanner.textContent = msg;
  els.errorBanner.classList.remove("hidden");
}

function clearError() {
  els.errorBanner.textContent = "";
  els.errorBanner.classList.add("hidden");
}

function setLoading(active, title = "Analyzing video with Gemini AI...", sub = "Fetching metadata & transcript, then scoring the strongest 15–60s moments.") {
  els.analyzeBtn.disabled = active;
  els.loadingTitle.textContent = title;
  els.loadingSub.textContent = sub;
  els.loadingBox.classList.toggle("hidden", !active);
}

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error("Backend unavailable");
    const data = await res.json();
    const pills = [
      { label: data.gemini_configured ? "Gemini API Ready" : "Gemini Key Missing", ok: data.gemini_configured },
      { label: data.ffmpeg_available ? "FFmpeg Ready" : "FFmpeg Missing", ok: data.ffmpeg_available },
      { label: data.smart_crop_available ? "Smart Crop Ready" : "Center Crop Only", ok: data.smart_crop_available },
      { label: data.whisper_available ? "Whisper Ready" : "YouTube Captions Mode", ok: data.whisper_available },
    ];
    els.statusPills.innerHTML = pills
      .map((p) => `<span class="pill ${p.ok ? "pill-ok" : "pill-warn"}">${p.label}</span>`)
      .join("");
  } catch {
    els.statusPills.innerHTML = `<span class="pill pill-warn">Backend Offline — Start FastAPI</span>`;
  }
}

// Handle Authorized Local Video Upload
els.uploadBtn.addEventListener("click", () => els.videoFileInput.click());

els.videoFileInput.addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  clearError();
  els.uploadBtn.disabled = true;
  els.uploadStatus.textContent = `Uploading ${file.name}...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload-video", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Video upload failed.");
    }
    state.localVideo = data;
    els.uploadStatus.textContent = `${data.filename} (${formatTime(data.duration)})`;
  } catch (err) {
    state.localVideo = null;
    els.uploadStatus.textContent = "Upload failed";
    showError(err.message);
  } finally {
    els.uploadBtn.disabled = false;
  }
});

// Handle Analyze Video
els.analyzeBtn.addEventListener("click", async () => {
  clearError();
  const youtubeUrl = els.youtubeUrl.value.trim();
  const rightsConfirmed = els.rightsCheckbox.checked;

  if (!rightsConfirmed) {
    showError("Please confirm that you own or have permission to edit this video before analyzing.");
    return;
  }
  if (!youtubeUrl && !state.localVideo) {
    showError("Please paste a YouTube URL, upload an authorized local video file, or both.");
    return;
  }

  setLoading(true);
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: youtubeUrl || null,
        local_video_id: state.localVideo ? state.localVideo.id : null,
        rights_confirmed: rightsConfirmed,
        desired_clips: Number(els.desiredClips.value) || 6,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `Analysis failed (HTTP ${res.status}).`);
    }

    state.metadata = data.metadata;
    state.transcriptSegments = data.transcript_segments || [];
    state.clips = data.clips || [];
    state.favorites.clear();
    state.renderedExports = {};

    renderMetadata(data.metadata, data.transcript_source, state.clips.length);
    renderClips();
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
});

function renderMetadata(meta, source, clipCount) {
  els.metaSection.classList.remove("hidden");
  els.metaTitle.textContent = meta.title;
  els.metaAuthor.textContent = meta.author ? `Channel: ${meta.author}` : "Source: Authorized Local Upload";
  els.metaDuration.textContent = meta.duration_seconds
    ? `Duration: ${formatTime(meta.duration_seconds)}`
    : "Duration: Unknown";
  els.metaClipCount.textContent = `${clipCount} Clips Suggested`;
  els.metaSourceBadge.textContent = `Transcript: ${source.replace(/_/g, " ")}`;

  if (meta.thumbnail_url) {
    els.metaThumb.src = meta.thumbnail_url;
    els.metaThumb.classList.remove("hidden");
    els.metaThumbFallback.classList.add("hidden");
  } else {
    els.metaThumb.classList.add("hidden");
    els.metaThumbFallback.classList.remove("hidden");
  }
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function highlightCaptionHtml(text, keywords) {
  const set = new Set((keywords || []).map((w) => w.toLowerCase().replace(/[^a-z0-9]/g, "")));
  return escapeHtml(text)
    .split(/\s+/)
    .map((tok) => {
      const clean = tok.toLowerCase().replace(/[^a-z0-9]/g, "");
      return clean && set.has(clean) ? `<span class="hl">${tok}</span>` : tok;
    })
    .join(" ");
}

function renderClips() {
  els.clipsSection.classList.remove("hidden");
  els.favCount.textContent = String(state.favorites.size);

  const visibleClips =
    state.filterMode === "favorites"
      ? state.clips.filter((c) => state.favorites.has(c.id))
      : state.clips;

  if (!visibleClips.length) {
    els.clipsGrid.innerHTML = `<div class="panel">No clips match this filter yet. Click the star on any clip to favorite it.</div>`;
    return;
  }

  els.clipsGrid.innerHTML = visibleClips
    .map((clip) => {
      const isFav = state.favorites.has(clip.id);
      const scoreClass = clip.viral_score >= 85 ? "score-pill" : "score-pill mid";
      const exported = state.renderedExports[clip.id];
      const dur = Math.max(1, Math.round(clip.end_time - clip.start_time));

      let previewHtml = "";
      if (state.metadata?.local_video_url) {
        previewHtml = `
          <video
            id="vid-${clip.id}"
            src="${state.metadata.local_video_url}#t=${clip.start_time},${clip.end_time}"
            controls
            preload="metadata"
            playsinline
          ></video>
          <div class="preview-caption-overlay">${highlightCaptionHtml(clip.excerpt || clip.title, clip.highlight_words)}</div>
        `;
      } else if (state.metadata?.video_id) {
        const s = Math.floor(clip.start_time);
        const e = Math.ceil(clip.end_time);
        previewHtml = `
          <iframe
            src="https://www.youtube.com/embed/${state.metadata.video_id}?start=${s}&end=${e}&rel=0"
            title="${escapeHtml(clip.title)}"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen
          ></iframe>
        `;
      }

      return `
        <article class="clip-card ${isFav ? "is-favorite" : ""}" data-clip-id="${clip.id}">
          <div class="clip-top">
            <div class="clip-badges">
              <span class="${scoreClass}" title="Estimated from hook strength, clarity, and pacing (not a view guarantee)">
                ${clip.viral_score}% potential
              </span>
              <span class="cat-pill">${escapeHtml(clip.category)}</span>
            </div>
            <button type="button" class="fav-btn ${isFav ? "active" : ""}" data-action="fav" data-id="${clip.id}">
              ${isFav ? "&#9733; Saved" : "&#9734; Save"}
            </button>
          </div>

          <div class="preview-frame">${previewHtml}</div>

          <h3 class="clip-title">${escapeHtml(clip.title)}</h3>
          <p class="clip-desc">${escapeHtml(clip.description)}</p>
          <p class="clip-reason"><strong>Why it works:</strong> ${escapeHtml(clip.score_reason)}</p>

          <div class="hashtags">
            ${(clip.hashtags || []).map((t) => `<span class="hashtag">${escapeHtml(t)}</span>`).join("")}
          </div>

          <div class="time-controls">
            <div class="time-field">
              <label for="start-${clip.id}">Start (sec)</label>
              <input id="start-${clip.id}" type="number" step="0.5" min="0" value="${clip.start_time}" data-time="start" data-id="${clip.id}" />
            </div>
            <div class="time-field">
              <label for="end-${clip.id}">End (sec)</label>
              <input id="end-${clip.id}" type="number" step="0.5" min="1" value="${clip.end_time}" data-time="end" data-id="${clip.id}" />
            </div>
            <div class="dur-badge" id="dur-${clip.id}">${dur}s</div>
          </div>

          <div class="edit-toggles">
            <label>
              <input type="checkbox" id="cap-${clip.id}" checked />
              Animated Captions
            </label>
            <label>
              <input type="checkbox" id="crop-${clip.id}" checked />
              Smart Speaker Crop
            </label>
          </div>

          <div class="card-actions">
            <button type="button" class="btn btn-secondary" data-action="copy" data-id="${clip.id}">
              Copy Metadata
            </button>
            <button type="button" class="btn btn-primary" data-action="render" data-id="${clip.id}">
              Render 9:16 MP4
            </button>
          </div>

          ${
            exported
              ? `<a class="btn btn-success" href="${exported.download_url}" download="${escapeHtml(exported.filename)}">
                  Download MP4 (${exported.duration}s${exported.captions_added ? " + Captions" : ""})
                 </a>`
              : ""
          }
          <div class="card-msg hidden" id="msg-${clip.id}"></div>
        </article>
      `;
    })
    .join("");
}

// Delegated clip card actions
els.clipsGrid.addEventListener("change", (e) => {
  const input = e.target;
  if (!input.dataset.time) return;
  const clip = state.clips.find((c) => c.id === input.dataset.id);
  if (!clip) return;
  const val = Math.max(0, Number(input.value) || 0);
  if (input.dataset.time === "start") clip.start_time = val;
  if (input.dataset.time === "end") clip.end_time = val;
  const durEl = document.getElementById(`dur-${clip.id}`);
  if (durEl) durEl.textContent = `${Math.max(1, Math.round(clip.end_time - clip.start_time))}s`;

  // Sync HTML5 video preview if local video is present
  const vid = document.getElementById(`vid-${clip.id}`);
  if (vid) {
    vid.currentTime = clip.start_time;
  }
});

els.clipsGrid.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const clipId = btn.dataset.id;
  const clip = state.clips.find((c) => c.id === clipId);
  if (!clip) return;

  if (action === "fav") {
    if (state.favorites.has(clipId)) state.favorites.delete(clipId);
    else state.favorites.add(clipId);
    renderClips();
    return;
  }

  if (action === "copy") {
    const text = `${clip.title}\n\n${clip.description}\n\n${(clip.hashtags || []).join(" ")}`;
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = "Copy Metadata"), 1500);
    } catch {
      alert(text);
    }
    return;
  }

  if (action === "render") {
    const msgEl = document.getElementById(`msg-${clipId}`);
    const showCardMsg = (txt) => {
      if (!msgEl) return;
      msgEl.textContent = txt;
      msgEl.classList.remove("hidden");
    };

    if (!state.localVideo) {
      showCardMsg("Upload your authorized local video file above first so FFmpeg can render a downloadable MP4.");
      return;
    }
    if (clip.end_time <= clip.start_time + 1) {
      showCardMsg("End time must be at least 1 second after start time.");
      return;
    }

    btn.disabled = true;
    btn.textContent = "Rendering MP4...";
    showCardMsg("Running FFmpeg 9:16 crop & animated captions...");

    try {
      const res = await fetch("/api/render-clip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          local_video_id: state.localVideo.id,
          clip_id: clip.id,
          start_time: clip.start_time,
          end_time: clip.end_time,
          title: clip.title,
          add_captions: document.getElementById(`cap-${clipId}`)?.checked ?? true,
          smart_crop: document.getElementById(`crop-${clipId}`)?.checked ?? true,
          highlight_words: clip.highlight_words || [],
          transcript_segments: state.transcriptSegments,
          rights_confirmed: els.rightsCheckbox.checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "FFmpeg render failed.");
      }
      state.renderedExports[clipId] = data;
      renderClips();
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Render 9:16 MP4";
      showCardMsg(`Error: ${err.message}`);
    }
  }
});

// Filter buttons
els.filterAllBtn.addEventListener("click", () => {
  state.filterMode = "all";
  els.filterAllBtn.classList.add("chip-active");
  els.filterFavBtn.classList.remove("chip-active");
  renderClips();
});

els.filterFavBtn.addEventListener("click", () => {
  state.filterMode = "favorites";
  els.filterFavBtn.classList.add("chip-active");
  els.filterAllBtn.classList.remove("chip-active");
  renderClips();
});

checkHealth();
