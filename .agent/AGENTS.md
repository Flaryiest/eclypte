# Superpowers for Antigravity

You have superpowers.

This profile adapts Superpowers workflows for Antigravity with strict single-flow execution.

## Core Rules

1. Prefer local skills in `.agent/skills/<skill-name>/SKILL.md`.
2. Execute one core task at a time with `task_boundary`.
3. Use `browser_subagent` only for browser automation tasks.
4. Track checklist progress in `<project-root>/docs/plans/task.md` (table-only live tracker).
5. Keep changes scoped to the requested task and verify before completion claims.

## Tool Translation Contract

When source skills reference legacy tool names, use these Antigravity equivalents:

- Legacy assistant/platform names -> `Antigravity`
- `Task` tool -> `browser_subagent` for browser tasks, otherwise sequential `task_boundary`
- `Skill` tool -> `view_file ~/.gemini/skills/<skill-name>/SKILL.md` (or project-local `.agent/skills/<skill-name>/SKILL.md`)
- `TodoWrite` -> update `<project-root>/docs/plans/task.md` task list
- File operations -> `view_file`, `write_to_file`, `replace_file_content`, `multi_replace_file_content`
- Directory listing -> `list_dir`
- Code structure -> `view_file_outline`, `view_code_item`
- Search -> `grep_search`, `find_by_name`
- Shell -> `run_command`
- Web fetch -> `read_url_content`
- Web search -> `search_web`
- Image generation -> `generate_image`
- User communication during tasks -> `notify_user`
- MCP tools -> `mcp_*` tool family

## Skill Loading

- First preference: project skills at `.agent/skills`.
- Second preference: user skills at `~/.gemini/skills`.
- If both exist, project-local skills win for this profile.
- Optional parity assets may exist at `.agent/workflows/*` and `.agent/agents/*` as entrypoint shims/reference profiles.
- These assets do not change the strict single-flow execution requirements in this file.

## Single-Flow Execution Model

- Do not dispatch multiple coding agents in parallel.
- Decompose large work into ordered, explicit steps.
- Keep exactly one active task at a time in `<project-root>/docs/plans/task.md`.
- If browser work is required, isolate it in a dedicated browser step.

## Verification Discipline

Before saying a task is done:

1. Run the relevant verification command(s).
2. Confirm exit status and key output.
3. Update `<project-root>/docs/plans/task.md`.
4. Report evidence, then claim completion.

## Project Context & Conventions

- **Heavy ML Isolation**: Do not install heavy ML packages (`torch`, `transformers`, `allin1`) locally. They are executed strictly on Modal T4 containers to keep the local dev environment lightweight.
- **Modal Execution**: Music analysis and edit rendering use `modal.Image.debian_slim(python_version="3.12")`. Video GPU analysis is the exception: it uses `modal.Image.from_registry("nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04", add_python="3.11")` so OpenCV can be built with CUDA support. When building Modal images, use `.add_local_python_source()` to inject specific local modules into the container, allowing relative imports to work seamlessly inside Modal functions.
- **Local Proxying**: For Modal functions, maintain a local proxy file (e.g. `query.py`) that uses `modal.Function.from_name("app-name", "function_name")` to isolate the remote call from the rest of the local logic.
- **Worktrees**: We prefer global worktrees located at `~/.config/superpowers/worktrees/eclypte/` for isolated development. (Note: Workspace validation must be disabled in settings to access this).
- **Canonical Runbook**: Use `api/COMMANDS.md` for exact setup, Modal, planning, rendering, storage, and test commands. The root `README.md` is currently just a stub. For R2-backed flows, local secrets should live in `api/.env` or environment variables; never commit secrets, exported cookies, or tokens.
- **Current Backend State**: `api/main.py` now exposes a real FastAPI app via `api.app.create_app()`. The v1 REST control plane is live under `/v1/*` for direct R2 uploads, file metadata, music analysis, video analysis, timeline planning, render jobs, run lookup, and run events. The prototype media code still lives in `api/prototyping/`, but the editor path now has API routes and background workflow adapters.
- **Railway Hosting State**: The API is hosted on Railway in project `eclypte-api`, service `api`, environment `production`. Public domain: `https://api-production-8fb8.up.railway.app`. The service has been linked to the GitHub repo/branch by the user for future deploy attempts.
- **Railway Verification**: Hosted `/healthz` returned `{"ok": true}`. A tiny hosted upload smoke test verified API -> presigned R2 PUT -> upload completion -> download URL. CORS preflight from `https://eclypte.vercel.app` passed. A hosted Railway -> Modal music-analysis run completed successfully (`run_036a84b2e8d3`), proving Railway has working R2 and Modal env vars.
- **Railway Config**: Root `railpack.json` pins Python 3.13 and starts with `python -m api.main`. Root `requirements.txt` is intentionally self-contained for Railway/Railpack; do not replace it with `-r api/requirements.txt` because Railpack copies only the root requirements file during the Python install layer. The broader local/dev dependency set still lives in `api/requirements.txt`.
- **Current Repo Map**:
  - `api/app.py`: versioned REST API. Temporary auth resolves `user_id` from `X-User-Id`, falling back to `ECLYPTE_DEFAULT_USER_ID`. CORS defaults to `https://eclypte.vercel.app`, `http://localhost:3000`, and `http://127.0.0.1:3000`, with `ECLYPTE_CORS_ORIGINS` as the override.
  - `api/workflows.py`: Railway-style background workflow runner. It creates/upserts run manifests, reuses or schedules analyses, calls Modal wrappers for heavy media work, supports deterministic and OpenAI/CLIP-backed timeline planning, and records progress.
  - `api/storage/`: shared Cloudflare R2-oriented storage substrate with `R2Config`, object-store factory helpers, canonical key builders, typed refs/models, an S3-compatible client, a repository layer, staging helpers, presigned URL helpers, upload reservations, and run-status helpers. The REST API uses it as the v1 metadata/artifact store, while some older prototype CLIs still read and write local files or Modal volumes directly.
  - `api/prototyping/music/`: YouTube audio download, lyric lookup, local analysis helpers, and the Modal-backed music analysis flow.
  - `api/prototyping/video/`: scene detection, motion/impact extraction, and the Modal-backed video analysis flow.
  - `api/prototyping/video/storage_modal.py`: R2-aware Modal video-analysis wrapper for API jobs. It reads the source blob from R2 and returns analysis JSON without Railway downloading the video.
  - `api/prototyping/edit/`: the main AMV pipeline. Phase 1 is deterministic planning, Phase 2 ingests and consolidates reference AMVs into `knowledge/references.md`, and Phase 3 uses OpenAI Responses plus Modal CLIP retrieval to synthesize timelines before rendering.
  - `api/prototyping/edit/render/`: MoviePy renderer for turning timeline JSON into MP4 output.
  - `api/prototyping/edit/render_storage_modal.py`: R2-aware Modal render wrapper for API jobs. It pulls timeline/media refs from R2 and writes the rendered MP4 back to R2.
  - `api/prototyping/edit/index/`: frame extraction, CLIP embedding, Modal index build/query, and tests for retrieval helpers.
  - `api/prototyping/edit/synthesis/`: timeline schema, validator, deterministic planner, agent loop, adapter, and tests.
  - `web/`: Next.js 16 + React 19 frontend with Clerk auth, a marketing landing page, lightweight pricing route, and a real dashboard console for uploads, saved assets, edit pipelines, synthesis prompt management, render browsing, and settings.
- **Testing Reality**: Automated coverage is concentrated in `api/storage/`, `api/test_api_v1.py`, `api/prototyping/music/`, `api/prototyping/edit/index/`, and `api/prototyping/edit/synthesis/`. Use `python -m pytest api -v` for the broad backend check. `pytest.ini` disables pytest's cache provider and sets tmp-path retention to zero to reduce local test artifacts. There is still no comparable frontend test suite in the repo; use `npm run lint` and `npm run build` from `web/` for frontend verification.
- **R2 Direction**: R2 is now the v1 metadata and artifact store for the cloud API. `FileManifest`, `FileVersionMeta`, `UploadReservation`, `RunManifest`, and `RunEvent` are the canonical persistence model. Direct browser-to-R2 upload reservation/completion is implemented; music/video analysis, timeline planning, and rendering all publish output artifacts through R2-backed run manifests.
- **Cloud REST API V1 Routes**:
  - Health: `GET /healthz`
  - Uploads/files/assets: `POST /v1/uploads`, `POST /v1/uploads/{upload_id}/complete`, `DELETE /v1/uploads/{upload_id}`, `GET /v1/files/{file_id}`, `GET /v1/files/{file_id}/versions/{version_id}`, `GET /v1/files/{file_id}/versions/{version_id}/download-url`, `GET /v1/assets`, `DELETE /v1/assets/{file_id}`, `POST /v1/assets/{file_id}/restore`
  - Workflows: `POST /v1/music/analyses`, `POST /v1/music/youtube-imports`, `POST /v1/video/analyses`, `POST /v1/timelines`, `POST /v1/renders`, `POST /v1/edits`
  - Edit jobs: `GET /v1/edits`, `GET /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/cancel`, `DELETE /v1/edits/{run_id}`, `POST /v1/edits/{run_id}/redo`
  - Runs: `GET /v1/runs`, `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, `GET /v1/runs/stream`, `GET /v1/runs/{run_id}/stream`
  - Synthesis: `POST /v1/synthesis/references`, `GET /v1/synthesis/references`, `POST /v1/synthesis/consolidations`, `GET /v1/synthesis/prompt`, `POST /v1/synthesis/prompt/versions`, `POST /v1/synthesis/prompt/versions/{version_id}/activate`
- **Cloud REST API Workflow Shape**: workflow endpoints create a `RunManifest` with `status="running"` and return `202` immediately. FastAPI background tasks call `DefaultWorkflowRunner`; if a worker dies mid-run, the run remains inspectable in R2 and can be retried manually or by a future durable queue.
- **Music Workflow Status**:
  - Production music analysis runs through `api/workflows.py::run_music_analysis`, which calls `eclypte-analysis::analyze_remote` and publishes a `music_analysis` artifact through `api/storage/`.
  - The shared storage entrypoint is `api.storage.factory.get_object_store()`. It loads `api/.env` if present and returns `None` in optional mode when required R2 env vars are missing.
  - `api/prototyping/music/lyrics.py` redirects `syncedlyrics` cache writes to `api/prototyping/music/content/.cache` on Windows so local `AppData` permission issues do not break or warn during normal runs.
  - On Windows, `pytubefix` progress output may still require `PYTHONIOENCODING=utf-8` for clean terminal execution.
