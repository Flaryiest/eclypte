# Ivory & Ink Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dark "Edit Bay" dashboard with a warm, light, consumer-grade 3-page app (Home pipeline feed / Library / Settings) plus one backend addition: real source-video thumbnails.

**Architecture:** The backend gains a `source_poster` artifact (representative frame picked during Modal video analysis, published by `run_video_analysis`, surfaced as an optional `poster` ref on `AssetSummary`). The frontend swaps the `[data-surface="studio"]` token block and `studio.module.css` to the Ivory & Ink system, adds five feedback primitives, then rebuilds `/dashboard` as the pipeline Home (absorbing the autopilot + publish pages) and `/dashboard/assets` as the Library (absorbing renders). Data layer (`src/stores/`, `useRunStream`, `eclypteApi`) is unchanged except two additive edits (poster type, XHR upload progress).

**Tech Stack:** FastAPI + Pydantic v2 + pytest (backend); Next.js 16 App Router, React 19, TypeScript, CSS Modules, zustand SWR cache (frontend); Modal `eclypte-video-r2` (GPU analysis worker).

**Spec:** `docs/superpowers/specs/2026-07-01-dashboard-redesign-design.md`. Approved visual mockups: `.superpowers/brainstorm/1592-1782947788/content/{home-design,library-design,system-design}.html` — open these in a browser when building UI tasks.

## Global Constraints

- Time fields stay in seconds with `_sec` suffix; existing `RunManifest.outputs` keys are frontend contracts — additive changes only.
- Marketing site untouched: never edit `:root`, `[data-theme]`, the CSS reset, or `body` rules in `web/src/app/globals.css`; only the `[data-surface="studio"]` block changes.
- Dashboard type: PP Neue Montreal only (`--font-ui`). **No `text-transform: uppercase`, no positive `letter-spacing` anywhere in dashboard CSS.** Sentence case in all copy. Meta text floor: `0.78rem` (12.5px).
- Palette (exact): app `#F7F5F1`, card `#FFFFFF`, sunk `#F1EDE4`, border `#E9E4DB`, border-strong `#D8D1C4`, overlay `rgba(38,35,30,0.28)`, ink `#26231E`, ink-soft `#3D3A34`, muted `#8A8375`, faint `#B3AC9C`, accent coral `#E86A4F` (progress/attention only), success sage `#5E8A62`, danger clay `#C25243`. Radius: cards/sheets 12px, buttons 10px, pills 99px.
- UI copy never names infrastructure (Buffer, R2, Redis, Modal, presigned URLs). Use `statusLabel`/`humanizeStageDetail`/`formatClock` from `dashboardCommon` instead of raw enums.
- Async feedback tiers (no exceptions): instant → optimistic + failure toast; short → button keeps label + inline `Spinner`; long → progress bar + stage sentence + real number.
- Backend tests run from repo root (`python -m pytest api ... -v`); frontend verification is `npm run lint` and `npm run build` from `web/` (no JS test runner exists in this repo — do not add one).
- Commit after every task with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Backend — `source_poster` artifact kind + `poster` ref on `AssetSummary`

**Files:**
- Modify: `api/storage/models.py:5-15` (ArtifactKind literal)
- Modify: `api/app.py:254-267` (AssetSummary model), `api/app.py:611-697` (`analysis_for_asset` / `summarize_asset`), `api/app.py:1000-1004` (default kind exclusion)
- Test: `api/test_api_v1.py` (append)

**Interfaces:**
- Consumes: existing `file_version_input(file_id, version_id) -> FileVersionInput | None` helper in `api/app.py`; `analysis_for_asset` already returns `(analysis, analysis_run)`.
- Produces: `AssetSummary.poster: FileVersionInput | None` — set for `kind == "source_video"` (from the completed `video_analysis` run's `source_poster_file_id`/`source_poster_version_id` outputs) and for `kind == "render_output"` (from `latest_run` outputs `render_poster_file_id`/`render_poster_version_id`). New literal member `"source_poster"`. Task 7 mirrors the field in `eclypteApi.ts`; Task 4 writes the run outputs.

- [ ] **Step 1: Write the failing tests** — append to `api/test_api_v1.py`:

```python
def test_assets_default_listing_excludes_source_posters():
    client, store, _ = build_client()
    from api.storage.repository import StorageRepository

    repo = StorageRepository(store)
    publish_artifact(repo, user_id="local_dev", file_id="file_v1", kind="source_video", filename="film.mp4")
    publish_artifact(repo, user_id="local_dev", file_id="file_p1", kind="source_poster", filename="film.jpg")

    default_listing = client.get("/v1/assets")
    poster_listing = client.get("/v1/assets", params={"kind": "source_poster"})

    assert default_listing.status_code == 200
    assert [a["file_id"] for a in default_listing.json()] == ["file_v1"]
    assert [a["file_id"] for a in poster_listing.json()] == ["file_p1"]


def test_source_video_asset_carries_poster_ref_from_analysis_run():
    client, store, _ = build_client()
    from api.storage.repository import StorageRepository

    repo = StorageRepository(store)
    video = publish_artifact(repo, user_id="local_dev", file_id="file_v2", kind="source_video", filename="film.mp4")
    analysis = publish_artifact(repo, user_id="local_dev", file_id="file_va2", kind="video_analysis", filename="film.json")
    poster = publish_artifact(repo, user_id="local_dev", file_id="file_sp2", kind="source_poster", filename="film.jpg")
    run = repo.create_run(
        user_id="local_dev",
        workflow_type="video_analysis",
        inputs={"source_video_file_id": video["file_id"], "source_video_version_id": video["version_id"]},
        steps=["analyze_video"],
    )
    repo.update_run_status(
        RunRef(user_id="local_dev", run_id=run.run_id),
        status="completed",
        outputs={
            "video_analysis_file_id": analysis["file_id"],
            "video_analysis_version_id": analysis["version_id"],
            "source_poster_file_id": poster["file_id"],
            "source_poster_version_id": poster["version_id"],
        },
    )

    listing = client.get("/v1/assets")

    asset = next(a for a in listing.json() if a["file_id"] == "file_v2")
    assert asset["poster"] == {"file_id": poster["file_id"], "version_id": poster["version_id"]}
```

(`RunRef` is already imported at the top of `test_api_v1.py`; if not, add `from api.storage.refs import RunRef`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest api/test_api_v1.py -k "source_poster or poster_ref" -v`
Expected: FAIL — first test rejects `kind="source_poster"` as an invalid `ArtifactKind` (422) and/or second test has no `poster` key.

- [ ] **Step 3: Add the literal member** — in `api/storage/models.py`, extend the `ArtifactKind` literal:

```python
ArtifactKind = Literal[
    "source_video",
    "song_audio",
    "lyrics",
    "music_analysis",
    "video_analysis",
    "clip_index",
    "timeline",
    "render_output",
    "render_poster",
    "source_poster",
]
```

- [ ] **Step 4: Exclude posters from default listing** — in `api/app.py` `list_assets` (line ~1003), change the tuple:

```python
            manifests = [
                manifest
                for manifest in manifests
                if manifest.kind not in ("render_output", "render_poster", "source_poster")
            ]
```

- [ ] **Step 5: Add `poster` to `AssetSummary` and resolve it** — in `api/app.py`, add the field after `analysis`:

```python
class AssetSummary(BaseModel):
    file_id: str
    kind: ArtifactKind
    display_name: str
    current_version_id: str | None
    created_at: str
    updated_at: str
    source_run_id: str | None
    tags: list[str]
    current_version: FileVersionMeta | None
    latest_run: RunManifest | None
    analysis: FileVersionInput | None
    poster: FileVersionInput | None
    archived_at: str | None
    archived_reason: str | None
```

In `summarize_asset`, after `latest_run` is resolved and before the `return`, add:

```python
        poster = None
        if manifest.kind == "source_video" and analysis_run is not None and analysis_run.status == "completed":
            poster = file_version_input(
                analysis_run.outputs.get("source_poster_file_id"),
                analysis_run.outputs.get("source_poster_version_id"),
            )
        elif manifest.kind == "render_output" and latest_run is not None:
            poster = file_version_input(
                latest_run.outputs.get("render_poster_file_id"),
                latest_run.outputs.get("render_poster_version_id"),
            )
```

and pass `poster=poster,` in the `AssetSummary(...)` constructor call.

- [ ] **Step 6: Run the new tests, then the API suite**

Run: `python -m pytest api/test_api_v1.py -k "source_poster or poster_ref" -v` → PASS
Run: `python -m pytest api/test_api_v1.py api/storage -v` → PASS (existing `AssetSummary` constructions all go through `summarize_asset`, so no other call sites break)

- [ ] **Step 7: Commit**

```bash
git add api/storage/models.py api/app.py api/test_api_v1.py
git commit -m "feat(api): add source_poster artifact kind + poster ref on asset summaries"
```

---

### Task 2: Backend — pure poster-frame picker module

**Files:**
- Create: `api/prototyping/video/poster.py`
- Test: `api/prototyping/video/test_poster.py`

**Interfaces:**
- Consumes: nothing (pure module — no cv2/numpy/Modal imports at module level, mirroring `credits.decide_content_end`'s pure-logic pattern).
- Produces: `PosterPicker(duration_sec: float)` with `consider(ts_sec: float, brightness: float, detail: float) -> bool` (True when this frame becomes the new best candidate — the caller then snapshots the frame) and `best_ts_sec: float | None`. Constants `POSTER_MIN_BRIGHTNESS`, `POSTER_MAX_BRIGHTNESS`, `POSTER_MIN_DETAIL`, `POSTER_WINDOW`, `POSTER_TARGET_FRAC`, `POSTER_SAMPLE_EVERY_SEC`. Task 3 wires this into the CUDA decode loop.

- [ ] **Step 1: Write the failing tests** — create `api/prototyping/video/test_poster.py`:

```python
from api.prototyping.video.poster import (
    POSTER_SAMPLE_EVERY_SEC,
    PosterPicker,
    score_poster_candidate,
)


def test_rejects_dark_flat_and_blown_out_frames():
    assert score_poster_candidate(0.2, brightness=10.0, detail=50.0) is None  # near-black
    assert score_poster_candidate(0.2, brightness=240.0, detail=50.0) is None  # blown out / credits-white
    assert score_poster_candidate(0.2, brightness=120.0, detail=5.0) is None  # flat / title card


def test_prefers_frames_near_the_target_fraction():
    early = score_poster_candidate(0.06, brightness=120.0, detail=40.0)
    on_target = score_poster_candidate(0.20, brightness=120.0, detail=40.0)
    late = score_poster_candidate(0.44, brightness=120.0, detail=40.0)
    assert on_target is not None and early is not None and late is not None
    assert on_target > early
    assert on_target > late


def test_ignores_frames_outside_the_window():
    assert score_poster_candidate(0.01, brightness=120.0, detail=40.0) is None
    assert score_poster_candidate(0.80, brightness=120.0, detail=40.0) is None


def test_picker_keeps_the_best_candidate_across_a_stream():
    picker = PosterPicker(duration_sec=100.0)
    assert picker.consider(10.0, brightness=120.0, detail=20.0) is True  # first acceptable
    assert picker.consider(15.0, brightness=15.0, detail=60.0) is False  # too dark
    assert picker.consider(20.0, brightness=130.0, detail=45.0) is True  # better: on target + detailed
    assert picker.consider(30.0, brightness=130.0, detail=30.0) is False  # worse than current best
    assert picker.best_ts_sec == 20.0


def test_picker_with_no_acceptable_frames_has_no_best():
    picker = PosterPicker(duration_sec=100.0)
    assert picker.consider(20.0, brightness=5.0, detail=2.0) is False
    assert picker.best_ts_sec is None


def test_sample_interval_is_positive():
    assert POSTER_SAMPLE_EVERY_SEC > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest api/prototyping/video/test_poster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.prototyping.video.poster'`

- [ ] **Step 3: Implement** — create `api/prototyping/video/poster.py`:

```python
"""Representative poster-frame selection for source videos.

Pure policy module (no cv2/numpy/Modal imports) so it can be unit-tested and
bundled into the Modal image via add_local_python_source. The CUDA decode loop
feeds sampled frames' brightness/detail here; the picker tracks the best
candidate and the caller snapshots the pixels whenever consider() says so.
Thresholds mirror the CLIP index content filter so we never pick a black,
blown-out, or flat (title card / credits) frame.
"""

POSTER_MIN_BRIGHTNESS = 40.0
POSTER_MAX_BRIGHTNESS = 215.0
POSTER_MIN_DETAIL = 14.0
# Only frames in this fraction-of-duration window are considered; the target is
# ~20% in — past intros/logos, well before spoiler territory.
POSTER_WINDOW = (0.05, 0.45)
POSTER_TARGET_FRAC = 0.20
POSTER_SAMPLE_EVERY_SEC = 2.0


def score_poster_candidate(ts_frac: float, *, brightness: float, detail: float) -> float | None:
    """Score a sampled frame; None means rejected outright."""
    if not (POSTER_WINDOW[0] <= ts_frac <= POSTER_WINDOW[1]):
        return None
    if brightness < POSTER_MIN_BRIGHTNESS or brightness > POSTER_MAX_BRIGHTNESS:
        return None
    if detail < POSTER_MIN_DETAIL:
        return None
    # More texture is better; drifting from the target timestamp costs points.
    return detail - 60.0 * abs(ts_frac - POSTER_TARGET_FRAC)


class PosterPicker:
    def __init__(self, duration_sec: float):
        self._duration_sec = max(float(duration_sec), 1e-6)
        self._best_score: float | None = None
        self.best_ts_sec: float | None = None

    def consider(self, ts_sec: float, *, brightness: float, detail: float) -> bool:
        score = score_poster_candidate(
            ts_sec / self._duration_sec, brightness=brightness, detail=detail
        )
        if score is None:
            return False
        if self._best_score is not None and score <= self._best_score:
            return False
        self._best_score = score
        self.best_ts_sec = ts_sec
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest api/prototyping/video/test_poster.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add api/prototyping/video/poster.py api/prototyping/video/test_poster.py
git commit -m "feat(video): pure poster-frame picker with brightness/detail/window policy"
```

---

### Task 3: Backend — capture the poster frame in the CUDA analyzer + bundle the module in both Modal apps

**Files:**
- Modify: `api/prototyping/video/analysis_cuda.py` (imports, decode loop lines ~44-79, result dict lines ~103-108)
- Modify: `api/prototyping/video/storage_modal.py:38` (`add_local_python_source`)
- Modify: `api/prototyping/video/analysis_modal.py:33` (`add_local_python_source` — also fixes the latent missing `"credits"` entry that would break the next `eclypte-video` deploy)

**Interfaces:**
- Consumes: `PosterPicker`, `POSTER_SAMPLE_EVERY_SEC` from Task 2 (imported as the bare `poster` module inside Modal, matching how `scenes`/`motion` are imported).
- Produces: `analyze_cuda(...)` result dict gains two optional top-level keys: `poster_jpeg_b64: str` (base64 JPEG, max width 854) and `poster_ts_sec: float`. Task 4 pops them before publishing the analysis JSON. Absent when no acceptable frame exists — callers must treat them as optional.

No local unit test is possible (requires cv2.cuda); the policy is covered by Task 2 and the wiring is smoke-verified at redeploy time (Verification section). This task is code + lint only.

- [ ] **Step 1: Wire the picker into `analysis_cuda.py`.** Add the import next to the other bare-module imports (line ~7-10):

```python
from poster import PosterPicker, POSTER_SAMPLE_EVERY_SEC
```

Before the `cap = cv2.VideoCapture(...)` line (~36), initialize:

```python
    poster_picker = PosterPicker(src_meta["duration_sec"])
    poster_frame = None
    poster_sample_every = max(1, int(fps_hz * POSTER_SAMPLE_EVERY_SEC))
```

Inside the decode loop, immediately after `gray = to_gray_small(frame)` (~line 56), add:

```python
            if fi % poster_sample_every == 0 and poster_picker.consider(
                ts, brightness=float(gray.mean()), detail=float(gray.std())
            ):
                poster_frame = frame.copy()
```

After the `finally: cap.release()` block and before building `scene_dicts` (~line 82), add the encode:

```python
    poster_payload = {}
    if poster_frame is not None:
        import base64

        height, width = poster_frame.shape[:2]
        if width > 854:
            scale = 854 / width
            poster_frame = cv2.resize(poster_frame, (854, max(1, int(height * scale))))
        ok, jpeg = cv2.imencode(".jpg", poster_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if ok:
            poster_payload = {
                "poster_jpeg_b64": base64.b64encode(jpeg.tobytes()).decode("ascii"),
                "poster_ts_sec": round(float(poster_picker.best_ts_sec or 0.0), 3),
            }
```

And merge it into the result dict (~line 103):

```python
    result = {
        "schema_version": SCHEMA_VERSION,
        "source": src_meta,
        "scenes": scene_dicts,
        "credits": credits,
        **poster_payload,
    }
```

- [ ] **Step 2: Bundle `poster` into both Modal images.** In `storage_modal.py` line 38:

```python
    .add_local_python_source("analysis_cuda", "scenes", "motion", "impact", "credits", "modal_s3", "progress_events", "poster")
```

In `analysis_modal.py` line 33 (adding the missing `credits` too):

```python
    .add_local_python_source("analysis_cuda", "scenes", "motion", "impact", "credits", "poster")
```

- [ ] **Step 3: Sanity-check imports parse** (the CUDA module can't run locally, but it must still be valid Python):

Run: `python -c "import ast; ast.parse(open('api/prototyping/video/analysis_cuda.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the video test suite** (pure-logic tests only — nothing here imports cv2.cuda):

Run: `python -m pytest api/prototyping/video -v`
Expected: PASS (poster tests + existing credits/scenes tests)

- [ ] **Step 5: Commit**

```bash
git add api/prototyping/video/analysis_cuda.py api/prototyping/video/storage_modal.py api/prototyping/video/analysis_modal.py
git commit -m "feat(video): capture a representative poster frame during CUDA analysis"
```

**Deploy note (for the final rollout, not this commit):** after this lands, redeploy from `api/prototyping/` with `PYTHONUTF8=1 modal deploy video/storage_modal.py`. Deploy Railway (Tasks 1+4) BEFORE the Modal redeploy so the workflow is ready to strip `poster_jpeg_b64`; an old workflow + new Modal would store the base64 key inside the analysis JSON (harmless but bloated).

---

### Task 4: Backend — `run_video_analysis` publishes the poster + records output refs

**Files:**
- Modify: `api/workflows.py:784-833` (`run_video_analysis`)
- Test: `api/test_workflows.py` (append)

**Interfaces:**
- Consumes: `analyze_r2` result with optional `poster_jpeg_b64`/`poster_ts_sec` (Task 3); `repo.publish_bytes(file_ref=, body=, content_type=, original_filename=, created_by_step=, derived_from_step=, input_file_version_ids=, derived_from_run_id=)`.
- Produces: run outputs gain `source_poster_file_id` + `source_poster_version_id` (consumed by Task 1's `summarize_asset`); a `source_poster` file manifest `file_source_poster_{run_id}`. Poster publishing is best-effort — a poster failure must never fail the analysis run.

- [ ] **Step 1: Write the failing test** — append to `api/test_workflows.py` (reuse the file's existing imports of `InMemoryObjectStore`, `StorageRepository`, `DefaultWorkflowRunner`, `RunRef`, `FileRef`; add `import base64`, `import sys`, `import types` at the top if absent):

```python
def test_run_video_analysis_publishes_source_poster(monkeypatch):
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    runner = DefaultWorkflowRunner()
    monkeypatch.setattr(runner, "_repository", lambda: repo)
    monkeypatch.setattr(runner, "_r2_config_payload", lambda: {"bucket": "b"})

    source_ref = FileRef(user_id="user_123", file_id="file_video")
    repo.create_file_manifest(file_ref=source_ref, kind="source_video", display_name="film.mp4")
    source_version = repo.publish_bytes(
        file_ref=source_ref,
        body=b"video-bytes",
        content_type="video/mp4",
        original_filename="film.mp4",
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    run = repo.create_run(
        user_id="user_123",
        workflow_type="video_analysis",
        inputs={"source_video_file_id": "file_video", "source_video_version_id": source_version.version_id},
        steps=["analyze_video"],
    )

    poster_b64 = base64.b64encode(b"jpeg-bytes").decode("ascii")
    payload = {
        "schema_version": 1,
        "source": {"duration_sec": 100.0},
        "scenes": [],
        "poster_jpeg_b64": poster_b64,
        "poster_ts_sec": 20.0,
    }

    class _FakeRemote:
        def remote(self, *args):
            return dict(payload)

    fake_modal = types.SimpleNamespace(
        Function=types.SimpleNamespace(from_name=lambda app, fn: _FakeRemote())
    )
    monkeypatch.setitem(sys.modules, "modal", fake_modal)

    runner.run_video_analysis(
        user_id="user_123",
        run_id=run.run_id,
        source_video={"file_id": "file_video", "version_id": source_version.version_id},
    )

    completed = repo.load_run_manifest(RunRef(user_id="user_123", run_id=run.run_id))
    assert completed.status == "completed", completed.last_error
    assert completed.outputs["source_poster_file_id"] == f"file_source_poster_{run.run_id}"
    assert completed.outputs["source_poster_version_id"].startswith("ver_")
    # The published analysis JSON must NOT contain the transport-only poster keys.
    analysis_key = [k for k in store.keys() if completed.outputs["video_analysis_version_id"] in k and k.endswith("blob")]
    import json as _json
    stored = _json.loads(store.get_bytes(analysis_key[0]).decode("utf-8"))
    assert "poster_jpeg_b64" not in stored and "poster_ts_sec" not in stored
```

If `InMemoryObjectStore` in `api/storage/test_fakes.py` lacks a `keys()` helper, use its internal dict the way other tests in the file already enumerate stored objects (check the fake first and match the existing accessor — do not add new fake methods unless nothing exists).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest api/test_workflows.py -k source_poster -v`
Expected: FAIL — `source_poster_file_id` missing from outputs (and the b64 key leaks into the stored JSON).

- [ ] **Step 3: Implement** — in `api/workflows.py` `run_video_analysis`, after `result = analyze.remote(*args)` (line ~807), strip the transport keys:

```python
            poster_b64 = result.pop("poster_jpeg_b64", None)
            result.pop("poster_ts_sec", None)
```

Then after the existing analysis `version = repo.publish_json(...)` block and BEFORE `repo.update_run_status(...)`, build outputs and best-effort publish:

```python
            outputs = {
                "video_analysis_file_id": file_ref.file_id,
                "video_analysis_version_id": version.version_id,
            }
            if poster_b64:
                try:
                    import base64

                    poster_ref = FileRef(user_id=user_id, file_id=f"file_source_poster_{run_id}")
                    repo.create_file_manifest(
                        file_ref=poster_ref,
                        kind="source_poster",
                        display_name=f"{source_meta.original_filename}.jpg",
                        source_run_id=run_id,
                    )
                    poster_version = repo.publish_bytes(
                        file_ref=poster_ref,
                        body=base64.b64decode(poster_b64),
                        content_type="image/jpeg",
                        original_filename=f"{source_meta.original_filename}.jpg",
                        created_by_step="analyze_video",
                        derived_from_step="analyze_video",
                        input_file_version_ids=[source_ref.version_id],
                        derived_from_run_id=run_id,
                    )
                    outputs["source_poster_file_id"] = poster_ref.file_id
                    outputs["source_poster_version_id"] = poster_version.version_id
                except Exception:
                    # Poster is decorative; the analysis run must not fail for it.
                    pass
```

and change the `update_run_status` call to use it:

```python
            repo.update_run_status(
                RunRef(user_id=user_id, run_id=run_id),
                status="completed",
                outputs=outputs,
            )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest api/test_workflows.py -v` → PASS (new + existing)
Run: `python -m pytest api -v` → PASS (full backend regression)

- [ ] **Step 5: Commit**

```bash
git add api/workflows.py api/test_workflows.py
git commit -m "feat(api): publish source_poster from video analysis runs"
```

---

### Task 5: Frontend — Ivory & Ink tokens (same token names, new values) + font pipeline trim

Strategy: the `[data-surface="studio"]` block keeps the **same custom-property names** with new light values, so this task alone flips the whole dashboard to the light palette with zero module edits — every commit stays shippable. Task 6 then restyles the component classes (type, casing, radii).

**Files:**
- Modify: `web/src/app/globals.css:148-202` (the `[data-surface="studio"]` block ONLY — do not touch `:root`, `[data-theme]`, the reset, or `body`)
- Modify: `web/src/app/layout.tsx` (drop Space Grotesk + JetBrains Mono)

**Interfaces:**
- Produces: same token names (`--surface-base`, `--surface-raised`, `--surface-sunk`, `--surface-overlay`, `--text-primary`, `--text-secondary`, `--text-muted`, `--line`, `--line-strong`, `--accent`, `--accent-soft`, `--accent-contrast`, `--energy`, `--ok`, `--ok-soft`, `--danger`, `--danger-soft`, `--attention`, `--attention-soft`, `--focus-ring`, `--elev-shadow`, `--radius`, `--font-display`, `--font-ui`, `--font-mono`) plus new `--text-faint`, `--radius-card`, `--shadow-card`, `--shadow-sheet`. All later tasks consume these.

- [ ] **Step 1: Replace the `[data-surface="studio"]` block** in `web/src/app/globals.css` (keep the surrounding comment banner, update its text):

```css
/* ----------------------------------------------------------------------------
   "Ivory & Ink" — the dashboard's warm, light identity. Gated entirely on
   [data-surface="studio"] (set on the dashboard container), so the marketing
   site (which uses --color-* / [data-theme="dark"]) is untouched. Token NAMES
   are stable; values define the light system. No uppercase, no noise, no
   gradients anywhere in the dashboard.
---------------------------------------------------------------------------- */
[data-surface="studio"] {
  color-scheme: light;

  /* Surfaces */
  --surface-base: #F7F5F1;
  --surface-raised: #FFFFFF;
  --surface-sunk: #F1EDE4;
  --surface-overlay: rgba(38, 35, 30, 0.28);

  /* Ink */
  --text-primary: #26231E;
  --text-secondary: #3D3A34;
  --text-muted: #8A8375;
  --text-faint: #B3AC9C;

  /* Lines */
  --line: #E9E4DB;
  --line-strong: #D8D1C4;

  /* Accent — coral, reserved for progress + attention */
  --accent: #E86A4F;
  --accent-soft: rgba(232, 106, 79, 0.12);
  --accent-contrast: #FBFAF7;
  /* Legacy alias: old CSS paints progress with --energy; now plain coral. */
  --energy: #E86A4F;

  /* Status */
  --ok: #5E8A62;
  --ok-soft: rgba(94, 138, 98, 0.14);
  --danger: #C25243;
  --danger-soft: rgba(194, 82, 67, 0.12);
  --attention: #A87B2A;
  --attention-soft: rgba(168, 123, 42, 0.14);

  /* Effects */
  --focus-ring: #E86A4F;
  --elev-shadow: 0 12px 32px rgba(50, 42, 28, 0.16);
  --shadow-card: 0 1px 3px rgba(50, 42, 28, 0.06);
  --shadow-sheet: -16px 0 40px rgba(50, 42, 28, 0.12);
  --radius: 10px;
  --radius-card: 12px;

  /* Dashboard type — one family */
  --font-display: var(--font-neue), "Helvetica Neue", Arial, system-ui, sans-serif;
  --font-ui: var(--font-neue), "Helvetica Neue", Arial, system-ui, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  background-color: var(--surface-base);
  color: var(--text-primary);
}
```

(The fractal-noise `background-image`, `background-size`, and `background-attachment` lines are deleted — no replacement.)

- [ ] **Step 2: Trim the font pipeline** in `web/src/app/layout.tsx`: delete the `Space_Grotesk` and `JetBrains_Mono` imports, the `spaceGrotesk`/`jetbrainsMono` constants (lines ~23-35 including the "Edit Bay" comment), and remove `${spaceGrotesk.variable} ${jetbrainsMono.variable}` from the body className. Everything else (Inter, Inter Tight, Outfit, Neue Montreal, Eiko) stays — the marketing `body` stack references them.

- [ ] **Step 3: Verify no orphaned font-variable references**

Run (from `web/`): `Select-String -Path src -Pattern "font-space-grotesk|font-jetbrains-mono" -SimpleMatch -Recurse` (PowerShell) or `grep -rn "font-space-grotesk\|font-jetbrains-mono" src`
Expected: no matches.

- [ ] **Step 4: Build + eyeball**

Run (from `web/`): `npm run lint` then `npm run build`
Expected: both pass. Then `npm run dev` and load `/dashboard/assets`: the dashboard is light/warm (type is still tracked-caps — that's Task 6); the marketing landing page (`/`) is pixel-identical dark.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/globals.css web/src/app/layout.tsx
git commit -m "feat(dashboard): swap Edit Bay tokens for the Ivory & Ink light system"
```

---

### Task 6: Frontend — rewrite `studio.module.css` to the Ivory & Ink component language

Full-file rewrite. **Every class name that exists today is kept** (new-edit/synthesis/settings/dashboardCommon/Select keep compiling and pick up the restyle for free); classes for the new Home/Library/primitives are added. Deletion of then-dead classes happens in Task 12 after a usage grep. Uppercase/letter-spacing are gone from every rule.

**Files:**
- Rewrite: `web/src/app/dashboard/studio.module.css`

**Interfaces:**
- Consumes: Task 5 tokens.
- Produces (new classes used by Tasks 7-10): `.spinner`, `.spinnerOnInk`, `.statusDot`, `.statusDotSwatch`, `.progressRow`, `.progressRowTop`, `.toastStack`, `.toast`, `.sheetOverlay`, `.sheet`, `.sheetHeader`, `.sheetTitle`, `.sheetBody`, `.sheetFooter`, `.topBanner`, `.feedSection`, `.feedSectionHead`, `.feedSectionTitle`, `.feedSectionCount`, `.feedSectionLink`, `.reviewCardGrid`, `.reviewCard`, `.posterThumb`, `.posterThumbPlaceholder`, `.reviewCardBody`, `.captionPreview`, `.workRow`, `.queueRow`, `.queueThumb`, `.postedStrip`, `.postedCard`, `.postedThumb`, `.postedMeta`, `.statusLine`, `.statusOnDot`, `.switchButton`, `.switchButtonOn`, `.mediaGrid`, `.mediaCard`, `.mediaCardBody`, `.mediaThumb`, `.mediaTitle`, `.mediaMeta`, `.songRow`, `.songArt`, `.tabPills`, `.pill`, `.pillActive`, `.hiddenLink`, `.uploadDrop`, `.sheetActionsRight`.

- [ ] **Step 1: Replace the entire file** with:

```css
/* Ivory & Ink — dashboard component language. One typeface, sentence case,
   no uppercase/letter-spacing anywhere. Legacy class names are preserved so
   remaining pages restyle without edits. */

.page {
	display: flex;
	flex-direction: column;
	gap: 2.2rem;
	color: var(--text-primary);
	max-width: 1140px;
	margin: 0 auto;
	width: 100%;
}

.header {
	display: flex;
	align-items: flex-end;
	justify-content: space-between;
	gap: 2rem;
	padding: 0 0 1.4rem;
}

.eyebrow {
	margin: 0 0 0.4rem;
	color: var(--text-faint);
	font-family: var(--font-ui);
	font-size: 0.82rem;
	font-weight: 500;
}

.title {
	margin: 0;
	font-family: var(--font-ui);
	font-size: 1.9rem;
	font-weight: 500;
	line-height: 1.15;
	letter-spacing: -0.015em;
}

.subtitle {
	margin: 0.5rem 0 0;
	max-width: 56ch;
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.92rem;
	line-height: 1.6;
}

.toolbar {
	display: flex;
	align-items: center;
	gap: 0.6rem;
	flex-wrap: wrap;
}

.grid {
	display: grid;
	grid-template-columns: repeat(12, minmax(0, 1fr));
	gap: 1.2rem;
}

.panel,
.detailPanel {
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	box-shadow: var(--shadow-card);
	padding: 1.3rem 1.4rem;
	display: flex;
	flex-direction: column;
	gap: 1rem;
	min-width: 0;
}

.assetCard,
.runCard,
.jobCard,
.listCard {
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	box-shadow: var(--shadow-card);
	padding: 1rem 1.1rem;
	display: flex;
	flex-direction: column;
	gap: 0.75rem;
	min-width: 0;
}

.settingCard {
	display: flex;
	align-items: flex-start;
	gap: 0.85rem;
	min-width: 0;
	color: var(--text-secondary);
}

.settingCard > div { min-width: 0; }

.wide { grid-column: span 8; }
.side { grid-column: span 4; }
.full { grid-column: 1 / -1; }

.panelHeader {
	display: flex;
	align-items: flex-end;
	justify-content: space-between;
	gap: 1rem;
	padding-bottom: 0.7rem;
	border-bottom: 1px solid var(--line);
}

.panelHeader h2 {
	margin: 0;
	font-family: var(--font-ui);
	font-size: 0.98rem;
	font-weight: 500;
}

.assetCard h3,
.runCard h3,
.listCard h3,
.jobCard h3 {
	margin: 0;
	font-family: var(--font-ui);
	font-size: 0.98rem;
	font-weight: 500;
	line-height: 1.3;
	overflow-wrap: anywhere;
}

.cardTop > div,
.panelHeader > div { min-width: 0; }

.panelHeader p,
.muted,
.smallText {
	margin: 0.35rem 0 0;
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.82rem;
	line-height: 1.5;
	overflow-wrap: anywhere;
}

/* --- Buttons: ink primary, soft secondary, ghost tertiary. Sentence case. --- */
.primaryButton,
.secondaryButton,
.ghostButton,
.dangerButton {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	gap: 0.45rem;
	min-height: 38px;
	padding: 0.5rem 1rem;
	border-radius: var(--radius);
	border: 1px solid transparent;
	font-family: var(--font-ui);
	font-size: 0.86rem;
	font-weight: 500;
	cursor: pointer;
	transition: background-color 140ms ease, color 140ms ease, opacity 140ms ease;
}

.primaryButton { background: var(--text-primary); color: var(--accent-contrast); }
.primaryButton:hover:not(:disabled) { background: #3A362F; }

.secondaryButton { background: var(--surface-sunk); color: var(--text-secondary); }
.secondaryButton:hover:not(:disabled) { background: #E9E3D7; }

.ghostButton { background: transparent; color: var(--text-muted); }
.ghostButton:hover:not(:disabled) { color: var(--text-primary); }

.dangerButton { background: transparent; color: var(--danger); }
.dangerButton:hover:not(:disabled) { background: var(--danger-soft); }

.primaryButton:disabled,
.secondaryButton:disabled,
.ghostButton:disabled,
.dangerButton:disabled,
.segmentButton:disabled,
.segmentActive:disabled { cursor: not-allowed; opacity: 0.45; }

.primaryButton:focus-visible,
.secondaryButton:focus-visible,
.ghostButton:focus-visible,
.dangerButton:focus-visible,
.segmentButton:focus-visible,
.segmentActive:focus-visible,
.pagerButton:focus-visible,
.disclosureToggle:focus-visible,
.assetRow:focus-visible,
.pill:focus-visible,
.pillActive:focus-visible,
.reviewCard:focus-visible,
.mediaCard:focus-visible,
.switchButton:focus-visible,
.filmstripCard:focus-visible {
	outline: 2px solid var(--focus-ring);
	outline-offset: 2px;
}

/* --- Spinner: the only busy indicator. --- */
.spinner {
	display: inline-block;
	width: 14px;
	height: 14px;
	border-radius: 50%;
	border: 2px solid var(--surface-sunk);
	border-top-color: var(--accent);
	animation: spin 0.9s linear infinite;
	flex: none;
}

.spinnerOnInk { border-color: rgba(255, 255, 255, 0.3); border-top-color: var(--accent-contrast); }

@keyframes spin { to { transform: rotate(360deg); } }

/* --- Status: a dot and a plain word (replaces badge boxes). --- */
.badge,
.statusDot {
	display: inline-flex;
	align-items: center;
	gap: 0.42rem;
	border: none;
	padding: 0;
	color: var(--text-secondary);
	background: transparent;
	font-family: var(--font-ui);
	font-size: 0.82rem;
	font-weight: 500;
	white-space: nowrap;
}

.badgeDot,
.statusDotSwatch {
	width: 8px;
	height: 8px;
	border-radius: 999px;
	background: var(--text-faint);
	flex: none;
}

.analyzing .badgeDot, .running .badgeDot, .queued .badgeDot, .scheduled .badgeDot,
.activeStage .stageDot { background: var(--accent); }
.ready .badgeDot, .completed .badgeDot, .available .badgeDot, .approved .badgeDot,
.imported .badgeDot, .published .badgeDot, .completeStage .stageDot { background: var(--ok); }
.failed .badgeDot, .rejected .badgeDot, .failedStage .stageDot { background: var(--danger); }
.canceled .badgeDot, .archived .badgeDot { background: var(--text-faint); }
.uploaded .badgeDot { background: var(--attention); }
.discovered .badgeDot, .created .badgeDot, .blocked .badgeDot {
	background: transparent;
	border: 1.5px solid var(--text-faint);
}

/* --- Inputs --- */
.input,
.textarea {
	width: 100%;
	box-sizing: border-box;
	border: 1px solid var(--line-strong);
	border-radius: var(--radius);
	background: var(--surface-raised);
	color: var(--text-primary);
	font-family: var(--font-ui);
	font-size: 0.92rem;
	outline: none;
	transition: border-color 140ms ease;
}

.input { min-height: 40px; padding: 0 0.75rem; }

.textarea {
	min-height: 150px;
	resize: vertical;
	line-height: 1.55;
	padding: 0.7rem 0.85rem;
}

.compactTextarea { min-height: 88px; }

.promptTextarea {
	min-height: 60vh;
	font-family: var(--font-mono);
	font-size: 0.84rem;
	line-height: 1.6;
	padding: 1rem 1.1rem;
}

.input:focus,
.textarea:focus,
.promptTextarea:focus { border-color: var(--text-primary); }
.filePicker:focus-within { border-color: var(--text-primary); }

/* --- Select (consumed by Select.tsx — names unchanged) --- */
.selectWrap { position: relative; width: 100%; }
.selectWrapCompact { width: auto; display: inline-flex; }

.selectTrigger {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 0.75rem;
	width: 100%;
	box-sizing: border-box;
	min-height: 40px;
	padding: 0 0.75rem;
	border: 1px solid var(--line-strong);
	border-radius: var(--radius);
	background: var(--surface-raised);
	color: var(--text-primary);
	font-family: var(--font-ui);
	font-size: 0.92rem;
	text-align: left;
	cursor: pointer;
	transition: border-color 140ms ease;
}

.selectTrigger:hover:not(:disabled) { border-color: var(--text-muted); }
.selectTrigger:disabled { cursor: not-allowed; opacity: 0.45; }
.selectTrigger:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.selectTriggerOpen { border-color: var(--text-primary); }

.selectCompact {
	width: auto;
	min-width: 140px;
	min-height: 34px;
	padding: 0.3rem 0.7rem;
	font-size: 0.84rem;
}

.selectValue,
.selectPlaceholder { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selectPlaceholder { color: var(--text-faint); }

.selectChevron { flex-shrink: 0; color: var(--text-muted); transition: transform 160ms ease; }
.selectTriggerOpen .selectChevron { transform: rotate(180deg); }

.selectPopover {
	position: absolute;
	top: calc(100% + 6px);
	left: 0;
	z-index: 40;
	min-width: 100%;
	width: max-content;
	max-width: min(92vw, 30rem);
	max-height: 15rem;
	overflow-y: auto;
	padding: 0.3rem;
	background: var(--surface-raised);
	border: 1px solid var(--line);
	border-radius: var(--radius);
	box-shadow: var(--elev-shadow);
}

.selectPopoverUp { top: auto; bottom: calc(100% + 6px); }

.selectOption {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 0.75rem;
	padding: 0.5rem 0.6rem;
	border-radius: 7px;
	color: var(--text-secondary);
	font-family: var(--font-ui);
	font-size: 0.9rem;
	cursor: pointer;
}

.selectOptionLabel { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selectOptionActive { background: var(--surface-sunk); color: var(--text-primary); }
.selectOptionSelected { color: var(--accent); }
.selectOption[aria-disabled="true"] { opacity: 0.45; cursor: not-allowed; }

.selectEmpty { padding: 0.7rem 0.6rem; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.86rem; }

/* --- Fields --- */
.fieldStack { display: flex; flex-direction: column; gap: 1.2rem; }

.fieldLabel {
	display: flex;
	flex-direction: column;
	gap: 0.45rem;
	color: var(--text-secondary);
	font-family: var(--font-ui);
	font-size: 0.84rem;
	font-weight: 500;
}

.segmentedControl { display: inline-flex; gap: 0.4rem; background: transparent; border: none; }

.segmentButton,
.segmentActive {
	min-height: 34px;
	padding: 0.3rem 0.9rem;
	border: none;
	border-radius: 999px;
	background: transparent;
	font-family: var(--font-ui);
	font-size: 0.86rem;
	font-weight: 500;
	cursor: pointer;
	transition: color 140ms ease, background-color 140ms ease;
}

.segmentButton { color: var(--text-muted); }
.segmentButton:hover:not(:disabled) { color: var(--text-primary); }
.segmentActive { color: var(--accent-contrast); background: var(--text-primary); }

.exportSection { display: flex; flex-direction: column; gap: 1rem; padding-top: 1.1rem; border-top: 1px solid var(--line); }

.exportHeader,
.trimSummary {
	display: flex;
	justify-content: space-between;
	gap: 1rem;
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.84rem;
	font-weight: 500;
}

.exportHeader > :first-child { color: var(--text-primary); }
.trimSummary { padding: 0.2rem 0 0.4rem; border-bottom: 1px solid var(--line); color: var(--text-primary); }

.rangeGrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }

.rangeLabel {
	display: flex;
	flex-direction: column;
	gap: 0.5rem;
	color: var(--text-secondary);
	font-family: var(--font-ui);
	font-size: 0.84rem;
	font-weight: 500;
}

.rangeInput { width: 100%; accent-color: var(--accent); cursor: pointer; }
.rangeInput:disabled { cursor: not-allowed; opacity: 0.45; }

.numberGrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }

.cropPreview {
	position: relative;
	display: grid;
	place-items: center;
	overflow: hidden;
	width: min(100%, 360px);
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-sunk);
}

.cropPreviewVertical { aspect-ratio: 9 / 16; max-height: 460px; }
.cropPreviewWide { aspect-ratio: 16 / 9; }
.cropPreviewMedia { width: 100%; height: 100%; background: var(--surface-sunk); }

.cropPreviewEmpty { padding: 1.4rem; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.9rem; text-align: center; }

.filePicker {
	position: relative;
	display: flex;
	flex-direction: column;
	gap: 0.45rem;
	min-height: 120px;
	padding: 1.2rem 1.1rem;
	border: 1.5px dashed var(--line-strong);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	cursor: pointer;
	transition: border-color 140ms ease;
}

.filePicker:hover { border-color: var(--text-muted); }
.filePicker input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }

.fileName { color: var(--text-primary); font-family: var(--font-ui); font-size: 0.98rem; font-weight: 500; overflow-wrap: anywhere; line-height: 1.35; }

.errorBanner,
.successBanner,
.topBanner {
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	padding: 0.8rem 1rem;
	font-family: var(--font-ui);
	font-size: 0.88rem;
	line-height: 1.55;
	color: var(--text-primary);
	display: flex;
	align-items: center;
	gap: 0.75rem;
	flex-wrap: wrap;
}

.errorBanner { border-color: rgba(194, 82, 67, 0.35); background: var(--danger-soft); }
.successBanner { border-color: rgba(94, 138, 98, 0.35); background: var(--ok-soft); }
.topBanner { background: var(--surface-raised); box-shadow: var(--shadow-card); }

.stageList, .assetList, .runList, .versionList, .referenceList {
	display: flex; flex-direction: column; gap: 0.7rem; margin: 0; padding: 0; list-style: none;
}

.stageItem {
	display: grid;
	grid-template-columns: 18px 1fr;
	gap: 0.6rem;
	align-items: start;
	padding: 0.8rem 0.95rem;
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
}

.stageDot { width: 8px; height: 8px; margin-top: 0.4rem; border-radius: 999px; background: var(--text-faint); }
.stageLabel { display: block; color: var(--text-primary); font-family: var(--font-ui); font-size: 0.88rem; font-weight: 500; }
.stageDetail { display: block; margin-top: 0.2rem; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.82rem; }

.assetGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
.settingsGrid { display: grid; grid-template-columns: 1fr; gap: 1.1rem; }

.settingLabel { display: block; margin-bottom: 0.3rem; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.8rem; font-weight: 500; }

/* --- Pager --- */
.pager { display: flex; align-items: center; justify-content: flex-end; gap: 0.9rem; padding-top: 0.9rem; }
.pagerTop { padding-top: 0; margin-bottom: 0.5rem; }

.pagerStatus { font-family: var(--font-ui); font-size: 0.8rem; color: var(--text-muted); white-space: nowrap; }

.pagerButton {
	display: inline-flex;
	align-items: center;
	gap: 0.3rem;
	min-height: 32px;
	padding: 0.35rem 0.7rem;
	border: 1px solid var(--line-strong);
	border-radius: var(--radius);
	background: var(--surface-raised);
	color: var(--text-secondary);
	font-family: var(--font-ui);
	font-size: 0.82rem;
	font-weight: 500;
	cursor: pointer;
	transition: border-color 140ms ease, color 140ms ease, opacity 140ms ease;
}

.pagerButton:hover:not(:disabled) { border-color: var(--text-muted); color: var(--text-primary); }
.pagerButton:disabled { opacity: 0.45; cursor: not-allowed; }

.libraryFilters { display: flex; align-items: center; gap: 0.6rem; padding-bottom: 0.9rem; }
.libraryFilterLabel { font-family: var(--font-ui); font-size: 0.82rem; color: var(--text-muted); }

.cardTop { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.85rem; }
.cardActions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: auto; padding-top: 0.3rem; }
.jobList { display: flex; flex-direction: column; gap: 0.9rem; }

/* --- Progress --- */
.progressHeader,
.stageProgressMeta,
.progressRowTop {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 0.65rem;
	color: var(--text-primary);
	font-family: var(--font-ui);
	font-size: 0.84rem;
	font-weight: 500;
}

.progressRowTop > span:last-child,
.stageProgressMeta > span:last-child { color: var(--text-muted); font-weight: 400; }

.progressTrack { position: relative; width: 100%; height: 5px; overflow: hidden; border-radius: 4px; background: var(--surface-sunk); }
.progressFill { height: 100%; border-radius: 4px; background: var(--accent); transition: width 240ms ease; }
.completeStage .progressFill { background: var(--ok); }
.failedStage .progressFill { background: var(--danger); }

.progressRow {
	display: flex;
	flex-direction: column;
	gap: 0.55rem;
	padding: 0.85rem 1rem;
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	box-shadow: var(--shadow-card);
}

.stageProgressList { display: flex; flex-direction: column; gap: 0.6rem; }
.stageProgressRow {
	display: flex;
	flex-direction: column;
	gap: 0.4rem;
	padding: 0.7rem 0.85rem;
	border: 1px solid var(--line);
	border-radius: var(--radius);
	background: var(--surface-base);
}

.previewMedia {
	width: 100%;
	max-height: 480px;
	border-radius: var(--radius-card);
	background: var(--surface-sunk);
	border: 1px solid var(--line);
}

.posterButton { position: relative; display: block; width: 100%; padding: 0; border: none; background: none; cursor: pointer; }
.posterButton .previewMedia { display: block; object-fit: cover; }

.posterPlayIcon {
	position: absolute;
	inset: 0;
	display: grid;
	place-items: center;
	color: #fff;
	background: rgba(38, 35, 30, 0.34);
	border-radius: var(--radius-card);
	transition: background 160ms ease;
}

.posterButton:hover .posterPlayIcon,
.posterButton:focus-visible .posterPlayIcon { background: rgba(38, 35, 30, 0.5); }

/* --- Skeletons (initial loads only) --- */
.skeletonList { display: flex; flex-direction: column; gap: 0.8rem; }

.skeletonCard {
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	padding: 1rem 1.1rem;
	display: flex;
	flex-direction: column;
	gap: 0.7rem;
}

.skeleton {
	display: block;
	height: 0.8rem;
	width: 100%;
	border-radius: 6px;
	background: linear-gradient(90deg, var(--surface-sunk) 0%, #EDE8DE 50%, var(--surface-sunk) 100%);
	background-size: 200% 100%;
	animation: skeletonShimmer 1.4s ease-in-out infinite;
}

.skeletonTitle { height: 1.05rem; width: 45%; }
.skeletonLine { width: 90%; }
.skeletonLineShort { width: 60%; }

@keyframes skeletonShimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

/* --- Empty states: friendly sentence + action, never italic. --- */
.emptyState {
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 0.5rem;
	padding: 2.4rem 1.4rem;
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.95rem;
	text-align: center;
}

.emptyStateIcon { display: inline-flex; color: var(--text-faint); margin-bottom: 0.2rem; }
.emptyStateTitle { margin: 0; color: var(--text-secondary); font-size: 1rem; font-weight: 500; }
.emptyStateHint { margin: 0; max-width: 42ch; font-size: 0.85rem; line-height: 1.55; color: var(--text-muted); }
.emptyStateAction { margin-top: 0.6rem; }

.metaList { display: grid; grid-template-columns: 1fr; gap: 0.5rem; margin: 0; }
.metaRow {
	display: grid;
	grid-template-columns: minmax(120px, 0.7fr) 1fr;
	gap: 1rem;
	align-items: baseline;
	padding: 0.5rem 0;
	border-bottom: 1px solid var(--line);
}
.metaKey { color: var(--text-muted); font-family: var(--font-ui); font-size: 0.8rem; font-weight: 500; }
.metaValue { margin: 0; color: var(--text-primary); font-family: var(--font-ui); font-size: 0.9rem; overflow-wrap: anywhere; }

.copyId {
	display: inline-flex;
	align-items: center;
	gap: 0.4rem;
	padding: 0.3rem 0.6rem;
	border: 1px solid var(--line-strong);
	border-radius: var(--radius);
	background: transparent;
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.78rem;
	font-weight: 500;
	cursor: pointer;
	transition: color 140ms ease, border-color 140ms ease;
}
.copyId:hover { color: var(--text-primary); border-color: var(--text-muted); }
.copyId:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

.detailLink {
	display: inline-flex;
	align-items: center;
	gap: 0.35rem;
	color: var(--text-primary);
	text-decoration: underline;
	text-decoration-color: var(--line-strong);
	text-underline-offset: 3px;
	font-family: var(--font-ui);
	font-size: 0.9rem;
	overflow-wrap: anywhere;
}
.detailLink:hover { text-decoration-color: var(--text-primary); }

.proseText { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-secondary); font-family: var(--font-ui); font-size: 0.9rem; line-height: 1.65; }
.numeral { font-family: var(--font-ui); font-weight: 500; color: var(--text-primary); }

/* --- Legacy asset table (new-edit job list still uses rows) --- */
.assetTable { display: flex; flex-direction: column; }

.assetTableHeader {
	display: grid;
	grid-template-columns: minmax(0, 1fr) minmax(0, max-content);
	gap: 1.5rem;
	padding: 0 0.6rem 0.6rem 0.75rem;
	border-bottom: 1px solid var(--line);
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.8rem;
	font-weight: 500;
}

.assetRow {
	display: grid;
	grid-template-columns: minmax(0, 1fr) minmax(0, max-content);
	gap: 1.5rem;
	align-items: center;
	padding: 0.65rem 0.6rem 0.65rem 0.75rem;
	border: none;
	border-bottom: 1px solid var(--line);
	cursor: pointer;
	background: transparent;
	width: 100%;
	text-align: left;
	font-family: inherit;
	color: var(--text-primary);
	transition: background-color 140ms ease;
}

.assetTableHeader > :last-child, .assetRow > :last-child { justify-self: end; }
.assetRow:hover { background: var(--surface-sunk); }
.assetRowSelected { background: var(--surface-sunk); box-shadow: inset 3px 0 0 var(--accent); }

.assetRowName { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.assetRowTitle { font-family: var(--font-ui); font-size: 0.94rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assetRowMeta { font-family: var(--font-ui); font-size: 0.8rem; color: var(--text-muted); }
.assetRowCellNumeral { font-family: var(--font-ui); font-size: 0.94rem; font-weight: 500; }

.detailEmpty { padding: 2.2rem 1.4rem; color: var(--text-muted); font-family: var(--font-ui); text-align: center; font-size: 0.95rem; }
.detailTitle { margin: 0; font-family: var(--font-ui); font-size: 1.15rem; font-weight: 500; overflow-wrap: anywhere; }

.disclosure { display: flex; flex-direction: column; }

.disclosureToggle {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 1rem;
	padding: 1rem 0;
	border: none;
	border-bottom: 1px solid var(--line);
	background: transparent;
	color: var(--text-secondary);
	font-family: var(--font-ui);
	font-size: 0.88rem;
	font-weight: 500;
	cursor: pointer;
	width: 100%;
	text-align: left;
}

.disclosureToggle:hover { color: var(--text-primary); }
.disclosureCaret { display: inline-block; font-size: 1.1rem; line-height: 1; transition: transform 200ms ease; }
.disclosureOpen .disclosureCaret { transform: rotate(45deg); }
.disclosureBody { padding: 1.3rem 0 0; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 1.2rem; }

.filmstrip { display: flex; gap: 0.9rem; overflow-x: auto; padding: 0.3rem 0 0.9rem; scroll-snap-type: x mandatory; }

.filmstripCard {
	flex: 0 0 220px;
	display: flex;
	flex-direction: column;
	gap: 0.55rem;
	padding: 0.75rem;
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	cursor: pointer;
	scroll-snap-align: start;
	transition: border-color 140ms ease;
	min-width: 0;
}

.filmstripCard:hover { border-color: var(--text-muted); }
.filmstripActive { border-color: var(--text-primary); background: var(--surface-sunk); }

.filmstripFrame {
	width: 100%;
	height: 120px;
	background: var(--surface-sunk);
	border-radius: var(--radius);
	color: var(--text-muted);
	display: flex;
	align-items: center;
	justify-content: center;
	font-family: var(--font-ui);
	font-size: 0.88rem;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	padding: 0 0.6rem;
	text-align: center;
}

.heroPlayer { display: flex; flex-direction: column; gap: 1.1rem; max-width: 1080px; margin: 0 auto; width: 100%; }
.heroCaption { display: flex; align-items: flex-end; justify-content: space-between; gap: 1.3rem; flex-wrap: wrap; }
.heroCaptionTitle { margin: 0; font-family: var(--font-ui); font-size: 1.2rem; font-weight: 500; overflow-wrap: anywhere; }
.heroCaptionMeta { margin: 0.3rem 0 0; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.82rem; }

.settingsStack { display: flex; flex-direction: column; max-width: 720px; width: 100%; }
.settingsGroup { display: flex; flex-direction: column; gap: 1.2rem; padding: 1.7rem 0; border-bottom: 1px solid var(--line); }
.settingsGroupHeader { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin-bottom: 0.4rem; }
.settingsGroupTitle { margin: 0; font-family: var(--font-ui); font-size: 0.98rem; font-weight: 500; color: var(--text-primary); }
.settingsRow { display: grid; grid-template-columns: minmax(140px, 1fr) 3fr; gap: 1.3rem; align-items: baseline; padding: 0.35rem 0; }
.settingsRowLabel { color: var(--text-muted); font-family: var(--font-ui); font-size: 0.84rem; }
.settingsRowValue { color: var(--text-primary); font-family: var(--font-ui); font-size: 0.94rem; overflow-wrap: anywhere; }

.queueStrip { display: flex; flex-direction: column; gap: 0.8rem; }
.queueLine { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0.85rem; align-items: baseline; padding: 0.65rem 0; border-bottom: 1px solid var(--line); font-family: var(--font-ui); font-size: 0.88rem; color: var(--text-secondary); min-width: 0; }
.queueLineNumeral { font-family: var(--font-ui); font-size: 0.95rem; font-weight: 500; color: var(--text-primary); }
.queueLineTitle { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.queueLineMeta { color: var(--text-muted); font-size: 0.8rem; white-space: nowrap; }

.assetCaption { margin: 0.5rem 0 0; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.82rem; }
.assetCaptionOk { color: var(--ok); }

.packageList { display: flex; flex-direction: column; }
.packageRow {
	display: flex;
	flex-direction: column;
	gap: 0.35rem;
	width: 100%;
	padding: 0.9rem 0.2rem 0.9rem 0.6rem;
	border: none;
	border-bottom: 1px solid var(--line);
	background: transparent;
	color: var(--text-primary);
	font-family: inherit;
	text-align: left;
	cursor: pointer;
	transition: background-color 140ms ease;
}
.packageRow:hover { background: var(--surface-sunk); }
.packageRowSelected { background: var(--surface-sunk); box-shadow: inset 3px 0 0 var(--accent); }
.packageRowHead { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; min-width: 0; }
.packageRowTitle { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-ui); font-size: 0.95rem; font-weight: 500; }
.packageRowMeta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-ui); font-size: 0.8rem; color: var(--text-muted); }

.haltClearButton { margin-left: auto; }

/* ============ NEW: toasts ============ */
.toastStack {
	position: fixed;
	left: 1.2rem;
	bottom: 1.2rem;
	z-index: 90;
	display: flex;
	flex-direction: column;
	gap: 0.5rem;
	pointer-events: none;
}

.toast {
	display: inline-flex;
	align-items: center;
	gap: 0.55rem;
	background: var(--text-primary);
	color: var(--accent-contrast);
	border-radius: 11px;
	padding: 0.65rem 1rem;
	font-family: var(--font-ui);
	font-size: 0.88rem;
	box-shadow: var(--elev-shadow);
	pointer-events: auto;
}

.toastOk { color: #9FCBA4; }
.toastErr { color: #F0A79B; }

/* ============ NEW: sheet (slide-over desktop / bottom sheet mobile) ============ */
.sheetOverlay { position: fixed; inset: 0; z-index: 80; background: var(--surface-overlay); border: none; padding: 0; cursor: default; }

.sheet {
	position: fixed;
	top: 0;
	right: 0;
	bottom: 0;
	z-index: 81;
	width: min(480px, 96vw);
	background: #FBFAF7;
	border-left: 1px solid var(--line);
	box-shadow: var(--shadow-sheet);
	display: flex;
	flex-direction: column;
	gap: 1rem;
	padding: 1.4rem 1.5rem;
	overflow-y: auto;
}

.sheetHeader { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.sheetTitle { margin: 0; font-family: var(--font-ui); font-size: 1.15rem; font-weight: 500; letter-spacing: -0.01em; overflow-wrap: anywhere; }
.sheetBody { display: flex; flex-direction: column; gap: 1rem; }
.sheetFooter { display: flex; gap: 0.55rem; align-items: center; margin-top: auto; padding-top: 1rem; flex-wrap: wrap; }
.sheetActionsRight { margin-left: auto; display: inline-flex; gap: 0.55rem; }

/* ============ NEW: Home feed ============ */
.statusLine { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.88rem; }
.statusOnDot { width: 8px; height: 8px; border-radius: 999px; background: var(--ok); flex: none; }
.statusOffDot { width: 8px; height: 8px; border-radius: 999px; background: var(--text-faint); flex: none; }

.switchButton {
	position: relative;
	width: 36px;
	height: 21px;
	border-radius: 999px;
	border: none;
	background: var(--line-strong);
	cursor: pointer;
	transition: background-color 140ms ease;
	flex: none;
}
.switchButton::after {
	content: "";
	position: absolute;
	left: 2.5px;
	top: 2.5px;
	width: 16px;
	height: 16px;
	border-radius: 50%;
	background: #fff;
	transition: transform 140ms ease;
}
.switchButtonOn { background: var(--text-primary); }
.switchButtonOn::after { transform: translateX(15px); }

.feedSection { display: flex; flex-direction: column; gap: 0.7rem; }
.feedSectionHead { display: flex; align-items: baseline; gap: 0.5rem; }
.feedSectionTitle { margin: 0; font-family: var(--font-ui); font-size: 0.98rem; font-weight: 500; }
.feedSectionCount { color: var(--text-faint); font-family: var(--font-ui); font-size: 0.86rem; }
.feedSectionLink { margin-left: auto; color: var(--text-muted); font-family: var(--font-ui); font-size: 0.84rem; background: none; border: none; cursor: pointer; }
.feedSectionLink:hover { color: var(--text-primary); }

.reviewCardGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 0.9rem; }

.reviewCard {
	display: flex;
	gap: 0.95rem;
	padding: 0.85rem;
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	box-shadow: var(--shadow-card);
	text-align: left;
	min-width: 0;
}

.posterThumb {
	width: 64px;
	aspect-ratio: 9 / 16;
	border-radius: 8px;
	object-fit: cover;
	flex: none;
	background: linear-gradient(160deg, #D8D2C6, #B9B1A0);
	border: none;
	display: block;
}

.posterThumbPlaceholder { display: grid; place-items: center; color: rgba(255, 255, 255, 0.85); }

.reviewCardBody { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.captionPreview {
	margin: 0.15rem 0 0;
	color: var(--text-muted);
	font-family: var(--font-ui);
	font-size: 0.82rem;
	line-height: 1.45;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	-webkit-box-orient: vertical;
	overflow: hidden;
}

.queueRow {
	display: flex;
	align-items: center;
	gap: 0.8rem;
	padding: 0.65rem 0.2rem;
	border-bottom: 1px solid var(--line);
	font-family: var(--font-ui);
	font-size: 0.9rem;
	color: var(--text-primary);
	min-width: 0;
}

.queueThumb { width: 32px; height: 32px; border-radius: 7px; object-fit: cover; flex: none; background: linear-gradient(135deg, #D8D2C6, #B9B1A0); }

.postedStrip { display: flex; gap: 0.7rem; overflow-x: auto; padding-bottom: 0.4rem; }
.postedCard { width: 76px; flex: none; background: none; border: none; padding: 0; cursor: pointer; text-align: left; }
.postedThumb { width: 76px; aspect-ratio: 9 / 16; border-radius: 8px; object-fit: cover; display: block; background: linear-gradient(160deg, #D8D2C6, #B9B1A0); }
.postedMeta { margin: 0.3rem 0 0; font-family: var(--font-ui); font-size: 0.78rem; color: var(--text-muted); line-height: 1.35; }

/* ============ NEW: Library ============ */
.tabPills { display: flex; gap: 0.4rem; align-items: center; }
.pill,
.pillActive {
	min-height: 34px;
	padding: 0.3rem 0.95rem;
	border: none;
	border-radius: 999px;
	font-family: var(--font-ui);
	font-size: 0.86rem;
	font-weight: 500;
	cursor: pointer;
	background: transparent;
	color: var(--text-muted);
	transition: color 140ms ease, background-color 140ms ease;
}
.pill:hover { color: var(--text-primary); }
.pillActive { background: var(--text-primary); color: var(--accent-contrast); }
.hiddenLink { margin-left: auto; background: none; border: none; color: var(--text-faint); font-family: var(--font-ui); font-size: 0.82rem; cursor: pointer; }
.hiddenLink:hover { color: var(--text-primary); }

.mediaGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.9rem; }

.mediaCard {
	border: 1px solid var(--line);
	border-radius: var(--radius-card);
	background: var(--surface-raised);
	box-shadow: var(--shadow-card);
	overflow: hidden;
	padding: 0;
	cursor: pointer;
	text-align: left;
	display: flex;
	flex-direction: column;
	transition: border-color 140ms ease;
	min-width: 0;
}
.mediaCard:hover { border-color: var(--line-strong); }

.mediaThumb { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; background: linear-gradient(160deg, #D8D2C6, #B9B1A0); }
.mediaThumbTall { aspect-ratio: 9 / 16; }
.mediaCardBody { padding: 0.7rem 0.85rem 0.85rem; display: flex; flex-direction: column; gap: 0.25rem; min-width: 0; }
.mediaTitle { margin: 0; font-family: var(--font-ui); font-size: 0.92rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mediaMeta { margin: 0; font-family: var(--font-ui); font-size: 0.8rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.4rem; }

.songRow {
	display: flex;
	align-items: center;
	gap: 0.9rem;
	padding: 0.75rem 0.2rem;
	border: none;
	border-bottom: 1px solid var(--line);
	background: transparent;
	width: 100%;
	text-align: left;
	cursor: pointer;
	font-family: inherit;
	color: var(--text-primary);
	min-width: 0;
}
.songRow:hover { background: var(--surface-sunk); }

.songArt {
	width: 40px;
	height: 40px;
	border-radius: 9px;
	flex: none;
	display: grid;
	place-items: center;
	color: rgba(255, 255, 255, 0.9);
	font-size: 0.95rem;
	background: linear-gradient(135deg, #C9BCA4, #A08D6C);
}

.uploadDrop { border-style: dashed; }

/* --- Responsive --- */
@media (max-width: 980px) {
	.header { flex-direction: column; align-items: flex-start; gap: 1.2rem; }
	.wide, .side { grid-column: 1 / -1; }
	.disclosureBody { grid-template-columns: 1fr; }
	.numberGrid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
	.page { gap: 1.5rem; }
	.panel, .detailPanel { padding: 1.1rem 1.1rem 1.2rem; }
	.toolbar, .cardActions { align-items: stretch; flex-direction: column; }
	.primaryButton, .secondaryButton, .ghostButton, .dangerButton { width: 100%; }
	.rangeGrid { grid-template-columns: 1fr; }
	.cropPreview { width: 100%; }
	.settingsRow { grid-template-columns: 1fr; gap: 0.35rem; }
	.reviewCardGrid { grid-template-columns: 1fr; }
	/* Sheets become bottom sheets on mobile. */
	.sheet {
		top: auto;
		left: 0;
		right: 0;
		width: 100%;
		max-height: 88dvh;
		border-left: none;
		border-top: 1px solid var(--line);
		border-radius: 14px 14px 0 0;
	}
}

@media (prefers-reduced-motion: reduce) {
	.progressFill { transition: none; }
	.disclosureCaret, .selectChevron { transition: none; }
	.skeleton, .spinner { animation: none; }
}

/* --- Text-overflow utilities --- */
.truncate { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.breakAny { min-width: 0; overflow-wrap: anywhere; }
```

- [ ] **Step 2: Lint + build + visual pass**

Run (from `web/`): `npm run lint` then `npm run build`
Expected: pass. In `npm run dev`, walk `/dashboard/new-edit`, `/dashboard/assets`, `/dashboard/publish`, `/dashboard/autopilot`, `/dashboard/synthesis`, `/dashboard/settings`: everything is light, sentence-case, rounded; no uppercase labels anywhere; no console errors. Compare feel against `system-design.html` mockup.

- [ ] **Step 3: Grep the bans**

Run (from `web/`): `grep -n "text-transform: uppercase\|letter-spacing: 0\." src/app/dashboard/studio.module.css`
Expected: no matches (negative letter-spacing like `-0.015em` is fine and won't match this pattern).

- [ ] **Step 4: Commit**

```bash
git add web/src/app/dashboard/studio.module.css
git commit -m "feat(dashboard): restyle every component class to Ivory & Ink"
```

---

### Task 7: Frontend — feedback primitives, poster plumbing, ETA extraction

**Files:**
- Modify: `web/src/services/eclypteApi.ts:75-89` (AssetSummary type)
- Modify: `web/src/app/dashboard/dashboardCommon.tsx` (append `Spinner`, `ProgressRow`, `Sheet`, `ToastProvider`/`useToast`)
- Create: `web/src/app/dashboard/editEta.ts` (moved from new-edit)
- Create: `web/src/app/dashboard/posterUrls.ts`
- Modify: `web/src/app/dashboard/new-edit/page.tsx` (delete the moved block, import from `./editEta` — wait, path is `../editEta` from inside `new-edit/`)

**Interfaces:**
- Consumes: Task 6 CSS classes; existing `EclypteApiClient.getDownloadUrl(ref)`.
- Produces:
  - `AssetSummary.poster: FileVersionInput | null` (TS mirror of Task 1)
  - `Spinner({ onInk?: boolean })`
  - `ProgressRow({ title: ReactNode; stageText: string; percent: number | null; error?: string | null })` — spinner + title left, stage sentence right, bar only when `percent !== null`
  - `Sheet({ open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode })` — Escape closes, body scroll locked, focus moves to panel
  - `ToastProvider({ children })` + `useToast(): (text: string, tone?: "ok" | "err") => void`
  - `editEta.ts` exports: `EDIT_STAGE_WEIGHTS: Record<string, number>`, `useNow(active: boolean): number`, `useRenderEta(job: EditJobStatus, isActive: boolean, nowMs: number): number | null`
  - `posterUrls.ts` exports: `posterKey(ref: FileVersionInput): string` and `usePosterUrls(api: EclypteApiClient | null, refs: (FileVersionInput | null | undefined)[]): Record<string, string>`

- [ ] **Step 1: Mirror the poster field** — in `web/src/services/eclypteApi.ts`, add to `AssetSummary` after `analysis`:

```ts
    poster: FileVersionInput | null
```

- [ ] **Step 2: Append primitives to `dashboardCommon.tsx`** (file already imports `styles`, `useCallback`, `useEffect`, `useRef`, `useState`, `ReactNode`; add `createContext`, `useContext` to the react import and `X` to the lucide import):

```tsx
export function Spinner({ onInk = false }: { onInk?: boolean }) {
    return (
        <span
            className={`${styles.spinner} ${onInk ? styles.spinnerOnInk : ""}`}
            role="status"
            aria-label="Working"
        />
    )
}

// Long-running work: spinner + name on the left, human stage sentence + number on
// the right, a real bar underneath whenever a percentage exists (feedback tier 3).
export function ProgressRow({
    title,
    stageText,
    percent,
    error,
}: {
    title: ReactNode
    stageText: string
    percent: number | null
    error?: string | null
}) {
    return (
        <div className={styles.progressRow}>
            <div className={styles.progressRowTop}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                    {!error && <Spinner />}
                    <span className={styles.truncate}>{title}</span>
                </span>
                <span>{stageText}</span>
            </div>
            {percent !== null && !error && (
                <div className={styles.progressTrack}>
                    <div className={styles.progressFill} style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
                </div>
            )}
            {error && <p className={styles.smallText}>{error}</p>}
        </div>
    )
}

// The single modal pattern: right slide-over on desktop, bottom sheet on mobile
// (media query in studio.module.css). Escape closes; body scroll is locked.
export function Sheet({
    open,
    title,
    onClose,
    children,
    footer,
}: {
    open: boolean
    title: string
    onClose: () => void
    children: ReactNode
    footer?: ReactNode
}) {
    const panelRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (!open) {
            return
        }
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                onClose()
            }
        }
        document.addEventListener("keydown", onKey)
        const previousOverflow = document.body.style.overflow
        document.body.style.overflow = "hidden"
        panelRef.current?.focus()
        return () => {
            document.removeEventListener("keydown", onKey)
            document.body.style.overflow = previousOverflow
        }
    }, [open, onClose])
    if (!open) {
        return null
    }
    return (
        <>
            <button type="button" className={styles.sheetOverlay} aria-label="Close" onClick={onClose} />
            <div className={styles.sheet} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panelRef}>
                <div className={styles.sheetHeader}>
                    <h2 className={styles.sheetTitle}>{title}</h2>
                    <button type="button" className={styles.ghostButton} onClick={onClose}>
                        <X size={16} /> Close
                    </button>
                </div>
                <div className={styles.sheetBody}>{children}</div>
                {footer && <div className={styles.sheetFooter}>{footer}</div>}
            </div>
        </>
    )
}

// Quiet confirmations (feedback tiers 1-2). Mount ToastProvider once in the
// dashboard layout; pages call useToast()("Posted to Instagram").
type ToastItem = { id: number; text: string; tone: "ok" | "err" }

const ToastContext = createContext<(text: string, tone?: "ok" | "err") => void>(() => undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<ToastItem[]>([])
    const idRef = useRef(0)
    const push = useCallback((text: string, tone: "ok" | "err" = "ok") => {
        const id = ++idRef.current
        setToasts((current) => [...current, { id, text, tone }])
        setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 3500)
    }, [])
    return (
        <ToastContext.Provider value={push}>
            {children}
            <div className={styles.toastStack} role="status" aria-live="polite">
                {toasts.map((toast) => (
                    <div key={toast.id} className={styles.toast}>
                        <span className={toast.tone === "ok" ? styles.toastOk : styles.toastErr}>
                            {toast.tone === "ok" ? "✓" : "!"}
                        </span>
                        {toast.text}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    )
}

export function useToast() {
    return useContext(ToastContext)
}
```

- [ ] **Step 3: Extract the ETA machinery.** Create `web/src/app/dashboard/editEta.ts` by MOVING (verbatim, no rewrites) from `web/src/app/dashboard/new-edit/page.tsx`:
  - the `EDIT_STAGE_WEIGHTS` constant and the `ETA_DEFAULT_TOTAL_SEC` / `ETA_MIN_CALIBRATION_SEC` / `ETA_LOCAL_RATE_MIN_PCT` / `ETA_SMOOTHING` constants (lines ~25-36),
  - the `useNow` hook (lines ~770-783),
  - `type StageTiming`, `estimateRemainingSec`, `type EtaState`, `emptyEtaState`, `stageSignature`, `nextEtaState`, `useRenderEta` (lines ~785-905 — copy through the end of `useRenderEta`).

  Add at the top of the new file: `import { useEffect, useState } from "react"` and `import type { EditJobStatus, EditJobStage } from "@/services/eclypteApi"`. Export `EDIT_STAGE_WEIGHTS`, `useNow`, and `useRenderEta` (the rest stay module-private). In `new-edit/page.tsx`, delete the moved code and add `import { EDIT_STAGE_WEIGHTS, useNow, useRenderEta } from "../editEta"`. If anything else in new-edit references a moved private helper (search for `stageSignature`, `estimateRemainingSec` uses), export that too rather than duplicating.

- [ ] **Step 4: Create `web/src/app/dashboard/posterUrls.ts`:**

```ts
import { useEffect, useRef, useState } from "react"
import type { EclypteApiClient, FileVersionInput } from "@/services/eclypteApi"

export function posterKey(ref: FileVersionInput) {
    return `${ref.file_id}:${ref.version_id}`
}

// Resolves signed URLs for poster refs, once per ref. Signed URLs are never
// cached across sessions (they expire); within the page a fetched URL is kept
// for the component's lifetime, which is comfortably inside the expiry window.
export function usePosterUrls(
    api: EclypteApiClient | null,
    refs: (FileVersionInput | null | undefined)[],
): Record<string, string> {
    const [urls, setUrls] = useState<Record<string, string>>({})
    const inFlightRef = useRef<Set<string>>(new Set())
    const wanted = refs.filter((ref): ref is FileVersionInput => Boolean(ref)).map(posterKey).sort().join("|")

    useEffect(() => {
        if (!api || wanted === "") {
            return
        }
        let cancelled = false
        for (const key of wanted.split("|")) {
            if (urls[key] || inFlightRef.current.has(key)) {
                continue
            }
            inFlightRef.current.add(key)
            const [file_id, version_id] = key.split(":")
            void api
                .getDownloadUrl({ file_id, version_id })
                .then((download) => {
                    if (!cancelled) {
                        setUrls((current) => ({ ...current, [key]: download.download_url }))
                    }
                })
                .catch(() => undefined) // decorative — a missing thumb falls back to the gradient tile
                .finally(() => {
                    inFlightRef.current.delete(key)
                })
        }
        return () => {
            cancelled = true
        }
        // `urls` intentionally omitted: re-running on every resolved URL would refetch nothing
        // (guards above) but churn the effect; `wanted` captures the actual input identity.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [api, wanted])

    return urls
}
```

- [ ] **Step 5: Lint + build** (from `web/`): `npm run lint && npm run build` → PASS (new-edit compiles against `../editEta`).

- [ ] **Step 6: Commit**

```bash
git add web/src/services/eclypteApi.ts web/src/app/dashboard/dashboardCommon.tsx web/src/app/dashboard/editEta.ts web/src/app/dashboard/posterUrls.ts web/src/app/dashboard/new-edit/page.tsx
git commit -m "feat(dashboard): feedback primitives (spinner/progress/sheet/toast) + poster plumbing"
```

---

### Task 8: Frontend — the pipeline Home at `/dashboard`

`/dashboard/page.tsx` (today a redirect to new-edit) becomes the Home feed. The old autopilot/publish pages keep working until Task 9 redirects them, so every commit stays shippable. Build against the `home-design.html` mockup.

**Files:**
- Rewrite: `web/src/app/dashboard/page.tsx`

**Interfaces:**
- Consumes: `useAutopilot`, `usePublishingPosts`, `useEditJobs`, `useAssets` (stores), `useRunStream`, Task 7 primitives + `usePosterUrls`/`posterKey` + `useRenderEta`/`useNow`, `Select`, helpers from `dashboardCommon` (`formatClock`, `formatDate`, `formatDuration`, `humanizeStageDetail`, `errorMessage`, `statusLabel`), API client methods: `updateAutopilot`, `addAutopilotItems`, `removeAutopilotItem`, `triggerAutopilotTick`, `updatePublishingPost`, `sendPublishingPostToBuffer`, `regeneratePublishingCaption`, `cancelPublishingPost`, `refreshPublishingPostStatus`, `markPublishingPostPosted`, `getRun`, `getDownloadUrl`.
- Produces: the page. **Behavior contracts preserved from the old publish page (do not drop):** ~25s Buffer reconciliation poll + visibilitychange refresh over pollable posts (`buffer_post_id` set AND status queued/scheduled/published-without-url), silent background errors, editor dirty-guard keyed by `post_id` (`syncedPostIdRef`), preview fetched once per `render_file_id:render_version_id` (`previewKeyRef`), save-before-send, manual re-check surfacing errors, mark-as-posted override.

- [ ] **Step 1: Write the page.** Replace `web/src/app/dashboard/page.tsx` with:

```tsx
"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import Link from "next/link"
import { Play, Plus, RefreshCw, Zap } from "lucide-react"
import {
    DashboardPage,
    ProgressRow,
    Select,
    Sheet,
    SkeletonList,
    Spinner,
    errorMessage,
    formatClock,
    formatDate,
    humanizeStageDetail,
    useToast,
} from "./dashboardCommon"
import styles from "./studio.module.css"
import { useRunStream } from "./useRunStream"
import { useNow, useRenderEta } from "./editEta"
import { posterKey, usePosterUrls } from "./posterUrls"
import {
    AssetSummary,
    AutopilotItem,
    EclypteApiClient,
    EditJobStatus,
    FileVersionInput,
    PublishingPost,
    RunStreamMessage,
} from "@/services/eclypteApi"
import { useAssets, useAutopilot, useEditJobs, usePublishingPosts } from "@/stores/dashboardResources"

const POLL_INTERVAL_MS = 25000
const POSTED_STRIP_LIMIT = 10

export default function HomePage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const toast = useToast()
    const [error, setError] = useState<string | null>(null)
    const [reviewPostId, setReviewPostId] = useState<string | null>(null)
    const [composerOpen, setComposerOpen] = useState(false)
    const [isTicking, setIsTicking] = useState(false)
    const pollableIdsRef = useRef<string[]>([])

    const api = useMemo(() => (user?.id ? new EclypteApiClient({ userId: user.id }) : null), [user?.id])
    const autopilotResource = useAutopilot(api)
    const autopilot = autopilotResource.data ?? null
    const setAutopilot = autopilotResource.set
    const postsResource = usePublishingPosts(api, { status: "all" })
    const posts = useMemo(() => postsResource.data ?? [], [postsResource.data])
    const setPosts = postsResource.set
    const jobsResource = useEditJobs(api)
    const jobs = useMemo(() => jobsResource.data ?? [], [jobsResource.data])
    const assetsResource = useAssets(api, { includeArchived: true })
    const assets = useMemo(() => assetsResource.data ?? [], [assetsResource.data])

    const readyPosts = useMemo(() => posts.filter((post) => post.status === "ready" || post.status === "draft"), [posts])
    const postedPosts = useMemo(
        () =>
            posts
                .filter((post) => post.status === "published" || post.status === "queued" || post.status === "scheduled")
                .slice(0, POSTED_STRIP_LIMIT),
        [posts],
    )
    const workingItems = useMemo(
        () => (autopilot?.items ?? []).filter((item) => ["importing", "analyzing", "editing"].includes(item.status)),
        [autopilot],
    )
    const pendingItems = useMemo(() => (autopilot?.items ?? []).filter((item) => item.status === "pending"), [autopilot])
    const failedItems = useMemo(() => (autopilot?.items ?? []).filter((item) => item.status === "failed"), [autopilot])

    const revalidateAll = useMemo(() => {
        const a = autopilotResource.revalidate
        const p = postsResource.revalidate
        const j = jobsResource.revalidate
        return () => {
            a()
            p()
            j()
        }
    }, [autopilotResource.revalidate, postsResource.revalidate, jobsResource.revalidate])

    useRunStream({
        api,
        enabled: workingItems.length > 0,
        shouldRefresh: isPipelineRunUpdate,
        refresh: revalidateAll,
    })

    // --- Poster refs: publishing posts carry the MP4 ref; the poster ref lives on the
    // post's source run outputs (render_poster_*). Fetched once per post, cached here.
    const [postPosterRefs, setPostPosterRefs] = useState<Record<string, FileVersionInput | null>>({})
    useEffect(() => {
        if (!api) {
            return
        }
        let cancelled = false
        const wanted = [...readyPosts, ...postedPosts].filter(
            (post) => post.source_run_id && postPosterRefs[post.post_id] === undefined,
        )
        for (const post of wanted) {
            void api
                .getRun(post.source_run_id as string)
                .then((run) => {
                    if (cancelled) {
                        return
                    }
                    const fileId = run.outputs["render_poster_file_id"]
                    const versionId = run.outputs["render_poster_version_id"]
                    setPostPosterRefs((current) => ({
                        ...current,
                        [post.post_id]: fileId && versionId ? { file_id: fileId, version_id: versionId } : null,
                    }))
                })
                .catch(() => {
                    if (!cancelled) {
                        setPostPosterRefs((current) => ({ ...current, [post.post_id]: null }))
                    }
                })
        }
        return () => {
            cancelled = true
        }
    }, [api, readyPosts, postedPosts, postPosterRefs])

    const assetById = useMemo(() => new Map(assets.map((asset) => [asset.file_id, asset])), [assets])
    const queueSourceRefs = useMemo(
        () => pendingItems.map((item) => assetById.get(item.source_video_file_id)?.poster ?? null),
        [pendingItems, assetById],
    )
    const posterUrls = usePosterUrls(api, [
        ...Object.values(postPosterRefs),
        ...queueSourceRefs,
    ])

    // --- Buffer reconciliation (ported behavior contract from the publish page).
    const pollablePosts = useMemo(
        () =>
            posts.filter(
                (post) =>
                    Boolean(post.buffer_post_id)
                    && (post.status === "queued" || post.status === "scheduled" || (post.status === "published" && !post.post_url)),
            ),
        [posts],
    )
    const hasPollable = pollablePosts.length > 0
    useEffect(() => {
        pollableIdsRef.current = pollablePosts.map((post) => post.post_id)
    })
    useEffect(() => {
        if (!api || !hasPollable) {
            return
        }
        const controller = new AbortController()
        let stopped = false
        const reconcile = async () => {
            if (document.visibilityState === "hidden") {
                return
            }
            for (const postId of pollableIdsRef.current) {
                try {
                    const next = await api.refreshPublishingPostStatus(postId, controller.signal)
                    if (stopped) {
                        return
                    }
                    setPosts((current = []) => current.map((post) => (post.post_id === next.post_id ? next : post)))
                } catch {
                    // Silent: background reconciliation must never clobber the UI.
                }
            }
        }
        const interval = window.setInterval(reconcile, POLL_INTERVAL_MS)
        const onVisible = () => {
            if (document.visibilityState === "visible") {
                void reconcile()
            }
        }
        document.addEventListener("visibilitychange", onVisible)
        return () => {
            stopped = true
            controller.abort()
            window.clearInterval(interval)
            document.removeEventListener("visibilitychange", onVisible)
        }
    }, [api, hasPollable, setPosts])

    const replacePost = (next: PublishingPost) => {
        setPosts((current = []) => current.map((post) => (post.post_id === next.post_id ? next : post)))
    }

    const updateSettings = async (input: { enabled?: boolean; dailyTarget?: number; clearHalt?: boolean }) => {
        if (!api) {
            return
        }
        setError(null)
        try {
            setAutopilot(await api.updateAutopilot(input))
        } catch (caught) {
            toast(errorMessage(caught), "err")
        }
    }

    const runTick = async () => {
        if (!api) {
            return
        }
        setIsTicking(true)
        setError(null)
        try {
            setAutopilot(await api.triggerAutopilotTick())
            toast("Checked the queue")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsTicking(false)
        }
    }

    const removeItem = async (itemId: string) => {
        if (!api) {
            return
        }
        try {
            setAutopilot(await api.removeAutopilotItem(itemId))
        } catch (caught) {
            toast(errorMessage(caught), "err")
        }
    }

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Home" title="Today">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Home" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to see your reels.</div>
            </DashboardPage>
        )
    }

    const reviewPost = reviewPostId ? posts.find((post) => post.post_id === reviewPostId) ?? null : null
    const madeToday = autopilot?.packaged_today ?? 0
    const target = autopilot?.daily_target ?? 3

    return (
        <DashboardPage
            eyebrow={formatDate(new Date().toISOString())}
            title="Today"
            action={
                <button className={styles.primaryButton} type="button" onClick={() => setComposerOpen(true)}>
                    <Plus size={16} /> New reel
                </button>
            }
        >
            <div className={styles.statusLine}>
                <span className={autopilot?.enabled ? styles.statusOnDot : styles.statusOffDot} aria-hidden />
                {autopilot?.enabled
                    ? `Autopilot is on · ${madeToday} of ${target} reels made today`
                    : "Autopilot is paused"}
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem", marginLeft: "auto" }}>
                    Daily goal
                    <Select
                        compact
                        ariaLabel="Daily goal"
                        value={String(target)}
                        onChange={(next) => updateSettings({ dailyTarget: Number(next) })}
                        options={Array.from({ length: 10 }, (_, index) => ({
                            value: String(index + 1),
                            label: `${index + 1} per day`,
                        }))}
                    />
                    <button
                        type="button"
                        className={`${styles.switchButton} ${autopilot?.enabled ? styles.switchButtonOn : ""}`}
                        role="switch"
                        aria-checked={Boolean(autopilot?.enabled)}
                        aria-label={autopilot?.enabled ? "Pause autopilot" : "Turn autopilot on"}
                        onClick={() => updateSettings({ enabled: !autopilot?.enabled })}
                    />
                    {!autopilot?.loop_configured && (
                        <button className={styles.ghostButton} type="button" onClick={runTick} disabled={isTicking}>
                            {isTicking ? <Spinner /> : <Zap size={15} />} Run now
                        </button>
                    )}
                </span>
            </div>

            {autopilot?.halted_reason && (
                <div className={styles.topBanner}>
                    <span className={styles.breakAny}>Autopilot paused itself: {autopilot.halted_reason}</span>
                    <button
                        className={`${styles.secondaryButton} ${styles.haltClearButton}`}
                        type="button"
                        onClick={() => updateSettings({ clearHalt: true })}
                    >
                        <Play size={15} /> Resume
                    </button>
                </div>
            )}
            {(error || autopilotResource.error || postsResource.error) && (
                <div className={styles.errorBanner}>{error || autopilotResource.error || postsResource.error}</div>
            )}

            {/* Ready for you */}
            <section className={styles.feedSection}>
                <div className={styles.feedSectionHead}>
                    <h2 className={styles.feedSectionTitle}>Ready for you</h2>
                    <span className={styles.feedSectionCount}>{readyPosts.length}</span>
                </div>
                {readyPosts.length === 0 ? (
                    <p className={styles.smallText}>
                        Nothing to review right now — new reels land here when they&apos;re done.
                    </p>
                ) : (
                    <div className={styles.reviewCardGrid}>
                        {readyPosts.map((post) => {
                            const ref = postPosterRefs[post.post_id]
                            const url = ref ? posterUrls[posterKey(ref)] : undefined
                            return (
                                <div key={post.post_id} className={styles.reviewCard}>
                                    {url ? (
                                        <img className={styles.posterThumb} src={url} alt="" />
                                    ) : (
                                        <span className={`${styles.posterThumb} ${styles.posterThumbPlaceholder}`} aria-hidden>▶</span>
                                    )}
                                    <div className={styles.reviewCardBody}>
                                        <h3 style={{ margin: 0 }} className={styles.truncate}>{postTitle(post)}</h3>
                                        <p className={styles.smallText} style={{ margin: 0 }}>
                                            made {formatDate(post.created_at)}
                                            {post.auto_created ? " · by autopilot" : ""}
                                        </p>
                                        <p className={styles.captionPreview}>{post.caption} {post.hashtags.join(" ")}</p>
                                        <div className={styles.cardActions}>
                                            <button className={styles.primaryButton} type="button" onClick={() => setReviewPostId(post.post_id)}>
                                                Review &amp; post
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>

            {/* In the works */}
            {(workingItems.length > 0 || failedItems.length > 0) && (
                <section className={styles.feedSection}>
                    <div className={styles.feedSectionHead}>
                        <h2 className={styles.feedSectionTitle}>In the works</h2>
                        <span className={styles.feedSectionCount}>{workingItems.length}</span>
                    </div>
                    {workingItems.map((item) => (
                        <WorkingRow key={item.item_id} item={item} jobs={jobs} assets={assetById} />
                    ))}
                    {failedItems.map((item) => (
                        <ProgressRow
                            key={item.item_id}
                            title={itemTitle(item, assetById)}
                            stageText="Didn't work"
                            percent={null}
                            error={item.last_error ?? "Something went wrong — remove it below and try again."}
                        />
                    ))}
                </section>
            )}

            {/* Up next */}
            <section className={styles.feedSection}>
                <div className={styles.feedSectionHead}>
                    <h2 className={styles.feedSectionTitle}>Up next</h2>
                    <span className={styles.feedSectionCount}>{pendingItems.length + failedItems.length}</span>
                </div>
                {pendingItems.length === 0 && failedItems.length === 0 ? (
                    <p className={styles.smallText}>The queue is empty — add a film and a song with “New reel”.</p>
                ) : (
                    <div>
                        {[...pendingItems, ...failedItems].map((item) => {
                            const asset = assetById.get(item.source_video_file_id)
                            const ref = asset?.poster ?? null
                            const url = ref ? posterUrls[posterKey(ref)] : undefined
                            return (
                                <div key={item.item_id} className={styles.queueRow}>
                                    {url ? (
                                        <img className={styles.queueThumb} src={url} alt="" />
                                    ) : (
                                        <span className={styles.queueThumb} aria-hidden />
                                    )}
                                    <span className={styles.truncate}>{itemTitle(item, assetById)}</span>
                                    <span style={{ marginLeft: "auto", display: "inline-flex", gap: "0.6rem", alignItems: "center" }}>
                                        {item.status === "failed" && <span className={styles.smallText} style={{ margin: 0, color: "var(--danger)" }}>didn&apos;t work</span>}
                                        <button className={styles.ghostButton} type="button" onClick={() => removeItem(item.item_id)}>
                                            Remove
                                        </button>
                                    </span>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>

            {/* Posted */}
            <section className={styles.feedSection}>
                <div className={styles.feedSectionHead}>
                    <h2 className={styles.feedSectionTitle}>Posted</h2>
                    <span className={styles.feedSectionCount}>recent</span>
                    <Link className={styles.feedSectionLink} href="/dashboard/assets?tab=reels">
                        See all
                    </Link>
                </div>
                {postedPosts.length === 0 ? (
                    <p className={styles.smallText}>Reels you approve show up here once they&apos;re queued or live.</p>
                ) : (
                    <div className={styles.postedStrip}>
                        {postedPosts.map((post) => {
                            const ref = postPosterRefs[post.post_id]
                            const url = ref ? posterUrls[posterKey(ref)] : undefined
                            return (
                                <button key={post.post_id} type="button" className={styles.postedCard} onClick={() => setReviewPostId(post.post_id)}>
                                    {url ? (
                                        <img className={styles.postedThumb} src={url} alt={postTitle(post)} />
                                    ) : (
                                        <span className={styles.postedThumb} aria-hidden />
                                    )}
                                    <p className={styles.postedMeta}>{postedLabel(post)}</p>
                                </button>
                            )
                        })}
                    </div>
                )}
            </section>

            {reviewPost && api && (
                <ReviewSheet
                    api={api}
                    post={reviewPost}
                    posterUrl={(() => {
                        const ref = postPosterRefs[reviewPost.post_id]
                        return ref ? posterUrls[posterKey(ref)] : undefined
                    })()}
                    onClose={() => setReviewPostId(null)}
                    replacePost={replacePost}
                    onError={setError}
                />
            )}
            {api && (
                <ComposerSheet
                    api={api}
                    open={composerOpen}
                    assets={assets}
                    posterUrls={posterUrls}
                    onClose={() => setComposerOpen(false)}
                    onQueued={(next) => {
                        setAutopilot(next)
                        setComposerOpen(false)
                        toast("Added to the queue")
                    }}
                />
            )}
        </DashboardPage>
    )
}

function isPipelineRunUpdate(message: RunStreamMessage) {
    return (
        message.type === "run_manifest"
        && (message.run.workflow_type === "edit_pipeline"
            || message.run.workflow_type === "youtube_song_import"
            || message.run.workflow_type === "music_analysis")
    )
}

function postTitle(post: PublishingPost) {
    if (post.source_name && post.song_name) {
        return `${post.source_name} × ${post.song_name}`
    }
    return post.render_display_name
}

function postedLabel(post: PublishingPost) {
    if (post.status === "published") {
        return `${formatDate(post.posted_at ?? post.updated_at)} · on Instagram`
    }
    if (post.status === "scheduled") {
        return `scheduled ${post.scheduled_at ? formatDate(post.scheduled_at) : ""}`
    }
    return "queued"
}

function itemTitle(item: AutopilotItem, assetById: Map<string, AssetSummary>) {
    const video = assetById.get(item.source_video_file_id)?.display_name ?? "Video"
    const song = item.song_file_id
        ? assetById.get(item.song_file_id)?.display_name ?? "Song"
        : item.song_youtube_url ?? "Song"
    return `${stripExtension(video)} × ${stripExtension(song)}`
}

export function stripExtension(name: string) {
    return name.replace(/\.(mp4|wav|mp3|m4a|aac|flac|ogg|opus|aiff|wma|jpg|jpeg|json)$/i, "")
}

// One row per in-flight autopilot item. Editing items have a real edit run —
// show its live percent + ETA; importing/analyzing show the stage sentence.
function WorkingRow({ item, jobs, assets }: { item: AutopilotItem; jobs: EditJobStatus[]; assets: Map<string, AssetSummary> }) {
    const job = item.edit_run_id ? jobs.find((candidate) => candidate.run_id === item.edit_run_id) ?? null : null
    const title = itemTitle(item, assets)
    if (item.status === "editing" && job) {
        return <EditingRow title={title} job={job} item={item} />
    }
    const stageText = item.status === "importing" ? "Getting the song…" : "Listening to the song…"
    return <ProgressRow title={title} stageText={stageText} percent={null} />
}

function EditingRow({ title, job, item }: { title: string; job: EditJobStatus; item: AutopilotItem }) {
    const isActive = job.status === "running" || job.status === "created" || job.status === "blocked"
    const now = useNow(isActive)
    const etaSec = useRenderEta(job, isActive, now)
    const stage = job.stages.find((candidate) => candidate.status === "running") ?? null
    const window =
        item.audio_start_sec !== null && item.audio_end_sec !== null
            ? ` · cutting ${formatClock(item.audio_start_sec)}–${formatClock(item.audio_end_sec)}`
            : ""
    const eta = etaSec !== null ? ` · about ${Math.max(1, Math.round(etaSec))}s left` : ""
    return (
        <ProgressRow
            title={`${title}${window}`}
            stageText={`${humanizeStageDetail(stage?.detail, stage?.id ?? job.status)} · ${job.progress_percent}%${eta}`}
            percent={job.progress_percent}
        />
    )
}
```

- [ ] **Step 2: Add the ReviewSheet and ComposerSheet** to the same file (below the helpers). The behavior comes from the old publish page verbatim where noted:

```tsx
function ReviewSheet({
    api,
    post,
    posterUrl,
    onClose,
    replacePost,
    onError,
}: {
    api: EclypteApiClient
    post: PublishingPost
    posterUrl?: string
    onClose: () => void
    replacePost: (next: PublishingPost) => void
    onError: (message: string | null) => void
}) {
    const toast = useToast()
    const [caption, setCaption] = useState("")
    const [hashtags, setHashtags] = useState("")
    const [scheduledAt, setScheduledAt] = useState("")
    const [videoUrl, setVideoUrl] = useState<string | null>(null)
    const [playing, setPlaying] = useState(false)
    const [busy, setBusy] = useState<string | null>(null) // which action is running
    const syncedPostIdRef = useRef<string | null>(null)
    const previewKeyRef = useRef<string | null>(null)

    // Dirty-guard (ported): reseed the editor only when the DISPLAYED post changes,
    // never when a background poll swaps the same post's object.
    useEffect(() => {
        if (post.post_id === syncedPostIdRef.current) {
            return
        }
        syncedPostIdRef.current = post.post_id
        setCaption(post.caption)
        setHashtags(post.hashtags.join(" "))
        setScheduledAt(toLocalDateTimeInput(post.scheduled_at))
        setPlaying(false)
    }, [post])

    // Preview URL fetched once per rendered media (ported previewKeyRef contract).
    useEffect(() => {
        const key = `${post.render_file_id}:${post.render_version_id}`
        if (key === previewKeyRef.current) {
            return
        }
        previewKeyRef.current = key
        setVideoUrl(null)
        let ignore = false
        void api
            .getDownloadUrl({ file_id: post.render_file_id, version_id: post.render_version_id })
            .then((download) => {
                if (!ignore) {
                    setVideoUrl(download.download_url)
                }
            })
            .catch((caught) => onError(errorMessage(caught)))
        return () => {
            ignore = true
        }
    }, [api, post.render_file_id, post.render_version_id, onError])

    const saveCurrent = async () => {
        const next = await api.updatePublishingPost(post.post_id, {
            caption,
            hashtags: hashtags.split(/\s+/).map((tag) => tag.trim()).filter(Boolean),
            notes: post.notes,
            scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
        })
        replacePost(next)
        return next
    }

    const act = async (name: string, action: () => Promise<void>) => {
        setBusy(name)
        onError(null)
        try {
            await action()
        } catch (caught) {
            onError(errorMessage(caught))
        } finally {
            setBusy(null)
        }
    }

    const send = (mode: "queue" | "schedule" | "now") =>
        act(mode, async () => {
            if (mode === "schedule" && !scheduledAt) {
                throw new Error("Choose a time first.")
            }
            const saved = await saveCurrent()
            const sent = await api.sendPublishingPostToBuffer(saved.post_id, {
                mode,
                scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
            })
            replacePost(sent)
            toast(mode === "now" ? "Posting to Instagram" : mode === "queue" ? "Added to the posting queue" : "Scheduled")
            onClose()
        })

    const rewrite = () =>
        act("rewrite", async () => {
            const next = await api.regeneratePublishingCaption(post.post_id)
            replacePost(next)
            setCaption(next.caption)
            setHashtags(next.hashtags.join(" "))
        })

    const canSend = post.status === "ready" || post.status === "draft" || post.status === "failed"
    const inFlight = post.status === "queued" || post.status === "scheduled"

    return (
        <Sheet
            open
            title={postTitle(post)}
            onClose={onClose}
            footer={
                canSend ? (
                    <>
                        <button className={styles.primaryButton} type="button" onClick={() => send("now")} disabled={busy !== null}>
                            {busy === "now" ? <Spinner onInk /> : null} Post now
                        </button>
                        <button className={styles.secondaryButton} type="button" onClick={() => send("schedule")} disabled={busy !== null}>
                            {busy === "schedule" ? <Spinner /> : null} Schedule
                        </button>
                        <button className={styles.secondaryButton} type="button" onClick={() => send("queue")} disabled={busy !== null}>
                            {busy === "queue" ? <Spinner /> : null} Add to queue
                        </button>
                        <span className={styles.sheetActionsRight}>
                            <button
                                className={styles.dangerButton}
                                type="button"
                                onClick={() => act("skip", async () => {
                                    replacePost(await api.cancelPublishingPost(post.post_id))
                                    toast("Skipped")
                                    onClose()
                                })}
                                disabled={busy !== null}
                            >
                                {busy === "skip" ? <Spinner /> : null} Skip this reel
                            </button>
                        </span>
                    </>
                ) : (
                    <>
                        {post.buffer_post_id && (
                            <button
                                className={styles.secondaryButton}
                                type="button"
                                onClick={() => act("recheck", async () => {
                                    replacePost(await api.refreshPublishingPostStatus(post.post_id))
                                    toast("Checked with Instagram")
                                })}
                                disabled={busy !== null}
                            >
                                {busy === "recheck" ? <Spinner /> : <RefreshCw size={15} />} Re-check status
                            </button>
                        )}
                        {inFlight && (
                            <button
                                className={styles.secondaryButton}
                                type="button"
                                onClick={() => act("mark", async () => {
                                    replacePost(await api.markPublishingPostPosted(post.post_id))
                                    toast("Marked as posted")
                                })}
                                disabled={busy !== null}
                            >
                                {busy === "mark" ? <Spinner /> : null} Mark as posted
                            </button>
                        )}
                        {post.post_url && (
                            <a className={styles.detailLink} href={post.post_url} target="_blank" rel="noreferrer">
                                Open on Instagram
                            </a>
                        )}
                    </>
                )
            }
        >
            {playing && videoUrl ? (
                <video className={styles.previewMedia} controls autoPlay src={videoUrl} style={{ maxWidth: 260 }} />
            ) : (
                <button type="button" className={styles.posterButton} style={{ width: 160 }} onClick={() => setPlaying(true)} disabled={!videoUrl}>
                    {posterUrl ? (
                        <img className={styles.posterThumb} style={{ width: 160 }} src={posterUrl} alt="" />
                    ) : (
                        <span className={`${styles.posterThumb} ${styles.posterThumbPlaceholder}`} style={{ width: 160 }} aria-hidden />
                    )}
                    <span className={styles.posterPlayIcon}>{videoUrl ? "▶" : <Spinner />}</span>
                </button>
            )}
            {canSend ? (
                <>
                    <label className={styles.fieldLabel}>
                        <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            Caption
                            <button className={styles.ghostButton} type="button" onClick={rewrite} disabled={busy !== null} style={{ minHeight: 0, padding: "0.2rem 0.4rem" }}>
                                {busy === "rewrite" ? <Spinner /> : "↺"} Rewrite
                            </button>
                        </span>
                        <textarea className={styles.textarea} value={caption} onChange={(event) => setCaption(event.target.value)} />
                    </label>
                    <label className={styles.fieldLabel}>
                        Hashtags
                        <input className={styles.input} value={hashtags} onChange={(event) => setHashtags(event.target.value)} />
                    </label>
                    <label className={styles.fieldLabel}>
                        Schedule for (optional)
                        <input className={styles.input} type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
                    </label>
                    <p className={styles.smallText}>Posts to Instagram as a Reel.</p>
                </>
            ) : (
                <>
                    <p className={styles.proseText}>{post.caption}</p>
                    <p className={styles.smallText}>{post.hashtags.join(" ")}</p>
                    <p className={styles.smallText}>{postedLabel(post)}</p>
                </>
            )}
            {post.last_error && <div className={styles.errorBanner}>{post.last_error}</div>}
        </Sheet>
    )
}

function toLocalDateTimeInput(value: string | null) {
    if (!value) {
        return ""
    }
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
        return ""
    }
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    return local.toISOString().slice(0, 16)
}

function ComposerSheet({
    api,
    open,
    assets,
    posterUrls,
    onClose,
    onQueued,
}: {
    api: EclypteApiClient
    open: boolean
    assets: AssetSummary[]
    posterUrls: Record<string, string>
    onClose: () => void
    onQueued: (next: Awaited<ReturnType<EclypteApiClient["addAutopilotItems"]>>) => void
}) {
    const [videoId, setVideoId] = useState("")
    const [songMode, setSongMode] = useState<"asset" | "youtube">("asset")
    const [songId, setSongId] = useState("")
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [brief, setBrief] = useState("")
    const [formError, setFormError] = useState<string | null>(null)
    const [isAdding, setIsAdding] = useState(false)

    const videos = assets.filter((asset) => asset.kind === "source_video" && asset.current_version_id && !asset.archived_at)
    const songs = assets.filter((asset) => asset.kind === "song_audio" && asset.current_version_id && !asset.archived_at)

    const add = async () => {
        const video = videos.find((asset) => asset.file_id === videoId)
        if (!video?.current_version_id) {
            setFormError("Pick a film first.")
            return
        }
        const song = songMode === "asset" ? songs.find((asset) => asset.file_id === songId) : null
        if (songMode === "asset" && !song?.current_version_id) {
            setFormError("Pick a song, or switch to a YouTube link.")
            return
        }
        if (songMode === "youtube" && !youtubeUrl.trim()) {
            setFormError("Paste a YouTube link, or pick a saved song.")
            return
        }
        setIsAdding(true)
        setFormError(null)
        try {
            const next = await api.addAutopilotItems([
                {
                    source_video: { file_id: video.file_id, version_id: video.current_version_id },
                    song: song?.current_version_id ? { file_id: song.file_id, version_id: song.current_version_id } : null,
                    song_youtube_url: songMode === "youtube" ? youtubeUrl.trim() : null,
                    creative_brief: brief.trim(),
                },
            ])
            setYoutubeUrl("")
            setBrief("")
            onQueued(next)
        } catch (caught) {
            setFormError(errorMessage(caught))
        } finally {
            setIsAdding(false)
        }
    }

    return (
        <Sheet
            open={open}
            title="New reel"
            onClose={onClose}
            footer={
                <button className={styles.primaryButton} type="button" onClick={add} disabled={isAdding}>
                    {isAdding ? <Spinner onInk /> : <Plus size={16} />} Add to queue
                </button>
            }
        >
            {formError && <div className={styles.errorBanner}>{formError}</div>}
            <div className={styles.fieldLabel}>
                Film
                <div className={styles.mediaGrid} role="radiogroup" aria-label="Film">
                    {videos.map((asset) => {
                        const url = asset.poster ? posterUrls[posterKey(asset.poster)] : undefined
                        const selected = videoId === asset.file_id
                        return (
                            <button
                                key={asset.file_id}
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                className={styles.mediaCard}
                                style={selected ? { borderColor: "var(--text-primary)", boxShadow: "inset 0 0 0 1px var(--text-primary)" } : undefined}
                                onClick={() => setVideoId(asset.file_id)}
                            >
                                {url ? <img className={styles.mediaThumb} src={url} alt="" /> : <span className={styles.mediaThumb} aria-hidden />}
                                <span className={styles.mediaCardBody}>
                                    <span className={styles.mediaTitle}>{stripExtension(asset.display_name)}</span>
                                </span>
                            </button>
                        )
                    })}
                </div>
            </div>
            <div className={styles.fieldLabel}>
                Song
                <Select
                    ariaLabel="Song source"
                    value={songMode}
                    onChange={(next) => setSongMode(next as "asset" | "youtube")}
                    options={[
                        { value: "asset", label: "Use a saved song" },
                        { value: "youtube", label: "Import from YouTube" },
                    ]}
                />
            </div>
            {songMode === "asset" ? (
                <div className={styles.fieldLabel}>
                    Saved song
                    <Select
                        ariaLabel="Saved song"
                        value={songId}
                        onChange={setSongId}
                        placeholder="Pick a song…"
                        options={songs.map((asset) => ({ value: asset.file_id, label: stripExtension(asset.display_name) }))}
                    />
                </div>
            ) : (
                <label className={styles.fieldLabel}>
                    YouTube link
                    <input className={styles.input} placeholder="https://youtu.be/…" value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} />
                </label>
            )}
            <label className={styles.fieldLabel}>
                Creative note (optional)
                <textarea className={`${styles.textarea} ${styles.compactTextarea}`} placeholder="Open on the most impactful shot, lean into the chorus…" value={brief} onChange={(event) => setBrief(event.target.value)} />
            </label>
        </Sheet>
    )
}
```

Notes for the implementer:
- `AutopilotStatus` in `eclypteApi.ts` already exposes `loop_configured`, `packaged_today`, `in_flight`, `pending` (used by the old autopilot page) — check the type at `eclypteApi.ts:183` and adjust property names to match exactly if they differ.
- `stripExtension` is exported for Task 10's Library; keep it here (Home) or move to `dashboardCommon.tsx` if lint complains about page exports — preferred home is `dashboardCommon.tsx`.
- If `next lint` flags the inline `style={{...}}` props, keep them (small one-offs) or promote to module classes — do not add a new CSS file.

- [ ] **Step 3: Mount the ToastProvider** — in `web/src/app/dashboard/layout.tsx`, wrap `{children}` with `<ToastProvider>` (import from `./dashboardCommon`). (Task 9 rewrites this file; add the provider now so Home's toasts work standalone.)

- [ ] **Step 4: Lint + build + manual pass**

Run (from `web/`): `npm run lint && npm run build` → PASS.
Manual (`npm run dev`, `/dashboard`): feed renders with real data; Review sheet opens/edits/closes with Escape; composer queues an item; switch toggles; posters appear for posts whose run has a poster (placeholder otherwise). Compare against `home-design.html`.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/dashboard/page.tsx web/src/app/dashboard/layout.tsx
git commit -m "feat(dashboard): pipeline Home feed with review + composer sheets"
```

---

### Task 9: Frontend — top-bar shell, retire the sidebar, redirect absorbed routes

**Files:**
- Rewrite: `web/src/app/dashboard/layout.tsx`
- Rewrite: `web/src/app/dashboard/layout.module.css`
- Rewrite (to redirect stubs): `web/src/app/dashboard/autopilot/page.tsx`, `web/src/app/dashboard/publish/page.tsx`, `web/src/app/dashboard/renders/page.tsx`
- Delete: `web/src/components/dashboard/sidebar/sidebar.tsx`, `web/src/components/dashboard/sidebar/sidebar.module.css`

**Interfaces:**
- Consumes: `ToastProvider` (Task 7).
- Produces: nav = Home (`/dashboard`, exact match) + Library (`/dashboard/assets`) + Settings icon + sign-out. Absorbed routes 302 into the new IA (bookmarks keep working). `/dashboard/new-edit` and `/dashboard/synthesis` remain routable, just unlisted.

- [ ] **Step 1: Rewrite `web/src/app/dashboard/layout.tsx`:**

```tsx
"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useClerk } from "@clerk/nextjs"
import { LogOut, Settings } from "lucide-react"
import styles from "./layout.module.css"
import { ToastProvider } from "./dashboardCommon"

const navItems = [
    { href: "/dashboard", label: "Home" },
    { href: "/dashboard/assets", label: "Library" },
]

export default function Layout({ children }: { children: React.ReactNode }) {
    const pathname = usePathname()
    const { signOut } = useClerk()

    const isActive = (href: string) =>
        href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href)

    return (
        <div className={styles.container} data-surface="studio">
            <ToastProvider>
                <header className={styles.topBar}>
                    <Link className={styles.brand} href="/dashboard">
                        Eclypte
                    </Link>
                    <nav className={styles.nav} aria-label="Main">
                        {navItems.map((item) => (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={isActive(item.href) ? styles.navLinkActive : styles.navLink}
                                aria-current={isActive(item.href) ? "page" : undefined}
                            >
                                {item.label}
                            </Link>
                        ))}
                    </nav>
                    <div className={styles.topBarRight}>
                        <Link
                            href="/dashboard/settings"
                            className={isActive("/dashboard/settings") ? styles.navLinkActive : styles.navLink}
                            aria-label="Settings"
                        >
                            <Settings size={17} aria-hidden />
                        </Link>
                        <button
                            type="button"
                            className={styles.signOut}
                            onClick={() => signOut({ redirectUrl: "/" })}
                            aria-label="Sign out"
                        >
                            <LogOut size={16} aria-hidden />
                        </button>
                    </div>
                </header>
                <main className={styles.main}>{children}</main>
            </ToastProvider>
        </div>
    )
}
```

- [ ] **Step 2: Rewrite `web/src/app/dashboard/layout.module.css`:**

```css
.container {
	min-height: 100dvh;
	width: 100%;
	display: flex;
	flex-direction: column;
	background: var(--surface-base);
	color: var(--text-primary);
	font-family: var(--font-ui);
}

.topBar {
	position: sticky;
	top: 0;
	z-index: 50;
	display: flex;
	align-items: center;
	gap: 1.6rem;
	padding: 0.85rem 2rem;
	background: var(--surface-base);
	border-bottom: 1px solid var(--line);
}

.brand {
	font-size: 1.05rem;
	font-weight: 500;
	letter-spacing: -0.01em;
	color: var(--text-primary);
}

.nav {
	display: flex;
	align-items: center;
	gap: 1.1rem;
}

.navLink,
.navLinkActive {
	display: inline-flex;
	align-items: center;
	gap: 0.35rem;
	font-size: 0.92rem;
	color: var(--text-muted);
	border-radius: 8px;
	padding: 0.3rem 0.45rem;
	transition: color 140ms ease;
}

.navLink:hover { color: var(--text-primary); }
.navLinkActive { color: var(--text-primary); font-weight: 500; }

.navLink:focus-visible,
.navLinkActive:focus-visible,
.signOut:focus-visible,
.brand:focus-visible {
	outline: 2px solid var(--focus-ring);
	outline-offset: 2px;
}

.topBarRight {
	margin-left: auto;
	display: flex;
	align-items: center;
	gap: 0.5rem;
}

.signOut {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 34px;
	height: 34px;
	border: none;
	border-radius: 8px;
	background: transparent;
	color: var(--text-muted);
	cursor: pointer;
	transition: color 140ms ease, background-color 140ms ease;
}

.signOut:hover { color: var(--text-primary); background: var(--surface-sunk); }

.main {
	flex: 1;
	width: 100%;
	box-sizing: border-box;
	padding: 2rem 2rem 4rem;
}

@media (max-width: 640px) {
	.topBar { padding: 0.75rem 1rem; gap: 1rem; }
	.main { padding: 1.4rem 1rem 3rem; }
}
```

- [ ] **Step 3: Replace the absorbed pages with redirect stubs.**

`web/src/app/dashboard/autopilot/page.tsx` and `web/src/app/dashboard/publish/page.tsx` (identical content, adjust nothing else):

```tsx
import { redirect } from "next/navigation"

export default function Page() {
    redirect("/dashboard")
}
```

`web/src/app/dashboard/renders/page.tsx`:

```tsx
import { redirect } from "next/navigation"

export default function Page() {
    redirect("/dashboard/assets?tab=reels")
}
```

- [ ] **Step 4: Delete the sidebar** (`web/src/components/dashboard/sidebar/`), then grep for stragglers:

Run (from `web/`): `grep -rn "dashboard/sidebar\|@dbcomponents/sidebar" src`
Expected: no matches.

- [ ] **Step 5: Lint + build + manual**

Run (from `web/`): `npm run lint && npm run build` → PASS. Manual: top bar on every dashboard page; `/dashboard/publish`, `/dashboard/autopilot`, `/dashboard/renders` redirect; `/dashboard/new-edit` + `/dashboard/synthesis` load (unlisted) and look coherent; mobile width shows the same bar (no hamburger).

- [ ] **Step 6: Commit**

```bash
git add -A web/src/app/dashboard web/src/components/dashboard
git commit -m "feat(dashboard): top-bar shell, retire sidebar, redirect absorbed routes"
```

---

### Task 10: Frontend — Library rebuild (Films / Songs / Reels) + real byte-progress uploads

Build against `library-design.html`. One deliberate simplification vs the mockup: film cards show no duration (it lives only in the analysis JSON, which is too heavy to fetch per card) — status + date instead.

**Files:**
- Modify: `web/src/services/eclypteApi.ts:785-825` (`uploadAsset`) and `:993-1012` (`uploadToPresignedUrl`)
- Rewrite: `web/src/app/dashboard/assets/page.tsx`

**Interfaces:**
- Consumes: primitives + `usePosterUrls`/`posterKey` + `stripExtension` (move it into `dashboardCommon.tsx` now if Task 8 left it in the Home page — Library needs it too); existing `assetState`, `waitForRunCompletion`, `downloadSignedUrl`/`safeDownloadFilename` from `@/services/downloadFile`.
- Produces: `uploadToPresignedUrl(url, file, headers, signal?, onProgress?: (loadedBytes: number) => void)` (XHR path when `onProgress` given, fetch path otherwise) and `uploadAsset(api, { file, kind, contentType, signal, onStatus, onProgress })`.

- [ ] **Step 1: Add byte progress to the upload path** in `eclypteApi.ts`. Extend `uploadToPresignedUrl`:

```ts
export async function uploadToPresignedUrl(
    url: string,
    file: File,
    headers: Record<string, string>,
    signal?: AbortSignal,
    onProgress?: (loadedBytes: number) => void,
) {
    if (!onProgress) {
        const response = await fetch(url, { method: "PUT", headers, body: file, signal })
        if (!response.ok) {
            throw new EclypteApiError(`Upload failed with status ${response.status}`, response.status)
        }
        return
    }
    // fetch() cannot report upload progress; XHR can.
    await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open("PUT", url)
        for (const [key, value] of Object.entries(headers)) {
            xhr.setRequestHeader(key, value)
        }
        xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
                onProgress(event.loaded)
            }
        }
        xhr.onload = () =>
            xhr.status >= 200 && xhr.status < 300
                ? resolve()
                : reject(new EclypteApiError(`Upload failed with status ${xhr.status}`, xhr.status))
        xhr.onerror = () => reject(new EclypteApiError("Upload failed", 0))
        xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"))
        if (signal) {
            if (signal.aborted) {
                xhr.abort()
                return
            }
            signal.addEventListener("abort", () => xhr.abort(), { once: true })
        }
        xhr.send(file)
    })
}
```

And thread it through `uploadAsset`: add `onProgress?: (loadedBytes: number) => void` to the options type, change the status copy to sentence case (`"Checking the file"`, `"Uploading"`, `"Finishing up"`), and pass `onProgress` as the fifth argument of `uploadToPresignedUrl`.

- [ ] **Step 2: Rewrite `web/src/app/dashboard/assets/page.tsx`.** Structure (complete component below):

```tsx
"use client"

import { ChangeEvent, Suspense, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useUser } from "@clerk/nextjs"
import { Activity, Download, Link2, Music, Plus, RotateCcw, Trash2 } from "lucide-react"
import {
    DashboardPage,
    Pager,
    Sheet,
    SkeletonList,
    Spinner,
    errorMessage,
    formatBytes,
    formatDate,
    isAbortError,
    stripExtension,
    usePagination,
    useToast,
    versionRef,
} from "../dashboardCommon"
import { posterKey, usePosterUrls } from "../posterUrls"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import {
    AssetSummary,
    EclypteApiClient,
    PublishingPost,
    assetState,
    uploadAsset,
    waitForRunCompletion,
} from "@/services/eclypteApi"
import { useAssets, usePublishingPosts } from "@/stores/dashboardResources"

type LibraryTab = "films" | "songs" | "reels" | "hidden"
type UploadCard = { id: number; name: string; loaded: number; total: number; stage: string; error: string | null }
type ImportCard = { url: string; stage: string; error: string | null }

const AUDIO_UPLOAD_EXTENSIONS = ["wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "aiff", "wma"]

export default function AssetsPage() {
    return (
        <Suspense fallback={<SkeletonList count={3} />}>
            <LibraryPage />
        </Suspense>
    )
}

function LibraryPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const router = useRouter()
    const searchParams = useSearchParams()
    const toast = useToast()
    const tab = (searchParams.get("tab") as LibraryTab) || "films"
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [addOpen, setAddOpen] = useState(false)
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [uploads, setUploads] = useState<UploadCard[]>([])
    const [imports, setImports] = useState<ImportCard[]>([])
    const [error, setError] = useState<string | null>(null)
    const uploadIdRef = useRef(0)

    const api = useMemo(() => (user?.id ? new EclypteApiClient({ userId: user.id }) : null), [user?.id])
    const assetsResource = useAssets(api, { includeArchived: true })
    const assets = useMemo(() => assetsResource.data ?? [], [assetsResource.data])
    const setAssets = assetsResource.set
    const reelsResource = useAssets(api, { kind: "render_output" })
    const reels = useMemo(() => reelsResource.data ?? [], [reelsResource.data])
    const postsResource = usePublishingPosts(api, { status: "all" })
    const posts = useMemo(() => postsResource.data ?? [], [postsResource.data])
    const postByRender = useMemo(() => new Map(posts.map((post) => [post.render_file_id, post])), [posts])

    const films = assets.filter((a) => a.kind === "source_video" && a.current_version_id && !a.archived_at)
    const songs = assets.filter((a) => a.kind === "song_audio" && a.current_version_id && !a.archived_at)
    const hidden = assets.filter((a) => Boolean(a.archived_at))
    const tabItems: AssetSummary[] = tab === "films" ? films : tab === "songs" ? songs : tab === "reels" ? reels : hidden
    const pager = usePagination(tabItems, tab === "songs" ? 10 : 12, tab)

    const posterUrls = usePosterUrls(api, [
        ...films.map((a) => a.poster),
        ...reels.map((a) => a.poster),
    ])

    const setTab = (next: LibraryTab) => {
        setSelectedId(null)
        router.replace(next === "films" ? "/dashboard/assets" : `/dashboard/assets?tab=${next}`)
    }

    const selected = selectedId
        ? [...films, ...songs, ...reels, ...hidden].find((a) => a.file_id === selectedId) ?? null
        : null

    // --- Add flow: one smart file input (MP4 → film, audio → song), plus YouTube. ---
    const onPick = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0] ?? null
        event.target.value = ""
        if (!file || !api) {
            return
        }
        const extension = file.name.toLowerCase().split(".").pop() ?? ""
        const isVideo = file.type === "video/mp4" || extension === "mp4"
        const isAudio = file.type.startsWith("audio/") || AUDIO_UPLOAD_EXTENSIONS.includes(extension)
        if (!isVideo && !isAudio) {
            setError("Use an MP4 film or a common audio file (WAV, MP3, M4A, FLAC, OGG).")
            return
        }
        setError(null)
        setAddOpen(false)
        void runUpload(file, isVideo)
    }

    const runUpload = async (file: File, isVideo: boolean) => {
        if (!api) {
            return
        }
        const id = ++uploadIdRef.current
        const patch = (partial: Partial<UploadCard>) =>
            setUploads((current) => current.map((card) => (card.id === id ? { ...card, ...partial } : card)))
        setUploads((current) => [
            ...current,
            { id, name: stripExtension(file.name), loaded: 0, total: file.size, stage: "Checking the file", error: null },
        ])
        try {
            const extension = file.name.toLowerCase().split(".").pop() ?? ""
            const isWav = file.type === "audio/wav" || extension === "wav"
            const uploaded = await uploadAsset(api, {
                file,
                kind: isVideo ? "source_video" : "song_audio",
                contentType: isVideo ? "video/mp4" : file.type || "application/octet-stream",
                onStatus: (stage) => patch({ stage }),
                onProgress: (loaded) => patch({ loaded, stage: "Uploading" }),
            })
            if (!isVideo && !isWav) {
                patch({ stage: "Converting the audio", loaded: file.size })
                const run = await api.createAudioConversion(uploaded)
                await waitForRunCompletion(api, run)
            }
            setUploads((current) => current.filter((card) => card.id !== id))
            assetsResource.revalidate()
            toast(`${stripExtension(file.name)} added to your library`)
        } catch (caught) {
            if (isAbortError(caught)) {
                setUploads((current) => current.filter((card) => card.id !== id))
                return
            }
            patch({ error: errorMessage(caught), stage: "Didn't work" })
        }
    }

    const runImport = async () => {
        if (!api || !youtubeUrl.trim()) {
            return
        }
        const url = youtubeUrl.trim()
        setYoutubeUrl("")
        setAddOpen(false)
        const patch = (partial: Partial<ImportCard>) =>
            setImports((current) => current.map((card) => (card.url === url ? { ...card, ...partial } : card)))
        setImports((current) => [...current, { url, stage: "Getting the song", error: null }])
        try {
            const run = await api.createYouTubeSongImport(url)
            await waitForRunCompletion(api, run, {
                onUpdate: (next) => patch({ stage: next.status === "running" ? "Getting the song" : "Finishing up" }),
            })
            setImports((current) => current.filter((card) => card.url !== url))
            if (tab !== "songs") {
                setTab("songs")
            }
            assetsResource.revalidate()
            toast("Song imported and ready")
        } catch (caught) {
            patch({ error: errorMessage(caught), stage: "Didn't work" })
        }
    }

    // --- Row/card actions (archive keeps the old optimistic cache patch behavior). ---
    const [busyAction, setBusyAction] = useState<string | null>(null)
    const act = async (name: string, action: () => Promise<void>) => {
        setBusyAction(name)
        setError(null)
        try {
            await action()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setBusyAction(null)
        }
    }

    const analyze = (asset: AssetSummary) =>
        act("analyze", async () => {
            const ref = versionRef(asset)
            if (!api || !ref) {
                return
            }
            const run = asset.kind === "song_audio" ? await api.createMusicAnalysis(ref) : await api.createVideoAnalysis(ref)
            assetsResource.revalidate()
            await waitForRunCompletion(api, run)
            assetsResource.revalidate()
            toast("All set — ready to use")
        })

    const download = (asset: AssetSummary) =>
        act("download", async () => {
            const ref = versionRef(asset)
            if (!api || !ref) {
                return
            }
            const downloadUrl = (await api.getDownloadUrl(ref)).download_url
            await downloadSignedUrl({
                url: downloadUrl,
                filename: safeDownloadFilename(asset.current_version?.original_filename || asset.display_name, "eclypte-asset"),
            })
        })

    const hide = (asset: AssetSummary) =>
        act("hide", async () => {
            if (!api) {
                return
            }
            await api.deleteAsset(asset.file_id)
            setSelectedId(null)
            setAssets((current = []) =>
                current.map((item) =>
                    item.file_id === asset.file_id
                        ? { ...item, archived_at: new Date().toISOString(), archived_reason: item.archived_reason ?? "archived" }
                        : item,
                ),
            )
            toast(`${stripExtension(asset.display_name)} hidden`)
        })

    const restore = (asset: AssetSummary) =>
        act("restore", async () => {
            if (!api) {
                return
            }
            const restored = await api.restoreAsset(asset.file_id)
            setAssets((current = []) => current.map((item) => (item.file_id === restored.file_id ? restored : item)))
            toast(`${stripExtension(asset.display_name)} restored`)
        })

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Library" title="Library">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Library" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to manage your library.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Everything you own"
            title="Library"
            action={
                <button className={styles.primaryButton} type="button" onClick={() => setAddOpen(true)}>
                    <Plus size={16} /> Add
                </button>
            }
        >
            {(error || assetsResource.error) && <div className={styles.errorBanner}>{error || assetsResource.error}</div>}

            <div className={styles.tabPills} role="tablist" aria-label="Library">
                {(["films", "songs", "reels"] as const).map((item) => (
                    <button
                        key={item}
                        type="button"
                        role="tab"
                        aria-selected={tab === item}
                        className={tab === item ? styles.pillActive : styles.pill}
                        onClick={() => setTab(item)}
                    >
                        {item === "films" ? `Films (${films.length})` : item === "songs" ? `Songs (${songs.length})` : `Reels (${reels.length})`}
                    </button>
                ))}
                <button type="button" className={styles.hiddenLink} onClick={() => setTab("hidden")}>
                    Hidden{hidden.length ? ` (${hidden.length})` : ""}
                </button>
            </div>

            {/* In-flight uploads/imports appear at the top of the active view. */}
            {(uploads.length > 0 || imports.length > 0) && (
                <div className={styles.feedSection}>
                    {uploads.map((card) => (
                        <div key={card.id} className={styles.progressRow}>
                            <div className={styles.progressRowTop}>
                                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                                    {!card.error && <Spinner />}
                                    <span className={styles.truncate}>{card.name}</span>
                                </span>
                                <span>
                                    {card.error
                                        ? card.error
                                        : card.stage === "Uploading"
                                            ? `Uploading · ${formatBytes(card.loaded)} of ${formatBytes(card.total)}`
                                            : `${card.stage}…`}
                                </span>
                            </div>
                            {!card.error && card.stage === "Uploading" && (
                                <div className={styles.progressTrack}>
                                    <div className={styles.progressFill} style={{ width: `${Math.min(100, (card.loaded / Math.max(1, card.total)) * 100)}%` }} />
                                </div>
                            )}
                            {card.error && (
                                <div>
                                    <button className={styles.ghostButton} type="button" onClick={() => setUploads((current) => current.filter((item) => item.id !== card.id))}>
                                        Dismiss
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                    {imports.map((card) => (
                        <div key={card.url} className={styles.progressRow}>
                            <div className={styles.progressRowTop}>
                                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                                    {!card.error && <Spinner />}
                                    <span className={styles.truncate}>{card.url}</span>
                                </span>
                                <span>{card.error ?? `${card.stage}…`}</span>
                            </div>
                            {card.error && (
                                <div>
                                    <button className={styles.ghostButton} type="button" onClick={() => setImports((current) => current.filter((item) => item.url !== card.url))}>
                                        Dismiss
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {tabItems.length === 0 && uploads.length === 0 && imports.length === 0 ? (
                <div className={styles.emptyState}>
                    <p className={styles.emptyStateTitle}>{emptyTitle(tab)}</p>
                    <p className={styles.emptyStateHint}>{emptyHint(tab)}</p>
                </div>
            ) : tab === "songs" ? (
                <div>
                    {pager.pageItems.map((asset) => (
                        <SongRow key={asset.file_id} asset={asset} onOpen={() => setSelectedId(asset.file_id)} />
                    ))}
                    <Pager page={pager.page} pageCount={pager.pageCount} onPrev={pager.prev} onNext={pager.next} />
                </div>
            ) : (
                <>
                    <div className={styles.mediaGrid}>
                        {pager.pageItems.map((asset) => (
                            <MediaCard
                                key={asset.file_id}
                                asset={asset}
                                tall={tab === "reels"}
                                posterUrl={asset.poster ? posterUrls[posterKey(asset.poster)] : undefined}
                                postedLabel={tab === "reels" ? reelPostedLabel(postByRender.get(asset.file_id)) : null}
                                onOpen={() => setSelectedId(asset.file_id)}
                            />
                        ))}
                    </div>
                    <Pager page={pager.page} pageCount={pager.pageCount} onPrev={pager.prev} onNext={pager.next} />
                </>
            )}

            {api && selected && (
                <AssetSheet
                    api={api}
                    asset={selected}
                    posterUrl={selected.poster ? posterUrls[posterKey(selected.poster)] : undefined}
                    busyAction={busyAction}
                    onClose={() => setSelectedId(null)}
                    onAnalyze={() => analyze(selected)}
                    onDownload={() => download(selected)}
                    onHide={() => hide(selected)}
                    onRestore={() => restore(selected)}
                />
            )}

            <Sheet
                open={addOpen}
                title="Add to your library"
                onClose={() => setAddOpen(false)}
                footer={
                    <button className={styles.secondaryButton} type="button" onClick={runImport} disabled={!youtubeUrl.trim()}>
                        <Link2 size={15} /> Import from YouTube
                    </button>
                }
            >
                <label className={`${styles.filePicker} ${styles.uploadDrop}`}>
                    <span className={styles.fileName}>Choose a file</span>
                    <span className={styles.muted}>An MP4 becomes a film; audio (WAV, MP3, M4A, FLAC…) becomes a song.</span>
                    <input type="file" accept={`video/mp4,.mp4,audio/*,${AUDIO_UPLOAD_EXTENSIONS.map((ext) => `.${ext}`).join(",")}`} onChange={onPick} />
                </label>
                <label className={styles.fieldLabel}>
                    Or paste a YouTube song link
                    <input className={styles.input} placeholder="https://youtu.be/…" value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} />
                </label>
            </Sheet>
        </DashboardPage>
    )
}
```

- [ ] **Step 3: Add the presentational pieces** (same file, below the page):

```tsx
function assetStatusText(asset: AssetSummary): { text: string; busy: boolean; ok: boolean } {
    const state = assetState(asset)
    if (state === "analyzing") {
        return { text: asset.kind === "song_audio" ? "Listening to the song…" : "Getting to know this film…", busy: true, ok: false }
    }
    if (state === "ready") {
        return { text: "Ready to use", busy: false, ok: true }
    }
    if (state === "failed") {
        return { text: "Needs another try", busy: false, ok: false }
    }
    return { text: "Needs a first look", busy: false, ok: false }
}

function MediaCard({
    asset,
    tall,
    posterUrl,
    postedLabel,
    onOpen,
}: {
    asset: AssetSummary
    tall: boolean
    posterUrl?: string
    postedLabel: string | null
    onOpen: () => void
}) {
    const status = assetStatusText(asset)
    return (
        <button type="button" className={styles.mediaCard} onClick={onOpen}>
            {posterUrl ? (
                <img className={`${styles.mediaThumb} ${tall ? styles.mediaThumbTall : ""}`} src={posterUrl} alt="" />
            ) : (
                <span className={`${styles.mediaThumb} ${tall ? styles.mediaThumbTall : ""}`} aria-hidden />
            )}
            <span className={styles.mediaCardBody}>
                <span className={styles.mediaTitle}>{stripExtension(asset.display_name)}</span>
                <span className={styles.mediaMeta}>
                    {postedLabel ?? (
                        <>
                            {status.busy ? <Spinner /> : <span className={styles.statusDotSwatch} style={{ background: status.ok ? "var(--ok)" : "var(--attention)" }} aria-hidden />}
                            {status.text}
                        </>
                    )}
                </span>
            </span>
        </button>
    )
}

function SongRow({ asset, onOpen }: { asset: AssetSummary; onOpen: () => void }) {
    const status = assetStatusText(asset)
    return (
        <button type="button" className={styles.songRow} onClick={onOpen}>
            <span className={styles.songArt} aria-hidden><Music size={16} /></span>
            <span style={{ minWidth: 0 }}>
                <span className={styles.mediaTitle} style={{ display: "block" }}>{stripExtension(asset.display_name)}</span>
                <span className={styles.mediaMeta}>
                    {status.busy ? <Spinner /> : <span className={styles.statusDotSwatch} style={{ background: status.ok ? "var(--ok)" : "var(--attention)" }} aria-hidden />}
                    {status.text}
                </span>
            </span>
        </button>
    )
}

function reelPostedLabel(post: PublishingPost | undefined) {
    if (!post) {
        return "Not posted yet"
    }
    if (post.status === "published") {
        return "On Instagram"
    }
    if (post.status === "queued" || post.status === "scheduled") {
        return "Queued to post"
    }
    return "Not posted yet"
}

function AssetSheet({
    api,
    asset,
    posterUrl,
    busyAction,
    onClose,
    onAnalyze,
    onDownload,
    onHide,
    onRestore,
}: {
    api: EclypteApiClient
    asset: AssetSummary
    posterUrl?: string
    busyAction: string | null
    onClose: () => void
    onAnalyze: () => void
    onDownload: () => void
    onHide: () => void
    onRestore: () => void
}) {
    const [previewUrl, setPreviewUrl] = useState<string | null>(null)
    const isArchived = Boolean(asset.archived_at)
    const contentType = asset.current_version?.content_type || ""
    const isAudio = contentType.startsWith("audio/")
    const isVideo = contentType.startsWith("video/")
    const status = assetStatusText(asset)
    const canAnalyze = (asset.kind === "song_audio" || asset.kind === "source_video") && !asset.analysis && !isArchived && !status.busy

    const openPreview = async () => {
        const ref = versionRef(asset)
        if (!ref) {
            return
        }
        const download = await api.getDownloadUrl(ref)
        setPreviewUrl(download.download_url)
    }

    return (
        <Sheet
            open
            title={stripExtension(asset.display_name)}
            onClose={onClose}
            footer={
                <>
                    {canAnalyze && (
                        <button className={styles.secondaryButton} type="button" onClick={onAnalyze} disabled={busyAction !== null}>
                            {busyAction === "analyze" ? <Spinner /> : <Activity size={15} />} Get it ready
                        </button>
                    )}
                    <button className={styles.secondaryButton} type="button" onClick={onDownload} disabled={busyAction !== null || !asset.current_version_id}>
                        {busyAction === "download" ? <Spinner /> : <Download size={15} />} Download
                    </button>
                    <span className={styles.sheetActionsRight}>
                        {isArchived ? (
                            <button className={styles.secondaryButton} type="button" onClick={onRestore} disabled={busyAction !== null}>
                                {busyAction === "restore" ? <Spinner /> : <RotateCcw size={15} />} Restore
                            </button>
                        ) : (
                            <button className={styles.dangerButton} type="button" onClick={onHide} disabled={busyAction !== null}>
                                {busyAction === "hide" ? <Spinner /> : <Trash2 size={15} />} Hide
                            </button>
                        )}
                    </span>
                </>
            }
        >
            {previewUrl ? (
                <>
                    {isAudio && <audio className={styles.previewMedia} controls autoPlay src={previewUrl} />}
                    {isVideo && <video className={styles.previewMedia} controls src={previewUrl} />}
                </>
            ) : (
                <button type="button" className={styles.posterButton} onClick={openPreview}>
                    {posterUrl ? (
                        <img className={styles.mediaThumb} src={posterUrl} alt="" />
                    ) : (
                        <span className={styles.mediaThumb} aria-hidden />
                    )}
                    <span className={styles.posterPlayIcon}>▶</span>
                </button>
            )}
            <p className={styles.smallText} style={{ margin: 0 }}>
                <span className={status.busy ? "" : ""}>{status.text}</span>
                {" · added "}{formatDate(asset.created_at)}
                {" · "}{formatBytes(asset.current_version?.size_bytes)}
            </p>
        </Sheet>
    )
}

function emptyTitle(tab: LibraryTab) {
    if (tab === "films") return "No films yet"
    if (tab === "songs") return "No songs yet"
    if (tab === "reels") return "No reels yet"
    return "Nothing hidden"
}

function emptyHint(tab: LibraryTab) {
    if (tab === "films") return "Add an MP4 of a film or anime — it becomes the footage your reels are cut from."
    if (tab === "songs") return "Add an audio file or import a song from YouTube."
    if (tab === "reels") return "Finished reels land here automatically."
    return "Things you hide can be restored from here."
}
```

- [ ] **Step 4: Move `stripExtension` into `dashboardCommon.tsx`** (exported) and update the Home import (`./dashboardCommon` instead of local) if Task 8 defined it locally.

- [ ] **Step 5: Lint + build + manual**

Run (from `web/`): `npm run lint && npm run build` → PASS.
Manual: upload an MP3 → in-grid card with live byte progress, then "Converting the audio…", then it lands in Songs with a toast; upload an MP4 → Films; import a YouTube URL → progress row → Songs; Reels tab shows posters + posted state; `?tab=reels` deep link works (from Home "See all" and the old renders redirect); Hidden restore works; sizes appear only in the detail sheet. Compare against `library-design.html`.

- [ ] **Step 6: Commit**

```bash
git add web/src/services/eclypteApi.ts web/src/app/dashboard/assets/page.tsx web/src/app/dashboard/dashboardCommon.tsx web/src/app/dashboard/page.tsx
git commit -m "feat(dashboard): Library with Films/Songs/Reels tabs + real byte-progress uploads"
```

---

### Task 11: Frontend — Settings rework (plain words, diagnostics tucked away)

**Files:**
- Modify: `web/src/app/dashboard/settings/page.tsx` (keep `useAbortableLoad` + the existing data calls `api.health()` / `api.getSynthesisPrompt()`; restructure the rendering only)

**Interfaces:** consumes existing `HealthResponse` fields (`ok`, `youtube_cookies_configured`, `realtime_streaming_configured`, `worker_progress_configured`, `autopilot_loop_configured`) — check the exact booleans on the `HealthResponse` type at `eclypteApi.ts:291` and use what exists.

- [ ] **Step 1: Restructure the page body** (keep the component's data loading exactly as-is; replace the rendered groups):
  - Group "Account": signed-in email/name from Clerk `user`, sign-out hint.
  - Group "Connection": one row — "Studio connection" with `health.ok ? "Working" : "Not responding"` and a dot (`.statusDot`).
  - Group "Creative style": active prompt version label + `formatDate(created_at)` + a `detailLink` to `/dashboard/synthesis` ("Tune how your reels are edited") — this is the only remaining nav path to the unlisted synthesis page.
  - Group "Advanced" behind the existing `.disclosure` pattern: API base URL, YouTube import readiness (`youtube_cookies_configured` → "Song imports: ready" / "Song imports: may be flaky"), live updates (`realtime_streaming_configured` → "Live updates: on" / "Live updates: checking periodically"), worker progress, autopilot loop (`autopilot_loop_configured` → "Always-on creation: on" / "manual"), and the Clerk user id behind `CopyableId`.
  - All copy sentence-case; no raw env names; no "Redis"/"Buffer"/"Modal".

- [ ] **Step 2: Lint + build + manual** (from `web/`): `npm run lint && npm run build` → PASS; page reads like product copy, advanced details only under the disclosure.

- [ ] **Step 3: Commit**

```bash
git add web/src/app/dashboard/settings/page.tsx
git commit -m "feat(dashboard): settings in plain words with diagnostics tucked into Advanced"
```

---

### Task 12: Cleanup, docs, memory, final verification

**Files:**
- Modify: `web/src/app/dashboard/studio.module.css` (delete now-dead classes)
- Modify: `CLAUDE.md`, `AGENTS.md`, `web/AGENTS.md`, `api/COMMANDS.md`
- Modify: `C:\Users\ericm\.claude\projects\c--Users-ericm-Documents-GitHub-eclypte\memory\project_dashboard_edit_bay_identity.md` (+ `MEMORY.md` index line)

- [ ] **Step 1: Dead-class sweep.** For each of these candidate-dead classes, grep usage and delete the rule if it has none: `.packageList`, `.packageRow*`, `.queueStrip`, `.queueLine*`, `.heroPlayer`, `.heroCaption*`, `.assetCaption*`, `.filmstrip*`, `.settingCard`, `.assetGrid`, `.numeral`, `.copyId` (keep if `CopyableId` survives in settings Advanced), `.stageProgress*`, `.assetTable*` (new-edit may still use), `.disclosure*` (settings uses), `.exportSection`/`.trimSummary`/`.rangeGrid`/`.numberGrid`/`.cropPreview*` (new-edit uses — keep).

Run (from `web/`): for each name `grep -rn "styles.packageRow" src` etc. Delete only zero-hit rules. Then `npm run build` → PASS.

- [ ] **Step 2: Docs reconciliation.**
  - `CLAUDE.md`: rewrite the Frontend section's page list (Home pipeline feed at `/dashboard` absorbing autopilot+publish; Library with Films/Songs/Reels absorbing renders; redirects; unlisted new-edit/synthesis; Ivory & Ink identity — light warm tokens under `[data-surface="studio"]`, PP Neue Montreal only, no uppercase; feedback tiers; new primitives in dashboardCommon; `source_poster` artifact kind + `AssetSummary.poster` contract + `source_poster_file_id/_version_id` outputs; `eclypte-video-r2` redeploy requirement).
  - `AGENTS.md` + `web/AGENTS.md`: same facts in their format; update the "Edit Bay" description everywhere it appears.
  - `api/COMMANDS.md`: confirm the Modal deploy section covers `modal deploy video/storage_modal.py` (with `PYTHONUTF8=1` on Windows) and note re-analysis populates posters for existing films.
- [ ] **Step 3: Memory update.** Rewrite `project_dashboard_edit_bay_identity.md` to describe the Ivory & Ink identity (name slug can stay; update title/description/body: light warm ivory #F7F5F1, ink #26231E, coral #E86A4F accent, PP Neue Montreal, no uppercase, 3-page IA) and update its `MEMORY.md` hook line. The `feedback_dashboard_no_dev_internals` memory still applies — leave it.
- [ ] **Step 4: Full verification (spec's checklist).**

```bash
python -m pytest api -v                    # all backend suites green
cd web && npm run lint && npm run build   # frontend green
```

Manual sweep: marketing `/`, `/pricing`, `/demo` pixel-identical dark; every dashboard page light + sentence-case; upload byte progress; autopilot pairing flows Ready-for-you → review sheet → schedule (avoid live "Post now" unless intended); redirects; mobile viewport (bottom sheets); `prefers-reduced-motion` (spinners static, no shimmer); new-edit + synthesis usable via URL.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(dashboard): dead-class sweep + reconcile docs with the Ivory & Ink redesign"
```

**Post-merge rollout order:** deploy Railway (backend tasks) → `PYTHONUTF8=1 modal deploy video/storage_modal.py` from `api/prototyping/` → re-analyze one film and confirm its thumbnail appears in Library.
