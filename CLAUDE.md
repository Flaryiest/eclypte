# CLAUDE.md

This file gives Claude Code working context for Eclypte. The repo-wide agent guide is `AGENTS.md`; this file keeps the same architecture in a Claude-oriented, operational form.

## Project Summary

Eclypte is an AMV creator monorepo. The dashboard is a Next.js 16 frontend; the backend is a FastAPI control plane that schedules media work, persists artifacts in Cloudflare R2, and delegates heavy audio/video/render/index jobs to Modal. Optional Postgres stores run manifests/events/progress; optional Redis broadcasts realtime run updates to the dashboard.

Core invariants:

- Audio and video analysis payloads use `schema_version: 1`.
- Time fields use seconds and the `_sec` suffix. Do not leak frame indices into shared schemas.
- `RunManifest.outputs` keys are frontend contracts. Change them only with coordinated API and frontend updates.
- Export behavior belongs in `api/export_options.py`; do not reimplement format/trim/crop logic in pages, planners, adapters, or renderers.
- Browser audio uploads may be WAV or any common audio format (MP3/M4A/AAC/FLAC/OGG), auto-converted to WAV server-side; video uploads are MP4 only.

## Top-Level Layout

- `web/`: Next.js 16.2.3, React 19.2, TypeScript, App Router. `web/AGENTS.md` has frontend-specific warnings.
- `api/`: FastAPI app, workflow orchestration, storage substrate, and prototype media pipelines.
- `api/publishing.py`: review-gated Buffer publishing for Instagram Reels — Gen-Z-voiced OpenAI/fallback caption generation (the model is fed the source movie/anime + song names — resolved from the render's run lineage by `resolve_edit_source_names` and persisted on the post as `source_name`/`song_name` — and produces context-relevant AI hashtags), public R2 media copies, Buffer GraphQL payloads (declares the Instagram `reel` post type; the send modes are `queue`=`addToQueue`, `schedule`/`now`=`customScheduled` — `now` posts immediately via a server-computed near-future `dueAt` from `immediate_due_at`, since Buffer has no instant-publish mode and rejects past `dueAt`), channel diagnostics, and post-status refresh (`apply_buffer_status`) that marks a post `published` as soon as Buffer reports it sent (`sentAt`/sent status) and independently back-fills the permalink from `externalLink` when it appears.
- `api/storage/`: R2 object access, file manifests, file versions, upload reservations, run manifests/events/progress, prompt versions, references, publishing posts, Postgres run store, Redis broadcaster, and tests.
- `api/prototyping/music/`: the pure allin1 analyzer, its Modal app (`eclypte-analysis`), synced-lyrics lookup, and the word-level lyrics aligner (`lyrics_align.py` pure decisions + `lyrics_align_modal.py` Modal app `eclypte-lyrics`). (Audio ingestion and R2 publishing live in the control plane — `api/workflows.py` with the WAV transcode helper in `api/audio_convert.py`.)
- `api/prototyping/video/`: scene detection, optical-flow motion analysis, impact detection, local CPU and Modal GPU runtimes, R2-aware Modal wrapper.
- `api/prototyping/edit/`: CLIP index, OpenAI synthesis agent, reference ingest/metrics, timeline schemas/validators, dual-path renderer (MP4 + poster frame), Modal render/index wrappers.
- `api/COMMANDS.md`: command runbook. Prefer updating it when operational instructions change.
- `.agent/`, `.superpowers/`: agent/process assets, not runtime app code. (The old `docs/` plans/specs directory has been removed.)
- `content/` and `api/prototyping/**/content/`: local scratch/generated media.

## Development Commands

Run backend commands from the repo root unless a command says otherwise:

```bash
python -m pytest api -v
python -m pytest api/test_api_v1.py -v
python -m pytest api/storage -v
python -m pytest api/test_export_options.py -v
python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v
python -m api.main
```

Run frontend commands from `web/`:

```bash
npm run dev
npm run lint
npm run build
npm run start
```

Railway/Railpack uses the repo-root `requirements.txt` and starts with `python -m api.main`. Local prototype development can use `api/requirements.txt`; the heavy Modal audio image uses `api/requirements-modal.txt`.

## Cloud API

`api/main.py` imports `create_app()` from `api/app.py`. `api/app.py` owns FastAPI setup, CORS, temp auth, request/response models, route definitions, and background-task scheduling.

Temporary auth resolves user id from `X-User-Id`, falling back to `ECLYPTE_DEFAULT_USER_ID`. Frontend Clerk integration sends Clerk `user.id` in that header; backend JWT verification is deferred.

Real `/v1/*` calls need R2 env vars:

- `ECLYPTE_R2_ACCOUNT_ID`
- `ECLYPTE_R2_BUCKET`
- `ECLYPTE_R2_ACCESS_KEY_ID`
- `ECLYPTE_R2_SECRET_ACCESS_KEY`
- `ECLYPTE_R2_REGION_NAME`

Optional env vars:

- `DATABASE_URL`: stores run manifests, events, and latest progress in Postgres.
- `REDIS_URL`: publishes non-durable run-update stream messages for the dashboard.
- `ECLYPTE_INTERNAL_PROGRESS_URL` and `ECLYPTE_INTERNAL_PROGRESS_TOKEN`: let Modal workers post live render/analysis progress to `/internal/progress` (workers send `X-Eclypte-Internal-Token` matching the token). Without them, progress falls back to slower R2 event JSON. Keep server-side only.
- `BUFFER_API_KEY`, `BUFFER_INSTAGRAM_CHANNEL_ID`, and `ECLYPTE_R2_PUBLIC_BASE_URL`: enable review-gated Buffer Instagram publishing from public R2 copies. `ECLYPTE_BUFFER_POST_NOW_LEAD_SEC` (default 60) is the lead added to "now" the post's computed `dueAt` so Buffer accepts it (must be in the future) and publishes near-immediately.
- `OPENAI_API_KEY`: enables AI caption generation for publishing packages. `ECLYPTE_CAPTION_MODEL` is optional and defaults to a small GPT-5.4-class model; deterministic fallback captions are used when OpenAI is unavailable.
- `ECLYPTE_LYRICS_TIMING_DISABLED=1`: kill-switch for word-level lyrics timing — skips the GPU alignment call in the song workflows AND the edit pipeline's backfill ensure-step. `ECLYPTE_LYRICS_WHISPER_MODEL` overrides the aligner's Whisper model (default `large-v3`; `medium` is the pressure valve for very long songs).
- `ECLYPTE_AUTOPILOT=1`: starts the in-process autopilot loop (FastAPI lifespan task) that ticks every `ECLYPTE_AUTOPILOT_INTERVAL_SEC` (default 300) for every user with autopilot enabled. Without it, ticks only run via `POST /v1/autopilot/tick`.

Routes:

- Health: `GET /healthz` — also reports non-secret booleans for realtime streaming (`REDIS_URL`), Modal worker-progress configuration, and always-on autopilot loop configuration (`autopilot_loop_configured`, i.e. `ECLYPTE_AUTOPILOT=1`).
- Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`.
- Workflows: `POST /v1/music/analyses`, `POST /v1/music/conversions` (transcode an uploaded non-WAV audio file into a WAV `song_audio` asset), `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`.
- Edit jobs: `POST /v1/edits`, `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`.
- Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`.
- Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`.
- Publishing: `GET /v1/publishing/config`, `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer` (`mode`: `queue`/`schedule`/`now`), `POST /v1/publishing/posts/{post_id}/refresh-status`, `POST /v1/publishing/posts/{post_id}/mark-posted`, `POST /v1/publishing/posts/{post_id}/cancel`.
- Autopilot: `GET /v1/autopilot`, `PATCH /v1/autopilot` (enable/disable, daily target, clear halt), `POST /v1/autopilot/queue`, `DELETE /v1/autopilot/queue/{item_id}`, `POST /v1/autopilot/tick` (manual tick). `api/autopilot.py` owns the review-gated tick state machine: queue items pair a saved film with a saved song (analysis is kicked off first when missing), and the tick starts cinematic 9:16 Reels edit jobs (`reels_cinematic`) with an energy-ranked ~20–30s trim window (≈25s target) from the song's music analysis (section-anchored windows begin `CHORUS_LEAD_IN_SEC`≈5s early so a chorus reel captures the build-in), dedupes (video, song, window) combos, halts after 3 consecutive failures, and auto-creates `ready` publishing packages (`auto_created=true`) that wait for human approval in the dashboard's Home feed. State lives in R2 at `users/{user_id}/autopilot/state.json` with enabled-user markers under `autopilot/enabled/`.
- Internal: `POST /internal/progress`, requiring `X-Eclypte-Internal-Token`.

## Storage Substrate

`api/storage/models.py` defines strict Pydantic models:

- `FileManifest`
- `FileVersionMeta`
- `RunManifest`
- `RunEvent`
- `UploadReservation`
- `SynthesisReferenceRecord`
- `SynthesisPromptVersion`
- `SynthesisPromptState`
- `StoredSynthesisPromptState`
- `PublishingPostRecord`

Artifact kinds are:

- `source_video`
- `song_audio`
- `lyrics`
- `lyrics_timing`
- `music_analysis`
- `video_analysis`
- `clip_index`
- `timeline`
- `render_output`
- `render_poster`
- `source_poster`

`StorageRepository` is the API-facing facade. It writes file/upload metadata to the object store, routes run state through Postgres when configured or R2 JSON otherwise, and publishes Redis updates after durable writes. Redis failures must not break persistence.

Default asset lists hide archived assets, render outputs, render posters, and source posters. Use `kind=render_output` (or `kind=source_poster`) to list them explicitly. Archive/restore instead of hard deletion for normal dashboard lifecycle. `AssetSummary.poster` carries an optional `FileVersionInput` ref to the asset's thumbnail — resolved from the completed `video_analysis` run's `source_poster_file_id`/`source_poster_version_id` outputs for a `source_video` asset, or from the `render_poster_file_id`/`render_poster_version_id` outputs for a `render_output` asset — and `AssetSummary.poster_url` carries a ready-to-use signed URL for it, presigned locally in the listing from the deterministic version blob key (zero extra network ops; `DOWNLOAD_URL_EXPIRES_IN` is 3600s). Publishing post responses are `PublishingPostView` (the stored record plus per-response `poster_url`/`render_url`; signed URLs are never persisted — posts store only `render_poster_file_id/version_id` refs, captured at creation and lazily backfilled for legacy posts on first list).

## Workflow Orchestration

`api/workflows.py` defines `WorkflowRunner` and `DefaultWorkflowRunner`. Workflow endpoints create a `RunManifest` with `status="running"` and schedule FastAPI background work.

Important workflows:

- `run_music_analysis`: loads audio from R2, calls `eclypte-analysis::analyze_remote`, publishes a `music_analysis` asset.
- `run_lyrics_timing`: backfill worker for word-level lyrics timing — reuses the stored LRC (or fetches one), calls `eclypte-lyrics::align_lyrics_remote`, publishes `lyrics_timing`, and stamps `lyrics_timing_status: ok|none` (the negative-cache marker). Created by the edit pipeline's `_ensure_edit_lyrics_timing` for songs that predate the feature.
- `run_video_analysis`: calls `eclypte-video-r2::analyze_r2`, publishes `video_analysis`, and (best-effort) a `source_poster` JPEG from the analyzer's picked poster frame — a publish failure is logged and swallowed, never fails the run.
- `run_timeline_plan`: runs the OpenAI/CLIP agent planner and publishes `timeline`.
- `run_render`: calls `eclypte-render-r2::render_r2`, publishes a `render_output` MP4 and a `render_poster` JPEG thumbnail.
- `run_edit_pipeline`: parent workflow that selects saved assets, ensures missing analysis, plans, renders, and writes child run ids/output refs onto the parent run.
- `run_synthesis_reference_ingest`: downloads/analyzes reference AMVs and records metrics.
- `run_synthesis_consolidation`: consolidates queued/completed references into generated prompt guidance and prompt versions.

Edit child run ids and render output ids are part of the dashboard contract. Preserve keys such as `music_run_id`, `video_run_id`, `timeline_run_id`, `render_run_id`, `render_output_file_id`, `render_output_version_id`, `render_poster_file_id`, and `render_poster_version_id`.

## Export Options

`api/export_options.py` owns:

- `reels_9_16`: 1080x1920, fill crop, `crop_focus_x`.
- `reels_cinematic`: 1080x1920, letterbox — the full widescreen picture centered on a native vertical canvas with black bars baked in (autopilot's default).
- `youtube_16_9`: 1920x1080, letterbox.
- `audio_start_sec` and `audio_end_sec`.
- `trim_song_analysis()`, which rewrites beats, downbeats, segments, energy, and source duration for the selected audio window.
- `trim_lyrics_timing()`, the same windowing for `lyrics_timing` payloads (lines + words rebased into the window). One deliberate difference: an `end_sec` past the artifact's duration clamps instead of raising, because the whisper-measured duration can differ by ms from the music analysis the window was validated against.

Backend defaults to YouTube 16:9 when export options are omitted. The dashboard defaults the compose UI to Reels.

## Audio Pipeline

`api/prototyping/music/analysis.py` is the pure analyzer. It produces a song map with tempo, beats, downbeats, 10 Hz normalized energy, structural segments, `schema_version: 1`, and `_sec` timestamps.

`api/prototyping/music/analysis_modal.py` defines Modal app `eclypte-analysis` and `analyze_remote(audio_bytes, filename)`. It owns the heavy allin1/torch/natten image. Keep Modal imports out of `analysis.py`.

The control plane wires the music flow (`api/workflows.py`: `run_music_analysis`, `run_audio_conversion`) — upload ingestion (non-WAV transcode via `api/audio_convert.py`), Modal analysis, lyrics, and R2 publishing; the `music/` package itself is just the pure analyzer, its Modal app, and `lyrics.py`. `lyrics.py` uses `syncedlyrics`; lyrics are optional and separate from `song_analysis.json`. Production sourcing: `search_synced_lyrics(query)` (synced LRC only, query = song filename) is called opportunistically during `run_music_analysis`, and `_publish_song_lyrics` stores a `lyrics` asset, recording `lyrics_file_id`/`lyrics_version_id` in the run outputs. Best-effort: a miss/error stores nothing and never fails the run. `syncedlyrics` is in root `requirements.txt` because the fetch runs on the control plane (Railway).

Word-level lyrics timing: after the LRC fetch, `_publish_song_lyrics_and_timing` calls `eclypte-lyrics::align_lyrics_remote` with the audio bytes and the LRC **text only** — provider timestamps are always discarded because the user's audio can be offset from them; timing comes from forced alignment against the actual audio. `api/prototyping/music/lyrics_align.py` is the pure module (LRC text extraction, quality gates, schema assembly, the align→transcribe decision flow; heavy imports stay lazy so the control plane can import it); `lyrics_align_modal.py` is the Modal wrapper (stable-ts 2.19.1 + Whisper `large-v3` + demucs vocal isolation on T4, pinned in `api/requirements-lyrics-modal.txt` — stable-ts is archived upstream, keep pins exact). With no findable text it transcribes instead (`mode: "transcribed"`); an instrumental or hallucinated result publishes nothing. The payload (`schema_version: 1`, `_sec`, 3dp) is `lines[].words[]` with per-word `start_sec`/`end_sec`/`confidence`, published as a `lyrics_timing` asset with run outputs `lyrics_timing_file_id`/`lyrics_timing_version_id`. The edit pipeline backfills older songs via `_ensure_edit_lyrics_timing` (a `lyrics_timing` child run inside the music stage; never blocks or fails the edit; a completed no-words run is a negative cache so GPU isn't re-burned per edit). `_run_agent_timeline_plan` looks the artifact up by audio-version lineage, windows it with `trim_lyrics_timing`, and passes it to the agent.

Heavy audio landmines:

- allin1 and natten belong in Modal, not local installs.
- natten is pinned because allin1 imports deprecated camelCase ops.
- torch, torchaudio, torchvision, CUDA, and natten versions are coupled.
- missing allin1 transitive imports belong in `api/requirements-modal.txt`.

## Video Pipeline

The pipeline is built from Modal-free analysis modules orchestrated by `analysis_cuda.py`:

- `scenes.py`: PySceneDetect scene boundaries, with whole-clip fallback.
- `motion.py`: Farneback optical flow, normalized motion curves, camera movement class, stability, and raw signals.
- `impact.py`: adaptive visual-energy impact/stillness detection.
- `credits.py`: end-credit detection. `decide_content_end` (pure, unit-tested) finds the dense-text credits block by scanning per-frame OCR word counts backward from the end and returns a conservative `content_end_sec = credits_start − 30s` (with guardrails so mid-film text can't truncate the edit); `detect_content_end` does the tail decode + Tesseract OCR (imports cv2/pytesseract lazily; stays Modal-free like scenes/motion).

`analysis_cuda.py` is the (GPU) orchestrator — the only one; the old CPU orchestrator was removed. It decodes sequentially and resets previous-frame state at scene boundaries so optical flow does not cross cuts, then runs `credits.detect_content_end` and adds a `credits` block (`{detected, credits_start_sec, content_end_sec}`) to the `video_analysis` payload. Planning hard-caps the usable source to `content_end_sec`: `_run_agent_timeline_plan` passes it as the agent's source duration, into `adapt(content_end_sec=...)` (clamps every shot's source range), and filters CLIP `query_clips` results beyond it. Older analyses without `credits` fall back to full duration. `analysis_cuda.py` also samples frames through `poster.py` — a pure, unit-tested poster-frame picker (mirrors `credits.py`'s pure-decision pattern: brightness/detail/window-position scoring, no cv2/numpy at module level) — and returns a representative JPEG poster frame (base64) alongside the analysis payload; `run_video_analysis` publishes it as a best-effort `source_poster` asset.

Modal apps:

- `api/prototyping/video/analysis_modal.py`: volume-based prototype app `eclypte-video`.
- `api/prototyping/video/storage_modal.py`: R2-aware API app `eclypte-video-r2`, function `analyze_r2`. Its image bundles `tesseract-ocr` + `pytesseract` (for credit OCR) and `add_local_python_source(... "credits", "poster" ...)`; redeploy `eclypte-video-r2` after changing `analysis_cuda.py`/`credits.py`/`poster.py` (re-analyze a film afterward to populate the new `credits` block and/or its poster thumbnail).

OpenCV-CUDA has no friendly local wheel path. Keep CUDA/OpenCV build complexity inside Modal unless the task explicitly asks for dependency work.

## Edit Pipeline

`api/prototyping/edit/` takes song analysis, source analysis, audio, and video and produces a timeline or rendered MP4.

Subsystems:

- `skills/`: registry of agent-placed creative skills composited over the reel, in four kinds — `overlay` (windowed layer: `text.hook`, `text.caption`, `text.lower_third`, `mask.vignette`), `grade` (whole-reel color), `moment` (short windowed accent), `lyrics` (full-reel word-synced lyric text: `lyrics.kinetic`, selected via finish_edit's dedicated `lyrics` field, not the overlays list). Each skill is one self-contained module declaring `id`, `kind`, an agent-facing `description`, a Pydantic `params_model`, `build_layers(overlay, ctx)` (MoviePy fallback path), and — when ported to the native renderer — `ffmpeg_supported = True` plus `ffmpeg_filter(overlay, ctx)` returning a label-free filter fragment gated with `enable='between(t,S,E)'`. A skill needing a side file (the lyrics .ass document) implements `ffmpeg_assets(overlay, ctx) -> {filename: text}`; the executor materializes those into a scratch dir passed as `ctx.asset_dir` (`wants_shot_stats` requests the renderer's footage sampling pass; `singleton` skills may appear once per timeline, validator-enforced). Skills self-register on import (`register(...)`); the agent tool enum, validators, and both render paths read the registry (`skills.ids()` / `skills.get()` / `skills.agent_catalog()`), so adding/removing a skill is a single module plus one import line in `skills/__init__.py`. Skill metadata, `ffmpeg_filter`, and `ffmpeg_assets` stay moviepy-free (Railway control plane); only `build_layers` imports moviepy/numpy lazily inside the Modal renderer. Text fragments go through `text_common.drawtext_fragment` with **double** escaping (`escape_drawtext_text`/`escape_drawtext_path` — ffmpeg parses the graph then the options, so literals are escaped twice).
- Kinetic lyrics (`lyrics.kinetic`) is the tasteful successor to the old removed synced-lyric burn-ins: word-timed lyric text over the whole reel (silent through instrumental gaps), driven by the `lyrics_timing` artifact the adapter embeds into the overlay params (timeline JSON stays self-contained; word key `word` in the artifact maps to `text` in the params). Three treatments — `sweep` (full line, ASS `\kf` karaoke color-fill word-by-word), `pop` (one big word center-stage on its timestamp), `build` (words accumulate, current word accented) — switchable per song section via `section_styles`. Pure modules: `skills/lyrics_ass.py` (ASS serializer — colors are `&HAABBGGRR` alpha-first **BGR**, `\kf` durations in centiseconds with cumulative rounding, `{}`/`\` sanitized), `skills/lyrics_layout.py` (per-line band picking with hysteresis inside IG safe areas — letterbox bars naturally win; light-vs-dark fill with dark/bright hysteresis so the palette doesn't flicker line-to-line; footage-hue accent with a 3.0 contrast floor checked in LINEAR luminance — zone luma from footage_stats is gamma-encoded and goes through `zone_relative_luminance` first; caps-aware per-font width estimates, and SIZE-CONSTANCY FIRST: lines WRAP into ≤3 `\N` rows via `plan_row_splits` to hold ONE size across the reel — per-line size jitter reads as a glitch — shrinking only when a fully-wrapped line still can't fit; the ASS doc uses WrapStyle 2, so an unfitted line would hard-clip, not wrap). Typography is deliberately prominent: `SWEEP_SIZE_FRAC`/`POP_SIZE_FRAC` in `lyrics_kinetic.py` (pop words share one size per reel), per-font letter-spacing from `FontSpec.spacing_frac` (folded into width estimates), and a soft drop shadow via `SHADOW_FRAC` + a semi-transparent ASS BackColour, `skills/lyrics_fonts.py` (catalog of 10 OFL/Apache static TTFs pinned to one google/fonts commit SHA, families verified against TTF name tables — libass matches by family and falls back **silently** on mismatch). Fonts are NOT committed: the Modal render image downloads them at build time into `/fonts/kinetic`; local dev runs `python -m api.prototyping.edit.skills.fetch_fonts` (gitignored `edit/content/fonts/`); `ECLYPTE_LYRICS_FONTS_DIR` overrides. Renders via ffmpeg's `ass=` filter (libass) on the fast native path; the renderer samples 2-3 decimated frames per shot (`render/footage_stats.py`, moviepy+numpy, no cv2; speed_ramp shots sample their linear first half only) for the adaptive layout — sampling failure degrades to safe defaults, never fails a render. MoviePy fallback: `build_layers` no-ops with a log (same as grades/shake).
- `synthesis/timeline_schema.py`: Pydantic timeline schema. `Timeline.overlays` carries optional `Overlay` items (`skill_id` + window + validated `params`), composited over the shots. `AudioSpec.fade_out_sec`/`OutputSpec.fade_out_sec` carry the end-of-reel fade lengths; the shared `tail_fade_for(duration_sec)` helper clamps the fade to ≤ ⅓ of the reel.
- `synthesis/validators.py`: contiguity and bounds validation, plus registry-driven overlay checks (known `skill_id`, in-bounds window).
- `synthesis/agent.py`: OpenAI Responses API synthesis loop.
- `synthesis/rhythm.py`: the pure rhythm engine (mirrors the `credits.py`/`poster.py` pure-decision pattern — no Modal/moviepy/numpy). Owns the musicality constants and functions: `pick_snap_beat` (downbeat-preferred snap targets with a `CUT_LEAD_SEC`=0.04s early-cut lead — editors cut ~1 frame before the beat), `register_impacts_to_downbeats` (shifts a shot's source window ≤0.75s so its strongest video-analysis impact frame lands on a musical downbeat; timeline positions never move), `pacing_bands_for` (tempo-scaled per-section shot-duration bands, chorus/drop faster than verse), `split_overlong_section_shots` (deterministic backstop: splits a fast-section shot that overruns its band 2× at downbeats, jumping later pieces' source windows so the splits are real cuts), and `sync_report` (JSON-safe musicality telemetry).
- `synthesis/adapter.py`: converts agent output into renderable timelines, dedupes near-duplicate source timestamps, trims song-duration overshoot, runs continuity post-processing, then runs the rhythm engine: pacing-backstop splits, beat-snapping interior cut boundaries (±0.15s, downbeat-preferred, `CUT_LEAD_SEC` early) onto `markers.beats_used_sec` (markers record the musical anchors, not the lead-adjusted positions), and impact→downbeat source-window registration. It also maps optional per-shot `transition_in`/`effect` choices, resolves the agent's optional `overlays` against the skill registry (clamps the window, validates params, and drops invalid/unknown overlays with a log rather than failing the edit), and sets the audio/video `fade_out_sec` via `tail_fade_for`. The agent returns `{"shots", "overlays"}`. `adapt(..., report_sink=)` optionally fills a dict with `{"sync", "impact_registrations", "pacing_splits"}` telemetry (never part of the timeline contract).
- `index/frames.py`: sequential frame extraction. Do not revert to per-frame `CAP_PROP_POS_MSEC` seeking on long videos.
- `index/embed.py`: CLIP frame/text embeddings.
- `index/query.py`: `rank_with_content_filter` (ranks CLIP results, dropping near-black/flat frames) — runs inside `eclypte-clip-index-r2`. The agent has no default query path; `workflows.py` always passes an explicit `query_clips_fn` closure hitting `query_index_r2`.
- `index/storage_modal.py`: R2-aware API CLIP app `eclypte-clip-index-r2`, with `build_index_r2` and `query_index_r2`. The build records per-frame `brightness`/`detail` in the index; `query_index_r2` ranks through `query.rank_with_content_filter`, which drops near-black and flat frames (black intros/outros, credits, title cards) so the agent can't select them. Bump `CLIP_INDEX_BUILD_STEP` in `api/workflows.py` (and reindex) when the index format changes; redeploy `eclypte-clip-index-r2` after changing this.
- `reference/`: reference AMV download, metrics, and ingest (the offline consolidate CLI and prompt-weight parsing were removed — reference guidance flows through the runtime style-profile loop and `run_synthesis_consolidation`).
- `render/renderer.py`: `render_timeline` is the entry point. It validates, then **dispatches** (via `can_render_with_ffmpeg`): timelines using cuts/crossfade/whip/`flash`, `freeze`/`punch_in` effects, and any overlay skill with an ffmpeg port render through a single native ffmpeg filtergraph — ~17× faster on the same hardware because pixels never leave ffmpeg (MoviePy's ~97% overhead was the per-frame Python decode→numpy→pipe pump, not the x264 encode). Only features without a native port fall back to the MoviePy v2 path in the same file (now a legacy fallback). The MoviePy path reads timeline JSON + media only, composites `timeline.overlays` over the concatenated shots before attaching audio, applies the end-of-reel audio fade-out + video fade-to-black (`render/fades.py`, via `clip.transform`), saves an RGB JPEG poster (after compositing, so overlays show), reports progress via proglog's `frame_index` bar. Both paths resolve the overlay font via `ECLYPTE_OVERLAY_FONT` → `/fonts/overlay.otf` → bundled DejaVu (the fast path passes it into `build_command(font_path=...)` for `drawtext`).
- `render/ffmpeg_filtergraph.py`: **pure** builder — a validated `Timeline` → ffmpeg argv (per-shot seeked input → scale/letterbox-or-cover-crop → per-shot effect chains — `freeze` = 1-frame input + `tpad` clone + exact re-trim, `punch_in` = fps-normalize → `zoompan` → `setpts` PTS renumber (zoompan stamps PTS in its own timebase — without the renumber a downstream fps filter fills phantom gaps by duplicating every frame ~512×), `flash` = three stepped `eq=brightness` windows approximating the sine bloom → concat, with crossfades folded into chained `xfade` at cumulative offsets; then overlay-skill fragments applied to the assembled stream before the tail fade; audio trim/gain, the end-of-reel `afade` + video `fade`, and the same CRF 18 / `-tune animation` / yuv420p / 192k AAC encode). No subprocess/moviepy, so it is fully unit-tested (`test_ffmpeg_filtergraph.py`). `can_render_with_ffmpeg` lives here and is **capability-driven**: `FFMPEG_TRANSITIONS`/`FFMPEG_EFFECTS` plus each overlay skill's `ffmpeg_supported` flag — a newly ported skill extends the fast path without touching the gate.
- `render/ffmpeg_run.py`: runs that argv as one process, parses `-progress` into the same `progress_callback` 0–100 contract, then extracts the JPEG poster. Resolves the ffmpeg binary via PATH → `imageio_ffmpeg`.
- `render_storage_modal.py`: R2-aware API renderer `eclypte-render-r2` (uploads the rendered MP4 and the poster image). Its image bundles `ffmpeg` and downloads the kinetic-lyrics font catalog into `/fonts/kinetic` at build time (URLs generated from `skills/lyrics_fonts.py` at deploy time — one source of truth), with a build-time `ffmpeg -filters | grep -qw ass` assert so a libass-less image fails the build, not a live render. Redeploy after changing the render package or the font catalog.

Agent planning defaults:

- Timeline planning is always the OpenAI/CLIP agent (there is no other mode).
- `synthesis/agent.py` currently uses `MODEL = "gpt-5.5"`, `reasoning_effort="high"`, and `verbosity="low"`.
- The baseline system prompt has ONE source of truth: `synthesis/system_prompt.py` (`SYSTEM_PROMPT`). `agent.py` imports it as its fallback; `workflows.py`/`app.py` import it as `DEFAULT_SYNTHESIS_PROMPT` (the default prompt-version text and the consolidation base). Edit the prompt only there — do not re-inline it.
- Responses API state is carried through `previous_response_id`; do not re-upload full message history each loop.
- Tools are `query_clips(query, top_k)` and `finish_edit(timeline)`; timeline items optionally carry `transition_in` (`cut`/`flash`/`crossfade`) and `effect` (`freeze`/`punch_in`). `finish_edit` also takes optional top-level `overlays`, `grade`, and `lyrics` ({enabled, font, style, section_styles?, accent_color?} — the kinetic-lyrics plan; the overlays skill_id enum excludes `grade`/`lyrics` kinds so lyrics can't be double-placed).
- `query_clips` results are enriched on the control plane (`_enrich_clip_results` in `api/workflows.py`) with per-scene `motion` (0–1 avg intensity), `camera` (camera-movement class), and `impact_near` (an impact frame within 0.5s) from the video analysis, so the agent can match footage energy to song energy. Fields are omitted for older analyses.
- The agent receives the source duration and is instructed to span the full source start→end regardless of song length, so short/trimmed edits still cover the whole film. This guidance is injected into the per-run user content (so it applies regardless of the active prompt version); nothing enforces it (no validator/forced spread), preserving the agent's freedom to dwell on standout moments.
- The agent also receives per-run pacing targets (`_format_pacing_context` in `agent.py`): tempo-scaled shot-length bands per song section from `rhythm.pacing_bands_for`, plus the note about the enriched query fields. The adapter's split backstop only enforces egregious (2×-band) violations in fast sections — the guidance is what makes the agent hit the bands on its own.
- When a `lyrics_timing` artifact exists for the song, the agent also receives a word-timed lyrics block (`_format_lyrics_context` in `agent.py`, trimmed to the audio window, times rebased to the edit timeline): per-word rows up to `LYRICS_WORD_DETAIL_MAX`=350 words, per-line rows beyond, a recognition-errors caveat in `transcribed` mode, and guidance for three uses — literal word→imagery match cuts at exact word timestamps, emotional-arc footage matching per section, and anchoring the strongest shots on hook/title-drop line starts. The block ends with the kinetic-lyrics rendering offer (`_format_lyrics_rendering_options`): the font menu with vibe descriptions, the three style treatments, guidance to ENABLE on-screen lyrics BY DEFAULT when word timing exists (unless the brief wants a text-free look), and — in `transcribed` mode — a caution to only enable when the transcript reads clean (misheard words would burn into the reel). No lyrics → no block, and the agent omits the `lyrics` field entirely.
- `_run_agent_timeline_plan` threads the agent's `lyrics` plan plus the windowed timing payload into `adapt(lyrics_plan=..., lyrics_timing=...)`; the adapter's `_resolve_lyrics` emits one full-reel `lyrics.kinetic` overlay ordered grade → lyrics → agent overlays (an invalid plan is dropped with a log, never failing the edit) and records `{enabled, font, style, word_count}` in the `timeline_sync_report` telemetry.
- Reference-derived style profiles: `synthesis/style_profile.py::derive_style_profile` turns completed synthesis-reference metrics into rhythm-engine overrides — `cut_lead_sec` (median cut-before-downbeat lead, clamped to ≤0.08s) and `pacing_bands_beats` per section (from median `cuts_per_downbeat`, 4-beat bars). `_run_agent_timeline_plan` computes the profile fresh at plan time from `repo.list_synthesis_references` (nothing persisted — a newly ingested reference shapes the very next edit), threads it into both the agent's pacing context and `adapt(style_profile=...)`, and records it on the `timeline_sync_report` event.
- The agent is instructed to never select black frames, solid colors, title cards, logos, or end credits, and to span the end of the *content* (not the trailing credits/black). Credits/title avoidance is now three-layered:
  1. **CLIP text-negative filter** (`index/query.py::TEXT_NEGATIVE_PROMPTS` + `query_index_r2`): every frame's stored embedding is compared against title-card/credits text prompts; a frame more similar to those than to the actual query (above `TEXT_NEG_THRESHOLD`) is dropped from `query_clips` results. Catches BRIGHT title cards and colored-background credits that the brightness/detail filter passes, and works retroactively on existing indexes (no reindex — but redeploy `eclypte-clip-index-r2`).
  2. **Prompt** (`system_prompt.py` + the per-run source context in `agent.py`): both ends of the source are hazardous (logos/titles/opening credits at the head, credits at the tail); every `source_timestamp` must come from a `query_clips` result — never invented, especially near either end.
  3. **Adapter anchor guard** (`adapter.py::_guard_anchor`, active when `workflows.py` passes the plan's collected `query_anchors`): an anchor inside the head/tail danger zones (`_anchor_guard_sec`: 3% of the usable source, clamped 10–90s) that no query result backs (±2s) is relocated to the nearest query-backed timestamp outside the zones, recorded as `anchor_relocations` in the `timeline_sync_report`.
  The durable tail cap remains `content_end_sec` from credit OCR (needs a present/up-to-date `credits` block — re-analyze older films).
- Agent mode may create/reuse `clip_index` assets and records `clip_index_file_id`, `clip_index_version_id`, and `synthesis_prompt_version_id`.
- Agent failures should fail visibly via `RunManifest.last_error`; there is no fallback planner.

Rendering notes:

- `render_timeline` depends on timeline JSON, source video, and song audio, and auto-dispatches between the native ffmpeg path and the MoviePy fallback (see above). The native path is verified frame-parity with MoviePy on the same timeline (deep-in-shot frames pixel-near-identical; deviations of ≤~1 frame only at cut boundaries / high motion, within the ±0.15s beat-snap tolerance).
- MoviePy v2 (fallback path) methods include `subclipped`, `with_duration`, `resized`, `concatenate_videoclips(method="compose")`, and `with_audio`.
- Implemented effects/transitions: `flash`/`crossfade` transitions and `freeze`/`punch_in`/`speed_ramp` effects — all supported on BOTH render paths. `speed_ramp` plays the shot's first half at 1x and accelerates the second half to 1.5x into the next cut (`SPEED_RAMP_END`/`SPEED_RAMP_SOURCE_FACTOR` in `timeline_schema.py` are the shared contract): the adapter extends the shot's source window to 1.25× its duration (dropping the effect with a log when the usable source can't cover it), beat-snap skips ramp-adjacent boundaries, and impact registration skips ramp shots (their second half breaks the 1:1 time mapping). On ffmpeg it renders as two input windows (`_ramp_chains`) concatenated; on MoviePy as a `time_transform` warp applied before the duration is pinned. `whip` renders as a hard cut everywhere; `hold` is still a no-op stub. The agent opts in per shot via optional `transition_in`/`effect` fields on `finish_edit` items, mapped in `synthesis/adapter.py`.
- Creative skill catalog beyond text/vignette: three `grade.*` presets (`cinematic`/`vibrant`/`moody` — whole-reel eq/colorbalance fragments; the agent picks at most one via finish_edit's optional `grade` field, and the adapter maps it to a full-reel overlay placed FIRST so text/moments draw over graded footage) and `impact.shake` (`kind="moment"` — a ~0.4s pad+crop jitter gated to its window). Grades and shake are ffmpeg-only (`build_layers` returns `[]` with a log on the MoviePy path — effectively unreachable since everything else is ported). When the agent places no moment skill itself, the adapter auto-accents the strongest impact+downbeat registrations with up to 2 `impact.shake` windows (`rhythm.auto_accent_overlays`; registrations now carry `intensity`).
- The adapter beat-snaps interior shot boundaries within ±0.15s (`snap_shots_to_beats` via `rhythm.pick_snap_beat`: downbeats beat nearer plain beats, and the boundary lands `CUT_LEAD_SEC`=0.04s ahead of the anchor), records the anchors in `markers.beats_used_sec`, and never collapses a shot below 0.4s. A `timeline_sync_report` run event on the timeline run records on-beat/on-downbeat percentages, impact registrations, and pacing splits per plan.
- Both render paths apply an end-of-reel tail fade (audio fade-out + video fade-to-black) over the reel's final seconds: native ffmpeg emits `afade`/`fade`; the MoviePy fallback uses `render/fades.py` (`audio_fade_out`/`video_fade_out` via `clip.transform`). Length comes from `timeline.audio.fade_out_sec`/`timeline.output.fade_out_sec`, set by the adapter through `tail_fade_for` (≤ ⅓ of the reel). The fade is just filters/transforms, so it does not push a cuts/crossfade timeline off the fast native path, and the mid-clip poster is unaffected.
- The encoder writes CRF 18 / `-tune animation` / yuv420p with 192k AAC so Instagram/YouTube re-encodes start from a high-quality source (identical flags on both paths).
- The native ffmpeg path encodes on CPU in seconds; a GPU/NVENC path is unnecessary for the common montage and is not worth the CUDA-ffmpeg image cost. The MoviePy fallback remains CPU-pump-bound (vCPU count barely helps it).
- Edit `progress_percent` is a weighted average by typical stage duration (`EDIT_STAGE_WEIGHTS` in `api/app.py`), and the render stage fills smoothly from the renderer's real encode progress. The dashboard shows the poster instantly and lazy-loads the heavy MP4 on play.

## Frontend

Before changing Next.js code, read relevant docs under `web/node_modules/next/dist/docs/`. This project uses Next.js 16, where conventions may differ from memory. The proxy/middleware file is `web/src/proxy.ts`, not `middleware.ts`.

Frontend architecture:

- `web/src/app/layout.tsx`: fonts and app shell providers.
- `web/src/app/page.tsx`: marketing landing page.
- `web/src/app/pricing/page.tsx`: marketing pricing page — three tiers (Free/Creator/Studio) + FAQ.
- `web/src/app/demo/page.tsx`: marketing "Screening Room" demo page. Poster-first lazy video via `web/src/components/demo/demoPlayer.tsx` (`DemoReel`/`DemoTile`); posters in `web/public/demo/posters/` and web-optimized 1080p sources in `web/public/demo/web/` (the unreferenced 4K originals were removed from the tree; they remain in git history).
- `web/src/app/dashboard/layout.tsx`: dashboard shell — a top bar (brand, Home/Library nav links, a Settings icon, sign-out); the old sidebar was retired (`web/src/components/dashboard/sidebar/` is gone).
- `web/src/app/dashboard/page.tsx`: the Home pipeline feed at `/dashboard`, the dashboard's default/index page. It absorbed the old autopilot and publish pages: an autopilot status line (enable/pause switch, daily-target `Select`, halt banner with Resume), a "Ready for you" review-card grid (approve/edit captions/send to Buffer — the old `/dashboard/publish` review queue), "In the works"/"Up next" live job and backlog rows, a "Posted" strip, and two `Sheet`-based flows: `ReviewSheet` (approve/caption/queue/schedule/post-now/mark-as-posted) and `ComposerSheet` (add a film + saved-song backlog item with an optional creative brief).
- `web/src/app/dashboard/new-edit/page.tsx`: compose/edit pipeline UI. Not linked from the top bar, but still routable directly.
- `web/src/app/dashboard/assets/page.tsx`: the Library at `/dashboard/assets` — Films/Songs/Reels tab pills (`?tab=` query param) plus a Hidden link, replacing the old Sources/Derived/Hidden tabs and absorbing the render-output library (Reels tab). Upload cards report real byte progress (XHR `upload.onprogress`, via `uploadToPresignedUrl`'s optional `onProgress` callback) instead of an all-or-nothing spinner. The library paginates at 12/page (10 for Songs).
- `web/src/app/dashboard/synthesis/page.tsx`: references and prompt management. Not linked from the top bar; reachable via the "Tune how your reels are edited" link on `/dashboard/settings`.
- `web/src/app/dashboard/publish/page.tsx`, `web/src/app/dashboard/autopilot/page.tsx`: redirect stubs to `/dashboard` — their functionality now lives in the Home feed.
- `web/src/app/dashboard/renders/page.tsx`: redirect stub to `/dashboard/assets?tab=reels`.
- `web/src/app/dashboard/settings/page.tsx`: API/user/prompt health plus realtime (Redis), worker-progress, and always-on-creation (autopilot loop) status; an Advanced disclosure holds the raw API base URL and account id (behind `CopyableId`).
- `web/src/app/dashboard/dashboardCommon.tsx`: shared dashboard page wrapper, skeleton placeholders (`Skeleton`/`SkeletonList`), formatting/humanizing helpers (`formatBytes`/`formatDate`/`kindLabel`/`humanizeLabel`/`statusLabel`/`humanizeStageDetail`/`formatClock`/`stripExtension` — `kindLabel`, `statusLabel`, and `StatusBadge` turn raw enum/kind strings into creator-facing words, e.g. `song_audio` → `Song Audio`, `ready` → `Ready to review`), client-side list pagination (`usePagination` + the `Pager` control used by every big dashboard list; pass a `resetKey` such as the active tab/filter to reset to page 1), the `errorMessage`/`isAbortError` error helpers, `useAbortableLoad` (still used by `/settings`; the data pages load through `web/src/stores/` instead), and the shared feedback-tier primitives: `Spinner`, `ProgressRow` (spinner + human stage sentence + a real progress bar), `Sheet` (the one modal pattern — right slide-over on desktop, bottom sheet on mobile; Escape closes, body scroll locks), `ToastProvider`/`useToast` (quiet confirmations, mounted once in `layout.tsx`), plus `EmptyState`, `MetaList` (replaces `JSON.stringify` dumps), and `CopyableId` (hides raw IDs behind a copy affordance).
- `web/src/app/dashboard/editEta.ts`: render/edit ETA estimation (`useNow`, `useRenderEta`, `EDIT_STAGE_WEIGHTS`) extracted out of `new-edit/page.tsx` so other pages' job rows can share it.
- `web/src/app/dashboard/posterUrls.ts`: `posterKey`/`stableMediaUrl` + `assetPosterUrl`/`postPosterUrl`/`postRenderUrl` — signed media URLs arrive inside list payloads; `stableMediaUrl` pins the first-seen URL per content key (~50 min) so refetches/navigation keep img/video srcs byte-identical (browser cache hits) and preconnects the media origin at runtime. Loading states use geometry-matched skeletons (`MediaGridSkeleton` etc. in `dashboardCommon`) gated on `isLoading`; thumbnails render through `FadeImg`.
- `web/src/stores/`: a zustand stale-while-revalidate cache shared across dashboard pages — `dashboardStore.ts` (generic per-key resource cache, in-flight dedup, latest-wins), `useResource.ts` (the SWR hook → `{ data, isLoading, error, revalidate, set }`), and `dashboardResources.ts` (typed, user-scoped wrappers: `useAssets`, `useEditJobs`, `usePublishingPosts`, `useSynthesisReferences`, `useSynthesisPrompt`, `useAutopilot`). Keys are scoped by `EclypteApiClient.userId`; signed URLs are never cached in the resource store (the `posterUrls.ts` `stableMediaUrl` pin is the one deliberate exception, keyed by immutable file+version). `web/src/stores/README.md` documents the design, page→resource map, and editing gotchas.
- `web/src/app/dashboard/useRunStream.ts`: shared hook that subscribes to `/v1/runs/stream` with a debounced refresh callback, a ~15s safety-poll watchdog that reconciles a connected-but-silent stream, and a 1s polling fallback when the stream fails; used by the Home, new-edit, and Library (Reels) pages.
- `web/src/services/eclypteApi.ts`: typed browser API client. Extend this before adding ad hoc fetch calls.

Run streams are newline-delimited JSON. Use `readJsonLineStream()` and `drainJsonLines()` from `eclypteApi.ts`; keep polling fallback logic because Redis may be absent or stale.

Dashboard data loading uses the `web/src/stores/` zustand SWR cache: route each page's primary list through a typed `useResource` wrapper, so navigation serves cached data instantly and revalidates in the background (TTL ~30s) with in-flight dedup and latest-wins. Mutations patch the cache via the hook's `set` (value or updater) instead of re-pulling the whole collection (archive/restore/delete patch the array in place); `useRunStream` and the Home page's Buffer-poll refresher call `revalidate`. A fetch is deliberately not aborted on unmount — finishing it populates the shared cache (latest-wins + dedup keep it correct). One non-obvious rule remains: the Synthesis prompt textarea is user-owned — a background revalidate must not overwrite unsaved edits (guarded by a last-seeded-value dirty check, `lastSeededRef`).

The dashboard's visual identity is "Ivory & Ink" — a light, warm system (ivory `#F7F5F1` surfaces, ink `#26231E` text, a coral `#E86A4F` accent reserved for progress/attention, not decoration) defined as CSS custom properties under `[data-surface="studio"]` in `web/src/app/globals.css` and applied via `data-surface="studio"` on the dashboard container in `layout.tsx`. It replaced the earlier dark "Edit Bay" identity; token *names* (`--surface-*`, `--text-*`, `--line*`, `--accent*`, `--ok`/`--danger`/`--attention`, `--font-*`) are unchanged so component CSS didn't need touching when the values swapped. One typeface everywhere — PP Neue Montreal (`--font-display`/`--font-ui`, local `.otf` files) — and sentence case only: no `text-transform: uppercase` and no positive `letter-spacing` anywhere in `web/src/app/dashboard/studio.module.css`. The marketing site (`/`, `/pricing`, `/demo`) keeps its own separate dark `--color-*`/`[data-theme="dark"]` theme, untouched by this redesign.

The frontend depends on these output keys:

- `music_analysis_file_id`, `music_analysis_version_id`
- `video_analysis_file_id`, `video_analysis_version_id`
- `timeline_file_id`, `timeline_version_id`
- `render_output_file_id`, `render_output_version_id`
- `render_poster_file_id`, `render_poster_version_id`
- `clip_index_file_id`, `clip_index_version_id`
- `synthesis_prompt_version_id`

`source_poster_file_id`/`source_poster_version_id` on a `video_analysis` run's outputs are additive and best-effort (not required — a missing poster is not an error); the frontend resolves them into `AssetSummary.poster` rather than reading them directly off run outputs. `lyrics_file_id`/`lyrics_version_id` and `lyrics_timing_file_id`/`lyrics_timing_version_id` are likewise additive and best-effort — the frontend does not read them; `lyrics_timing` assets stay out of the Library (its tabs filter positively by kind).

Styling uses CSS Modules and the existing dashboard/landing visual language. Shared services and components should stay typed and colocated with their CSS where that pattern already exists.

## Modal Apps

API-facing R2-aware apps:

- `eclypte-analysis::analyze_remote` from `api/prototyping/music/analysis_modal.py`
- `eclypte-lyrics::align_lyrics_remote` from `api/prototyping/music/lyrics_align_modal.py` (word-level lyrics forced alignment; own slim T4 image from `api/requirements-lyrics-modal.txt` + `lyrics-align-cache` volume — the fragile allin1 image is untouched; redeploy after changing `lyrics_align.py`)
- `eclypte-video-r2::analyze_r2` from `api/prototyping/video/storage_modal.py`
- `eclypte-clip-index-r2::build_index_r2` and `query_index_r2` from `api/prototyping/edit/index/storage_modal.py`
- `eclypte-render-r2::render_r2` from `api/prototyping/edit/render_storage_modal.py`

Prototype/volume apps:

- `eclypte-video` (used in production by synthesis reference ingest via `analyze_remote_bytes`)

Modal wrappers should use pure local modules through `add_local_python_source()` or explicit storage wrappers. Pure analysis modules should not import Modal.

Shared wrapper helpers live at the `api/prototyping/` root: `modal_s3.py` (S3/R2 client + object download) and `progress_events.py` (progress emission). Import them by bare module name inside Modal function bodies, list them in each app's `add_local_python_source()`, and deploy from `api/prototyping/` so they resolve.

`add_local_python_source()` snapshots local code at `modal deploy` time. Pushing to Railway does NOT update Modal: after changing anything inside the bundled `edit` package that the renderer uses (`edit/render/**`, `edit/skills/**`, `edit/synthesis/timeline_schema.py`, `edit/synthesis/validators.py`), redeploy `eclypte-render-r2` or live renders keep running the old code (and may reject timelines that use newer schema values, or silently drop overlays whose skills the old image lacks). `eclypte-clip-index-r2` also bundles `edit` but only needs a redeploy when index code changes. On Windows, prefix `modal` commands with `PYTHONUTF8=1` (or `$env:PYTHONIOENCODING="utf-8"`) — the CLI prints Unicode glyphs that crash the default charmap console.

## Testing Guidance

- Backend behavior changes: run focused tests near the changed module, then `python -m pytest api -v` when feasible.
- API contract changes: run `python -m pytest api/test_api_v1.py -v` and update `web/src/services/eclypteApi.ts`.
- Storage changes: run `python -m pytest api/storage -v`.
- Publishing changes: run `python -m pytest api/test_publishing.py -v`.
- Export option changes: run `python -m pytest api/test_export_options.py -v`.
- Synthesis/index changes: run `python -m pytest api/prototyping/edit/synthesis api/prototyping/edit/index -v`.
- Frontend changes: from `web/`, run `npm run lint` and `npm run build`.

`pytest.ini` disables pytest's cache provider and sets temp-path retention to zero to reduce `.pytest*` artifacts.

## Current Focus & Next Steps (July 2026)

The active push is edit quality — making reels *feel* musically cut, not just land on beats. Phase 1 (the rhythm engine, `synthesis/rhythm.py`) is implemented: downbeat-preferred snapping with an early-cut lead, impact→downbeat source-window registration, tempo-scaled per-section pacing (agent guidance + a deterministic split backstop for fast sections), motion/impact-enriched `query_clips` results, and `timeline_sync_report` telemetry per plan. All of it stays on the fast native ffmpeg render path and needs no Modal redeploys.

Autopilot context (previous push, still live): review-gated packages rendered as `reels_cinematic` (native 1080x1920, baked-in bars) from ~20–30s energy-ranked windows (≈25s, 5s chorus lead-in), an audio+video tail fade, and a CRF 18 encode. Captions name the source movie/anime + song with context-relevant AI hashtags.

Operational checklist:

- QA the first post-rhythm-engine reel: cuts should land a hair *before* beats (deliberate — `CUT_LEAD_SEC`), choruses should visibly cut faster than verses, and at least one visual hit should land on a downbeat. Check the run's `timeline_sync_report` event for the numbers.
- QA the first kinetic-lyrics reel: words should land ON the vocal onsets (a constant offset means a windowing/rebasing bug); the sweep fill should complete exactly at each word's end; text must stay out of the IG UI zones and stay readable on the brightest and darkest shots; placement shouldn't hop bands line-to-line; letterboxed `reels_cinematic` reels should favor the bars; each font must render as itself (a DejaVu-looking fallback means a family-name mismatch); `timeline_sync_report` carries the `lyrics` telemetry.
- Confirm `ECLYPTE_AUTOPILOT=1` (and optionally `ECLYPTE_AUTOPILOT_INTERVAL_SEC`) is set on Railway; `/healthz` reports `autopilot_loop_configured`. Without it, ticks are manual.

All four phases of the edit-quality roadmap are implemented: the rhythm engine (Phase 1), the ffmpeg polish foundation (Phase 2 — skill kinds, capability-driven dispatch, flash/freeze/punch_in/vignette/drawtext ported native), the polish catalog (Phase 3 — grade presets, impact.shake + auto-accents, real speed_ramp), and reference-derived style profiles (Phase 4 — plan-time rhythm overrides from reference metrics). On top of them sits **kinetic lyrics** (July 2026): the `lyrics.kinetic` skill, ASS/libass rendering, the footage-adaptive layout engine, the pinned font catalog, and agent default-on lyric plans. **Redeploy `eclypte-render-r2` before the next real render** — the bundled render/skills/schema code changed AND the image itself changed (kinetic fonts + libass assert).

Deferred, in rough priority order:

- Text-behind-subject masking for kinetic lyrics (needs a GPU segmentation matte; the params schema keeps a `masking` slot).
- `whip` transition and `hold` effect (still cut/no-op).
- YouTube publishing path (16:9 renders already exist; no upload integration).
- Retention experiment: the "span the full source" prompt rule turns a ~25s reel into a whole-film montage — once IG insights accumulate, test single-scene reels against it and revisit the rule.
- Per-shot crop focus for fill-mode reels; posting-time optimization stays in Buffer.

## Working Rules

- Prefer existing repository boundaries and helpers over new parallel abstractions.
- Keep storage, API, frontend client, and dashboard UI in sync when contracts change.
- Do not commit secrets, `.env` files, cookies, Modal tokens, or OpenAI keys.
- Do not install heavy ML stacks locally unless the task is explicitly dependency work.
- Keep `AGENTS.md`, `web/AGENTS.md`, `api/COMMANDS.md`, and this file reconciled when architecture or commands change.
- Preserve unrelated local changes.
