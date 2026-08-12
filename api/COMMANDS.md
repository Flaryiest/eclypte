# Eclypte — Command Runbook

Every command below is shown twice: once in **PowerShell** (what the project uses on Windows) and once in **bash / zsh**. Paths use forward slashes throughout — both shells accept them.

Unless noted, run from the **repo root**. A few Modal commands must run from `api/prototyping/` — those are called out.

---

## One-time setup

Activate the venv every session:

```powershell
# PowerShell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
. .venv/Scripts/Activate.ps1
```

```bash
# bash / zsh
source .venv/bin/activate
```

First-time-only (the venv lives at the repo root):

```powershell
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r api/requirements.txt
modal token new       # browser-based Modal auth, writes ~/.modal.toml
```

Secrets (`api/prototyping/edit/synthesis/.env`):

```
OPENAI_API_KEY=sk-...
```

The synthesis agent (`api/prototyping/edit/synthesis/agent.py`) reads this via `load_dotenv()`.

---

## Cloud REST API V1

The Railway-ready FastAPI app lives in `api/app.py` and is exposed by
`api/main.py`. It keeps media artifacts and file metadata in R2. When
`DATABASE_URL` is set, run manifests, run events, and latest stage progress are
stored in Postgres; otherwise the app falls back to the original R2 JSON run
store. When `REDIS_URL` is set, run updates are also published to a realtime
stream for dashboard UX; Redis is not durable state. Workflow endpoints return
immediately while background tasks call Modal for analysis, planning, and rendering.

Required storage env for real `/v1/*` calls:

```powershell
$env:ECLYPTE_R2_ACCOUNT_ID="..."
$env:ECLYPTE_R2_BUCKET="eclypte"
$env:ECLYPTE_R2_ACCESS_KEY_ID="..."
$env:ECLYPTE_R2_SECRET_ACCESS_KEY="..."
$env:ECLYPTE_R2_REGION_NAME="auto"
$env:ECLYPTE_DEFAULT_USER_ID="local_dev"
# Optional Postgres run/progress store:
$env:DATABASE_URL="postgresql://..."
$env:REDIS_URL="redis://..."
$env:ECLYPTE_INTERNAL_PROGRESS_URL="https://<api-host>/internal/progress"
$env:ECLYPTE_INTERNAL_PROGRESS_TOKEN="..."
```

```bash
export ECLYPTE_R2_ACCOUNT_ID="..."
export ECLYPTE_R2_BUCKET="eclypte"
export ECLYPTE_R2_ACCESS_KEY_ID="..."
export ECLYPTE_R2_SECRET_ACCESS_KEY="..."
export ECLYPTE_R2_REGION_NAME="auto"
export ECLYPTE_DEFAULT_USER_ID="local_dev"
# Optional Postgres run/progress store:
export DATABASE_URL="postgresql://..."
export REDIS_URL="redis://..."
export ECLYPTE_INTERNAL_PROGRESS_URL="https://<api-host>/internal/progress"
export ECLYPTE_INTERNAL_PROGRESS_TOKEN="..."
```

CORS defaults to `https://eclypte.vercel.app`, `http://localhost:3000`, and
`http://127.0.0.1:3000`. Override with a comma-separated
`ECLYPTE_CORS_ORIGINS` value if needed.

Run locally from the repo root:

```powershell
$env:PORT="8000"
python -m api.main
```

```bash
PORT=8000 python -m api.main
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

```bash
curl http://127.0.0.1:8000/healthz
```

Routes:

- `POST /v1/uploads` reserves a file/version/blob key and returns a presigned R2 PUT URL.
- `POST /v1/uploads/{upload_id}/complete` validates the uploaded object and records metadata.
- `GET /v1/files/{file_id}` and `GET /v1/files/{file_id}/versions/{version_id}` read manifests.
- `GET /v1/files/{file_id}/versions/{version_id}/download-url` returns a presigned R2 GET URL.
- `POST /v1/music/analyses`, `POST /v1/video/analyses`, `POST /v1/timelines`, and `POST /v1/renders` create run manifests and schedule background work. Renders publish a `render_output` MP4 and a `render_poster` JPEG thumbnail.
- `GET /v1/publishing/config` reports non-secret Buffer/OpenAI/public-media setup.
- `GET /v1/publishing/posts` (each post carries a `performance_score` scored against the account's recent published cohort), `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer`, `POST /v1/publishing/posts/{post_id}/refresh-status` (back-fills the live permalink from Buffer, and — for a `published` post — pulls the latest per-post metrics too; a metrics-pull failure logs and is swallowed, never surfaced as an error), `POST /v1/publishing/posts/{post_id}/mark-posted` (manual override when a sent post can't be reconciled from Buffer), and `POST /v1/publishing/posts/{post_id}/cancel` manage review-gated Buffer publishing packages (sent as Instagram Reels). `cancel` on a `queued`/`scheduled` post now deletes it from Buffer first (the human veto) — it fails with a 502 and leaves the post untouched if Buffer refuses the delete.
- `GET /v1/runs/{run_id}` and `GET /v1/runs/{run_id}/events` inspect workflow status.
- `GET /v1/runs/stream` and `GET /v1/runs/{run_id}/stream` stream Redis-backed run updates when `REDIS_URL` is configured.
- `POST /internal/progress` records worker progress and requires `X-Eclypte-Internal-Token`.

Buffer publishing environment:

```powershell
$env:BUFFER_API_KEY="..."
$env:BUFFER_INSTAGRAM_CHANNEL_ID="..."
$env:ECLYPTE_R2_PUBLIC_BASE_URL="https://media.example.com"
$env:OPENAI_API_KEY="..."
$env:ECLYPTE_CAPTION_MODEL="gpt-5.4-mini"
```

```bash
export BUFFER_API_KEY="..."
export BUFFER_INSTAGRAM_CHANNEL_ID="..."
export ECLYPTE_R2_PUBLIC_BASE_URL="https://media.example.com"
export OPENAI_API_KEY="..."
export ECLYPTE_CAPTION_MODEL="gpt-5.4-mini"
```

Operational assumption: the Buffer channel's own posting schedule (e.g. 2 slots/day) is
configured in Buffer's dashboard, not here — it's what actually paces posts to Instagram, so
autopilot's `daily_target` (below) should match it.

A queued post deleted directly in Buffer's UI converges automatically: the tick's
hourly status reconcile marks it `canceled` locally within the hour (a phantom
"queued" record would otherwise count against the send ceiling and creation brake).

Deploy-time check: the cancel veto's `deletePost` GraphQL mutation shape was written
against Buffer's documented conventions but has not been confirmed against the live
schema — verify a cancel round-trip on a queued post before trusting `auto_publish`
unattended.

Deploy-time check (performance feedback loop, Phase 1): the live-probe step for
`BufferClient.get_post_metrics` was skipped during implementation (no `BUFFER_API_KEY`
available locally) — run it against a real sent post as soon as a key is available and
record which metric `name`s Buffer actually populates for Instagram Reels (floor
expectation per Buffer's Analyze docs: `impressions`/`likes`/`comments`; hoped-for:
`views`/`reach`/`saves`/`shares`/`totalTimeWatched`):

```bash
curl -s https://api.buffer.com -H "Authorization: Bearer $BUFFER_API_KEY" \
  -H "Content-Type: application/json" -d '{
  "query": "query PostMetrics($input: PostInput!) { post(input: $input) { id metricsUpdatedAt metrics { type name value unit } } }",
  "variables": {"input": {"id": "<a real sent buffer_post_id from R2 post JSON>"}}
}' | python3 -m json.tool
```

The implementation is deliberately shape-agnostic (stores whatever metric names arrive),
so a floor-only result needs no code change — just update the dashboard's `METRIC_LABELS`
map (`web/src/app/dashboard/page.tsx`) if a hoped-for name never shows up and its row
should be dropped instead of falling through `humanizeLabel`. Also record the live
`sentAt` format Buffer returns — the stored `posted_at` should parse as
`%Y-%m-%dT%H:%M:%SZ`; if Buffer emits another form, normalize it in `apply_buffer_status`.

Licensing note: Buffer post metrics are licensed for "personal workflows and automations
only" (the personal API key Eclypte uses). That's fine for the current single-operator
product but is a known blocker before any multi-tenant launch — the documented upgrade
path is a direct Meta "Instagram API with Instagram Login" integration (full Reels
metrics: views, reach, saves, shares, avg watch time, skip rate; needs a Meta app + a
60-day token with a dead-man refresh), not built in Phase 1.

Publishing smoke:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/v1/publishing/config" `
  -Headers @{"X-User-Id"="local_dev"}
```

```bash
curl -H "X-User-Id: local_dev" \
  http://127.0.0.1:8000/v1/publishing/config
```

Publishing is review-gated in the dashboard Home feed (`/dashboard`; the old
`/dashboard/publish` page now redirects there). Public R2 copies under
`public/publishing/` and Buffer posts are created only when a user queues or
schedules a package.

Direct Graph API publishing (`ECLYPTE_PUBLISH_PROVIDER=graph`): replaces the
Buffer send step with a first-party Instagram Graph API publish — immediate
posting (autopilot slot spacing supplies the cadence: `86400/daily_target`
seconds between publishes), a custom cover from the render poster, a
`copyright_check_status` canary (matches veto the send and stamp
`copyright_status="matches_found"` on the post), and first-party insights
metrics for graph-published posts. Default stays `buffer`.

One-time setup (operator):
1. Create a Meta app; connect the Instagram professional account (Creator
   type — Business accounts get a restricted music library) via Facebook
   Login with `instagram_basic`, `instagram_content_publish`,
   `instagram_manage_insights`.
2. Exchange for a long-lived (60-day) token and calendar the refresh:
   `GET /oauth/access_token?grant_type=fb_exchange_token&client_id=...&client_secret=...&fb_exchange_token=<short-lived>`.
3. Set on Railway: `ECLYPTE_IG_USER_ID`, `ECLYPTE_IG_ACCESS_TOKEN`
   (optionally `ECLYPTE_GRAPH_API_BASE`, default `https://graph.facebook.com/v23.0`),
   then `ECLYPTE_PUBLISH_PROVIDER=graph`. `/healthz` reports
   `graph_publishing_configured`; `/v1/publishing/config` reports
   `publish_provider`.
4. Run the Task 0 probes from
   `docs/superpowers/plans/2026-08-04-graph-publishing.md` (Audio API shape,
   container `copyright_check_status` timing, `cover_url` acceptance) and the
   live veto drill: approve one post, watch `copyright_status`, verify the
   reel lands with the right cover/caption.

Autopilot (review-gated content loop): set `ECLYPTE_AUTOPILOT=1` on the API to
run the background tick loop (`ECLYPTE_AUTOPILOT_INTERVAL_SEC`, default 300).
Current per-edit defaults: `reels_9_16` format (native 1080x1920 fill-frame —
letterbox is officially demoted by Instagram; `reels_cinematic` remains for manual
composes), `edit_focus="moment"` single-scene plans, energy-ranked ~20–30s trim
window (≈25s target, 1.5s chorus lead-in), agent planning, daily target 2 (per-user, adjustable 1–10; keep it matched to the Buffer
channel's posting slots/day). A song without a music
analysis is analyzed first (`analyzing` state) so the window is always
energy-ranked, never the full song.
Without it, advance the queue manually:

```bash
curl -X POST -H "X-User-Id: local_dev" \
  http://127.0.0.1:8000/v1/autopilot/tick
```

Manage state via `GET/PATCH /v1/autopilot` and `POST /v1/autopilot/queue`;
auto-created packages appear as `ready` on the dashboard Home feed (`/dashboard`)
for approval (`/dashboard/publish` now redirects there).

Two default-off autonomy flags extend the loop via `PATCH /v1/autopilot`:
`auto_pair` lets the tick pick its own film×song pairs (LRU rotation over the
saved library, skipping/recycling exhausted pairs — `api/autopilot.py::select_next_pair`)
instead of requiring a manually queued pair; `auto_publish` sends `ready`
auto-created packages straight to Buffer's queue on a tick (skipped while
autopilot is paused or halted, 30-minute retry backoff on a send failure,
paused once queued posts reach 2x `daily_target`, send failures never count
toward the 3-failure halt). With `auto_publish` on,
`POST /v1/publishing/posts/{post_id}/cancel` on a queued/scheduled post is the
human veto — it deletes the post from Buffer before marking it canceled.

Every tick also runs a metrics-refresh pass (performance feedback loop, Phase
1) over `published` posts — independent of `auto_pair`/`auto_publish`/the
halt, so review-gated mode gets metrics too. It pulls Buffer's per-post
metrics on a 12h cadence, caps itself at 20 posts/pass, stops polling a post
after 30 days, and never fails the tick or trips the halt on a fetch error.
Because the background loop only ticks users with `enabled=true`, pausing
autopilot pauses this pass along with everything else — use the dashboard's
manual "Re-check status" (`refresh-status`) to pull metrics while paused.

Deploy the new R2-aware Modal wrappers before using video-analysis/render API
jobs against live Modal. Run deploys from `api/prototyping/` so the shared
`modal_s3` and `progress_events` modules resolve. Alternatively, deploy from
GitHub with no local setup: the manually-dispatched "Deploy Modal app"
workflow (`.github/workflows/modal-deploy.yml`, Actions → Run workflow → pick
render / video / clip-index / analysis / lyrics) deploys from a checkout of
the pushed branch; it needs `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` as repo
secrets (preferred) or Actions variables:

```powershell
cd api/prototyping
$env:PYTHONIOENCODING="utf-8"
modal deploy video/storage_modal.py
modal deploy edit/render_storage_modal.py
```

```bash
cd api/prototyping
PYTHONUTF8=1 modal deploy video/storage_modal.py
PYTHONUTF8=1 modal deploy edit/render_storage_modal.py
```

Modal snapshots local source at deploy time — pushing to Railway does not
update deployed apps. Redeploy `eclypte-render-r2` whenever `edit/render/**`,
`edit/skills/**`, `edit/synthesis/timeline_schema.py`, or
`edit/synthesis/validators.py` change (encode settings, effects/transitions,
overlay skills, schema values), or live renders keep the old behavior — an
older render image silently drops overlays whose skills it lacks, and an
older image REJECTS timelines carrying `lyrics.kinetic` (unknown skill_id →
visible render failure), so redeploy BEFORE shipping control-plane changes
that emit kinetic lyrics. The render image also downloads the kinetic-lyrics
font catalog (from `edit/skills/lyrics_fonts.py`, SHA-pinned google/fonts
URLs) into `/fonts/kinetic` and asserts its ffmpeg links libass at build time.

Local kinetic-lyrics rendering needs the same fonts once (gitignored
`api/prototyping/edit/content/fonts/`):

```powershell
python -m api.prototyping.edit.skills.fetch_fonts
```

Redeploy
`eclypte-video-r2` (`modal deploy video/storage_modal.py`, `PYTHONUTF8=1` on
Windows per above) whenever `video/analysis_cuda.py`, `video/credits.py`, or
`video/poster.py` change (its image bundles `tesseract-ocr` + `pytesseract`
for end-credit OCR, plus the pure poster-frame picker); re-analyze a film
afterward to populate the new `credits.content_end_sec` and/or its poster
thumbnail — re-analysis is also how existing films pick up a thumbnail for
the dashboard Library after deploying a `poster.py` change for the first
time. On Windows the UTF-8 env var matters: without it the Modal CLI can die
printing Unicode (`'charmap' codec can't encode character`).

Music analysis API jobs reuse the existing `eclypte-analysis::analyze_remote`
Modal function from `api/prototyping/music/analysis_modal.py`.

---

## Word-level lyrics timing (Modal GPU)

Deploy the lyrics aligner (`eclypte-lyrics::align_lyrics_remote`) used by song
imports/analyses and the edit pipeline's backfill; it has its own slim image
(`api/requirements-lyrics-modal.txt`) so the fragile allin1 image stays
untouched:

```powershell
cd api/prototyping
$env:PYTHONIOENCODING="utf-8"
modal deploy music/lyrics_align_modal.py
```

```bash
cd api/prototyping
PYTHONUTF8=1 modal deploy music/lyrics_align_modal.py
```

Redeploy after changing `music/lyrics_align.py` (the bundled pure module). The
first call downloads Whisper `large-v3` (~3 GB) + demucs weights (~300 MB) into
the persistent `lyrics-align-cache` volume, so expect a slow warm-up once.
`ECLYPTE_LYRICS_TIMING_DISABLED=1` on Railway skips alignment entirely;
`ECLYPTE_LYRICS_WHISPER_MODEL=medium` trades accuracy for speed on long songs.
Pure-module tests: `python -m pytest api/prototyping/music -v`.

---

## Music / video analysis (Modal GPU)

Production analysis calls `eclypte-analysis::analyze_remote` and
`eclypte-video-r2::analyze_r2` directly from the cloud API; the prototype
`eclypte-video` app's `analyze_remote_bytes` serves reference ingest. (The old
`modal run` local entrypoints were removed — exercise the analyzers through
the API or the reference-ingest CLI below.)

---

## CLIP index (Phase-3 prerequisite)

Deploy the R2-backed API index/query app (`eclypte-clip-index-r2`) used by `/v1/timelines` agent mode:

```powershell
cd api/prototyping
$env:PYTHONIOENCODING="utf-8"
modal deploy edit/index/storage_modal.py
```

(The `PYTHONIOENCODING` prefix only matters when Modal's pip output hits Unicode characters; harmless otherwise.)

The cloud API builds missing `clip_index` artifacts on demand, reuses existing ones derived from the selected source video version, and stores them in R2.

---

## Reference AMVs (local ingest CLI)

```powershell
# Ingest one viral reference (downloads, runs music + video analysis on Modal)
python -m api.prototyping.edit.reference ingest `
    --url "https://www.youtube.com/watch?v=..." `
    --likes 50000 `
    --views 1000000

# Inspect store
python -m api.prototyping.edit.reference list
python -m api.prototyping.edit.reference show <ref_id>
```

Production reference guidance flows through `POST /v1/synthesis/references` +
`POST /v1/synthesis/consolidations` and the plan-time style-profile loop; the
old offline LLM consolidate subcommand was removed.

---

## Tests

```powershell
python -m pytest api -v
python -m pytest api/test_api_v1.py -v
python -m pytest api/storage -v
python -m pytest api/prototyping/edit/synthesis/ -v
python -m pytest api/prototyping/edit/index/ -v
python -m pytest api/prototyping/edit/skills/ -v
python -m pytest api/prototyping/edit/render/ -v
python -m pytest api/prototyping/video/test_credits.py -v
python -m pytest api/prototyping/video/test_poster.py -v
```

`pytest.ini` disables pytest's cache provider and sets tmp-path retention to
zero, so normal future test runs should leave far fewer `.pytest*` artifacts in
the repo.

---

## Storage substrate tests

Set these env vars before using the shared R2 storage layer:

```powershell
$env:ECLYPTE_R2_ACCOUNT_ID="..."
$env:ECLYPTE_R2_BUCKET="eclypte"
$env:ECLYPTE_R2_ACCESS_KEY_ID="..."
$env:ECLYPTE_R2_SECRET_ACCESS_KEY="..."
$env:ECLYPTE_R2_REGION_NAME="auto"
```

Then run:

```powershell
python -m pytest api/storage -v
```

The storage test suite uses an in-memory fake by default, so it should pass
without live R2 access. Real R2 integration checks can be added later behind
explicit opt-in env vars.

---

## Useful Modal housekeeping

```powershell
modal app list                                # see deployed + running apps
modal volume ls allin1-cache                  # list files on a volume
```
