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

`agent.py` reads this via `load_dotenv()` when `--agent` mode runs.

---

## Cloud REST API V1

The Railway-ready FastAPI app lives in `api/app.py` and is exposed by
`api/main.py`. It uses R2 manifests as the v1 metadata store and returns
immediately from workflow endpoints while background tasks call Modal or the
local deterministic planner.

Required storage env for real `/v1/*` calls:

```powershell
$env:ECLYPTE_R2_ACCOUNT_ID="..."
$env:ECLYPTE_R2_BUCKET="eclypte"
$env:ECLYPTE_R2_ACCESS_KEY_ID="..."
$env:ECLYPTE_R2_SECRET_ACCESS_KEY="..."
$env:ECLYPTE_R2_REGION_NAME="auto"
$env:ECLYPTE_DEFAULT_USER_ID="local_dev"
```

```bash
export ECLYPTE_R2_ACCOUNT_ID="..."
export ECLYPTE_R2_BUCKET="eclypte"
export ECLYPTE_R2_ACCESS_KEY_ID="..."
export ECLYPTE_R2_SECRET_ACCESS_KEY="..."
export ECLYPTE_R2_REGION_NAME="auto"
export ECLYPTE_DEFAULT_USER_ID="local_dev"
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

Routes:

- `POST /v1/uploads` reserves a file/version/blob key and returns a presigned R2 PUT URL.
- `POST /v1/uploads/{upload_id}/complete` validates the uploaded object and records metadata.
- `GET /v1/files/{file_id}` and `GET /v1/files/{file_id}/versions/{version_id}` read manifests.
- `GET /v1/files/{file_id}/versions/{version_id}/download-url` returns a presigned R2 GET URL.
- `POST /v1/music/analyses`, `POST /v1/video/analyses`, `POST /v1/timelines`, and `POST /v1/renders` create run manifests and schedule background work.
- `GET /v1/runs/{run_id}` and `GET /v1/runs/{run_id}/events` inspect workflow status.

Deploy the new R2-aware Modal wrappers before using video-analysis/render API
jobs against live Modal:

```powershell
cd api/prototyping/video
modal deploy storage_modal.py

cd ../
modal deploy edit/render_storage_modal.py
```

```bash
cd api/prototyping/video
modal deploy storage_modal.py

cd ../
modal deploy edit/render_storage_modal.py
```

Music analysis API jobs reuse the existing `eclypte-analysis::analyze_remote`
Modal function from `api/prototyping/music/analysis_modal.py`.

---

## Music analysis (Modal GPU)

Download a YouTube song → WAV → allin1 analysis JSON:

```powershell
cd api/prototyping/music
python main.py                # end-to-end: ytdownload + Modal analyze + lyrics
# or, if the WAV already exists:
modal run analysis_modal.py::main --wav content/output.wav
```

If you also want the music workflow to publish `output.wav`, `output.json`, and
`lyrics.txt` to R2 after local success, create `api/.env` from
`api/.env.example` and fill in:

```powershell
$env:ECLYPTE_R2_ACCOUNT_ID="..."
$env:ECLYPTE_R2_BUCKET="eclypte"
$env:ECLYPTE_R2_ACCESS_KEY_ID="..."
$env:ECLYPTE_R2_SECRET_ACCESS_KEY="..."
$env:ECLYPTE_R2_REGION_NAME="auto"
$env:ECLYPTE_DEFAULT_USER_ID="local_dev"
```

If those vars are missing, `python main.py` still succeeds locally and prints
`R2 publish skipped: storage not configured.`

Output: `api/prototyping/music/content/output.wav` + `output.json`.

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

Upload the source video to the edit volume (one-time per video):

```powershell
modal volume create eclypte-edit                                   # once, ever
modal volume put eclypte-edit "api/prototyping/video/content/Project Hail Mary.mp4"
modal volume put eclypte-edit api/prototyping/music/content/output.wav
```

Build the CLIP index (from `api/prototyping/`):

```powershell
cd api/prototyping
modal run edit/index/index_modal.py --video-filename "Project Hail Mary.mp4"
```

Deploy the query endpoint (one-time):

```powershell
cd api/prototyping
$env:PYTHONIOENCODING="utf-8"
modal deploy edit/index/query_modal.py
```

(The `PYTHONIOENCODING` prefix only matters when Modal's pip output hits Unicode characters; harmless otherwise.)

Deploy the R2-backed API index/query app used by `/v1/timelines` agent mode:

```powershell
cd api/prototyping
$env:PYTHONIOENCODING="utf-8"
modal deploy edit/index/storage_modal.py
```

The cloud API builds missing `clip_index` artifacts on demand, reuses existing ones derived from the selected source video version, and stores them in R2. The older `eclypte-edit` volume commands above are still for local/prototype CLI runs.

---

## Plan a timeline (Phase-1: deterministic)

From the repo root:

```powershell
python -m api.prototyping.edit.main `
    --song "api/prototyping/music/content/output.wav" `
    --source "api/prototyping/video/content/Project Hail Mary.mp4" `
    --out "api/prototyping/edit/content/timeline.json"
```

```bash
python -m api.prototyping.edit.main \
    --song "api/prototyping/music/content/output.wav" \
    --source "api/prototyping/video/content/Project Hail Mary.mp4" \
    --out "api/prototyping/edit/content/timeline.json"
```

---

## Plan a timeline (Phase-3: GPT-4o agent)

Requires: CLIP index built, `eclypte-query` deployed, `OPENAI_API_KEY` set in `.env`.

```powershell
python -m api.prototyping.edit.main `
    --song "api/prototyping/music/content/output.wav" `
    --source "api/prototyping/video/content/Project Hail Mary.mp4" `
    --out "api/prototyping/edit/content/timeline_agent.json" `
    --agent `
    --instructions "Fast-paced action AMV, open strong, tell the full story chronologically."
```

Single-line version (paste-friendly):

```powershell
python -m api.prototyping.edit.main --song "api/prototyping/music/content/output.wav" --source "api/prototyping/video/content/Project Hail Mary.mp4" --out "api/prototyping/edit/content/timeline_agent.json" --agent --instructions "Fast-paced action AMV, open strong, tell the full story chronologically."
```

---

## Plan + render in one command

Add `--render` to any of the plan commands above. It subprocesses `modal run edit/render_modal.py` after writing the timeline:

```powershell
python -m api.prototyping.edit.main `
    --song "api/prototyping/music/content/output.wav" `
    --source "api/prototyping/video/content/Project Hail Mary.mp4" `
    --out "api/prototyping/edit/content/timeline_agent.json" `
    --agent `
    --instructions "Fast-paced action AMV, open strong, tell the full story chronologically." `
    --render `
    --render-out "api/prototyping/edit/content/output_agent.mp4"
```

`--render-out` defaults to `api/prototyping/edit/content/output.mp4` if omitted.

For faster render turnaround with no encode-quality change, add:

```powershell
--render-store-only
```

`--render-store-only` keeps the MP4 on the `eclypte-edit` Modal volume instead
of returning the full file over the function response.

`--render-preset` is still available if you want a different x264 speed/compression
tradeoff, but the quality-safe fast path is just `--render-store-only`.

For the higher-capacity benchmark profile, add:

```powershell
--render-profile boosted
```

To test whether local container staging beats repeated volume reads on long renders,
add:

```powershell
--render-stage-inputs-local
```

---

## Render a timeline manually (Phase-1 or Phase-3)

From `api/prototyping/` (required — `add_local_python_source("edit")` resolves relative to cwd):

```powershell
cd api/prototyping
modal run edit/render_modal.py `
    --timeline edit/content/timeline.json `
    --out edit/content/output.mp4
```

Faster remote-only variant:

```powershell
cd api/prototyping
modal run edit/render_modal.py `
    --timeline edit/content/timeline.json `
    --out edit/content/output.mp4 `
    --store-only
```

Higher-capacity benchmark variant:

```powershell
cd api/prototyping
modal run edit/render_modal.py `
    --timeline edit/content/timeline.json `
    --out edit/content/output.mp4 `
    --render-profile boosted `
    --store-only
```

Higher-capacity + local-staging benchmark:

```powershell
cd api/prototyping
modal run edit/render_modal.py `
    --timeline edit/content/timeline.json `
    --out edit/content/output.mp4 `
    --render-profile boosted `
    --render-stage-inputs-local `
    --store-only
```

Query warm-container tuning note:
if you want the `scaledown_window=600` change on the deployed query app, redeploy it:

```powershell
cd api/prototyping
modal deploy edit/index/query_modal.py
```

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

Apply the consolidated pattern weights to a Phase-1 plan:

```powershell
python -m api.prototyping.edit.main `
    --song ... --source ... --out ... `
    --use-annotations
```

---

## Tests

```powershell
python -m pytest api -v
python -m pytest api/test_api_v1.py -v
python -m pytest api/storage -v
python -m pytest api/prototyping/edit/synthesis/ -v
python -m pytest api/prototyping/edit/index/ -v
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
modal volume ls eclypte-edit                  # list files on a volume
modal volume get eclypte-edit output_agent.mp4 ./    # download from volume
```
