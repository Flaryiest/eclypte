# Eclypte — Command Runbook

Every command below is shown twice: once in **PowerShell** (what the project uses on Windows) and once in **bash / zsh**. Paths use forward slashes throughout — both shells accept them.

Unless noted, run from the **repo root** (`c:\Users\ericm\Documents\GitHub\eclypte`). A few Modal commands must run from `api/prototyping/` — those are called out.

---

## One-time setup

Activate the venv every session:

```powershell
# PowerShell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
. api/.venv/Scripts/Activate.ps1
```

```bash
# bash / git-bash
source api/.venv/Scripts/activate
```

First-time-only:

```powershell
python -m venv api/.venv
. api/.venv/Scripts/Activate.ps1
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

YouTube song import may require authenticated YouTube cookies when Railway's
IP is challenged. Export YouTube cookies in Netscape `cookies.txt` format,
base64-encode the file contents, and set this on the Railway API service:

```powershell
$env:ECLYPTE_YOUTUBE_COOKIES_B64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content .\youtube-cookies.txt -Raw)))
```

```bash
export ECLYPTE_YOUTUBE_COOKIES_B64="$(base64 < youtube-cookies.txt | tr -d '\n')"
```

For local-only development, raw `ECLYPTE_YOUTUBE_COOKIES` text is also accepted.
Do not commit exported cookies; treat them like passwords and refresh them if
YouTube rejects the configured value.

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

Backfill existing R2 run history into Postgres after `DATABASE_URL` is set:

```powershell
python -m api.storage.backfill_runs
# or one user only:
python -m api.storage.backfill_runs --user-id local_dev
```

```bash
python -m api.storage.backfill_runs
# or one user only:
python -m api.storage.backfill_runs --user-id local_dev
```

Routes:

- `POST /v1/uploads` reserves a file/version/blob key and returns a presigned R2 PUT URL.
- `POST /v1/uploads/{upload_id}/complete` validates the uploaded object and records metadata.
- `GET /v1/files/{file_id}` and `GET /v1/files/{file_id}/versions/{version_id}` read manifests.
- `GET /v1/files/{file_id}/versions/{version_id}/download-url` returns a presigned R2 GET URL.
- `POST /v1/music/analyses`, `POST /v1/video/analyses`, `POST /v1/timelines`, and `POST /v1/renders` create run manifests and schedule background work. Renders publish a `render_output` MP4 and a `render_poster` JPEG thumbnail.
- `GET /v1/publishing/config` reports non-secret Buffer/OpenAI/public-media setup.
- `GET /v1/publishing/posts`, `POST /v1/publishing/posts`, `PATCH /v1/publishing/posts/{post_id}`, `POST /v1/publishing/posts/{post_id}/regenerate-caption`, `POST /v1/publishing/posts/{post_id}/send-buffer`, `POST /v1/publishing/posts/{post_id}/refresh-status` (back-fills the live permalink from Buffer), and `POST /v1/publishing/posts/{post_id}/cancel` manage review-gated Buffer publishing packages (sent as Instagram Reels).
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

Autopilot (review-gated content loop): set `ECLYPTE_AUTOPILOT=1` on the API to
run the background tick loop (`ECLYPTE_AUTOPILOT_INTERVAL_SEC`, default 300).
Current per-edit defaults: `reels_cinematic` format (native 1080x1920 with the
widescreen picture letterboxed in), energy-ranked ~20–30s trim window (≈25s target), agent
planning, daily target 3 (per-user, adjustable 1–10). A song without a music
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

Deploy the new R2-aware Modal wrappers before using video-analysis/render API
jobs against live Modal. Run deploys from `api/prototyping/` so the shared
`modal_s3` and `progress_events` modules resolve:

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
older render image silently drops overlays whose skills it lacks. Redeploy
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

## Music analysis (Modal GPU)

Analyze an existing WAV with allin1 on Modal:

```powershell
cd api/prototyping/music
modal run analysis_modal.py::main --wav content/output.wav
```

Output: `api/prototyping/music/content/output.json`. Production music analysis
calls `eclypte-analysis::analyze_remote` directly from the cloud API.

---

## Video analysis (Modal GPU)

Upload the source once:

```powershell
modal volume put eclypte-video-input "api/prototyping/video/content/Project Hail Mary.mp4"
```

Run the analysis:

```powershell
cd api/prototyping/video
modal run analysis_modal.py --filename "Project Hail Mary.mp4"
```

First run builds an OpenCV-CUDA image (~20–40 min). Subsequent runs skip to GPU inference.

Output: `api/prototyping/video/content/<name>.json`.

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

## Phase-2: ingest + consolidate reference AMVs

```powershell
# Ingest one viral reference (downloads, runs music + video analysis on Modal)
python -m api.prototyping.edit.reference ingest `
    --url "https://www.youtube.com/watch?v=..." `
    --likes 50000 `
    --views 1000000

# Inspect store
python -m api.prototyping.edit.reference list
python -m api.prototyping.edit.reference show <ref_id>

# Consolidate via LLM → rewrites knowledge/references.md
python -m api.prototyping.edit.reference consolidate
```

---

## Tests

```powershell
python -m pytest api -v
python -m pytest api/test_api_v1.py -v
python -m pytest api/storage -v
python -m pytest api/prototyping/edit/synthesis/ -v
python -m pytest api/prototyping/edit/index/ -v
python -m pytest api/prototyping/edit/skills/ -v
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
modal volume ls eclypte-video-input           # list files on a volume
```
