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

## Music analysis (Modal GPU)

Download a YouTube song → WAV → allin1 analysis JSON:

```powershell
cd api/prototyping/music
python main.py                # end-to-end: ytdownload + Modal analyze + lyrics
# or, if the WAV already exists:
modal run analysis_modal.py::main --wav content/output.wav
```

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

---

## Render a timeline manually (Phase-1 or Phase-3)

From `api/prototyping/` (required — `add_local_python_source("edit")` resolves relative to cwd):

```powershell
cd api/prototyping
modal run edit/render_modal.py `
    --timeline edit/content/timeline.json `
    --out edit/content/output.mp4
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
python -m pytest api/prototyping/edit/synthesis/ -v
python -m pytest api/prototyping/edit/index/ -v
```

---

## Useful Modal housekeeping

```powershell
modal app list                                # see deployed + running apps
modal volume ls eclypte-edit                  # list files on a volume
modal volume get eclypte-edit output_agent.mp4 ./    # download from volume
```
