# Direct Graph API Publishing (Phase B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PROBE-GATED:** Task 0 is a live-API probe with a decision checkpoint. Tasks 3b/5b depend on its findings; do not start them before Task 0's outcomes are recorded in this file.
>
> **STATUS (2026-08-04):** Tasks 1-6 implemented and merged (no Meta credentials in the dev environment, so shapes are probe-tolerant). Task 0 probes + the veto drill are the operator's next step; Tasks 3b/5b remain unbuilt pending the audio-offset answer.

**Goal:** Publish reels straight through the Instagram Graph API (Buffer stays the default provider) to unlock attached licensed audio, custom covers, a pre-publish copyright canary, and first-party insights metrics — the four reach surfaces Buffer structurally cannot reach.

**Architecture:** A new stdlib-only `api/instagram_graph.py` (pure payload builders + a `GraphPublisher` mirroring `BufferClient`'s urllib pattern) behind `ECLYPTE_PUBLISH_PROVIDER=buffer|graph`. `api/publishing.py` gains `send_post_via_graph` beside `send_post_to_buffer`; a small dispatch helper picks the provider. Graph publishing is immediate (no remote queue), so the autopilot send pass becomes the scheduler via slot spacing. Graph-published posts refresh status/permalink/metrics from the Graph API; Buffer-published posts keep the existing paths. All `PublishingPostRecord` additions are additive with defaults.

**Tech Stack:** Instagram Graph API (`graph.facebook.com`, Facebook-Login connection), stdlib urllib (no new deps), Pydantic v2 strict models, existing `apply_post_metrics`/`performance_score` fold (source-agnostic by design), pytest with fakes.

**Spec:** `docs/superpowers/specs/2026-08-04-reels-reach-recovery-design.md`

## Global Constraints

- Run backend tests with `.venv/bin/python -m pytest ...` from the repo root.
- `api/publishing.py` and `api/instagram_graph.py` stay stdlib-only for HTTP (mirror `BufferClient._graphql`'s urllib pattern).
- Default provider is `buffer`; every graph path is opt-in via env. A missing/invalid graph config must produce a typed `GraphConfigError`, never a silent fallback.
- All new `PublishingPostRecord` fields additive with defaults (`extra="forbid"` models; persisted R2 JSON must keep loading).
- Metrics rules carry over unchanged: absent ≠ 0; metrics work never touches `last_error`; nothing here counts toward the autopilot halt.
- Env names: `ECLYPTE_PUBLISH_PROVIDER`, `ECLYPTE_IG_USER_ID`, `ECLYPTE_IG_ACCESS_TOKEN`, `ECLYPTE_GRAPH_API_BASE` (default `https://graph.facebook.com/v23.0`). Never commit tokens.
- The human review gate is untouched: only `ready` posts are ever sent, by the same routes/passes as today.

---

### Task 0: Operator setup + live probes (CHECKPOINT)

**Files:**
- Modify (findings only): this plan + `api/COMMANDS.md`

- [ ] **Step 1: Meta app + token setup (operator, manual)**

Create a Meta app, connect the Instagram professional account via Facebook Login (the Audio API is documented for Facebook-Login connections), grant `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, exchange for a long-lived (60-day) token. Record the refresh procedure in `api/COMMANDS.md`. Confirm the account type is **Creator** (music-library breadth). Set `ECLYPTE_IG_USER_ID` + `ECLYPTE_IG_ACCESS_TOKEN` locally for probing.

- [ ] **Step 2: Probe the Audio API**

```bash
curl -s "https://graph.facebook.com/v23.0/${ECLYPTE_IG_USER_ID}/ig_audio?audio_type=music&search_query=<a real song>&access_token=${ECLYPTE_IG_ACCESS_TOKEN}" | python3 -m json.tool
```

Record: response shape, whether trending audio returns on an empty query, and **whether any start-offset/segment field exists** (on `ig_audio` results or in `audio_configuration`'s documented JSON shape).

- [ ] **Step 3: Probe container create + copyright canary (unpublished)**

Create a REELS container with a public test MP4 (`media_type=REELS`, `video_url`, `caption`), then poll `GET /{container-id}?fields=status_code,copyright_check_status` until `FINISHED`/`completed`. Record: field spellings, timing, and `matches_found` behavior for a burned-in commercial track. Do NOT `media_publish` unless intended. Also probe `cover_url` acceptance on the container.

- [ ] **Step 4: CHECKPOINT — record decisions in this file**

- **Audio decision:** If `audio_configuration` supports an offset that keeps a beat-cut edit sample-synced → Tasks 3b/5b build attached-audio publishing (render keeps video, song comes from the library). If NOT → skip Task 3b, keep burned-in audio, and Phase B still ships the canary + cover + insights + provider switch.
- **Field-name corrections:** amend later tasks' payload builders to the probed spellings before implementing them.

No commit (findings live in this plan + COMMANDS.md; commit those doc edits).

---

### Task 1: `api/instagram_graph.py` — pure builders + client

**Files:**
- Create: `api/instagram_graph.py`
- Create: `api/test_instagram_graph.py`

**Interfaces:** `GraphConfig.from_env()`; `build_reel_container_params(...) -> dict`; `GraphPublisher` with `create_reel_container`, `get_container_status`, `publish_container`, `get_media`, `get_insights`, `search_audio`; typed errors `GraphConfigError`, `GraphApiError`, `CopyrightBlockedError`.

- [x] **Step 1: Write the failing builder tests**

```python
from api.instagram_graph import build_reel_container_params


def test_reel_container_params_minimal():
    params = build_reel_container_params(
        video_url="https://cdn.example/reel.mp4", caption="hi\n#tag"
    )
    assert params == {
        "media_type": "REELS",
        "video_url": "https://cdn.example/reel.mp4",
        "caption": "hi\n#tag",
        "share_to_feed": "true",
    }


def test_reel_container_params_full():
    params = build_reel_container_params(
        video_url="https://cdn.example/reel.mp4",
        caption="c",
        cover_url="https://cdn.example/poster.jpg",
        audio_name="Song — Artist",
        audio_config={"audio_id": "123"},
    )
    assert params["cover_url"] == "https://cdn.example/poster.jpg"
    assert params["audio_name"] == "Song — Artist"
    assert json.loads(params["audio_configuration"]) == {"audio_id": "123"}


def test_graph_config_requires_env(monkeypatch):
    monkeypatch.delenv("ECLYPTE_IG_ACCESS_TOKEN", raising=False)
    with pytest.raises(GraphConfigError):
        GraphConfig.from_env()
```

- [x] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/test_instagram_graph.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement**

Module skeleton (urllib request/response mechanics copied from `BufferClient._graphql`, form-encoded POSTs, `access_token` always a param; every non-2xx or `{"error": ...}` body raises `GraphApiError` with the API's message; builders pure, JSON-encode `audio_configuration`, omit absent optionals; adjust field names to Task 0 findings):

```python
DEFAULT_GRAPH_API_BASE = "https://graph.facebook.com/v23.0"

@dataclass(frozen=True)
class GraphConfig:
    ig_user_id: str
    access_token: str
    api_base: str = DEFAULT_GRAPH_API_BASE

    @classmethod
    def from_env(cls) -> "GraphConfig": ...  # GraphConfigError on missing vars

class GraphPublisher:
    def __init__(self, config: GraphConfig): ...
    def create_reel_container(self, **kwargs) -> str: ...          # returns container id
    def get_container_status(self, container_id) -> dict: ...      # status_code, copyright_check_status
    def publish_container(self, container_id) -> str: ...          # returns ig media id
    def get_media(self, media_id, fields) -> dict: ...
    def get_insights(self, media_id, metrics) -> dict[str, float]: ...  # name -> value; absent stays absent
    def search_audio(self, query) -> list[dict]: ...
```

`get_insights` parses the insights list tolerantly (skip malformed entries, never invent zeros — same discipline as `get_post_metrics`).

- [x] **Step 4: Run**

Run: `.venv/bin/python -m pytest api/test_instagram_graph.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add api/instagram_graph.py api/test_instagram_graph.py
git commit -m "feat(publishing): Instagram Graph API client - containers, canary, insights, audio search"
```

---

### Task 2: Public poster copy for `cover_url`

**Files:**
- Modify: `api/publishing.py` (`prepare_public_media_copy` area, ~685-721)
- Test: `api/test_publishing.py`

- [x] **Step 1: Failing test** — a `prepare_public_poster_copy(repo, user_id, post)` that copies the post's `render_poster_file_id/version_id` blob to `public/publishing/{user}/{post}/{version}.jpg` and returns the public URL (same base-URL resolution as the MP4 copy); returns `None` when the post has no poster refs.

- [x] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest api/test_publishing.py -v -k poster_copy` → FAIL

- [x] **Step 3: Implement** by extracting the shared copy-to-public logic from `prepare_public_media_copy` (DRY: one helper, two extensions).

- [x] **Step 4: Run** — `.venv/bin/python -m pytest api/test_publishing.py -v` → PASS

- [x] **Step 5: Commit** — `feat(publishing): public poster copies for reel cover frames`

---

### Task 3: Provider switch + `send_post_via_graph`

**Files:**
- Modify: `api/storage/models.py` (`PublishingPostRecord` additive fields), `api/publishing.py`, `api/app.py` (send route + autopilot `send_ready_post` closure), `api/autopilot.py` (protocol untouched — dispatch stays in app.py)
- Test: `api/storage/test_models.py`, `api/test_publishing.py`, `api/test_api_v1.py`

**Interfaces:** `PublishingPostRecord.provider: str = "buffer"` (as built: the pre-existing field, stamped `"graph"` at graph-send time), `.ig_container_id: str | None`, `.ig_media_id: str | None`, `.copyright_status: str | None`; `resolve_publish_provider_env() -> str` (`"buffer"` default, `"graph"` allowed, anything else raises); inline provider dispatch (send route + autopilot send closure, keyed on `resolve_publish_provider_env()`) between `send_post_to_buffer` and `send_post_via_graph` (as built — no separate dispatch helper).

- [x] **Step 1: Failing tests** — model round-trip for the new fields; provider resolution default/invalid; `send_post_via_graph` happy path with a fake `GraphPublisher` (public copies prepared, container created with caption+hashtags via `format_post_text` and `cover_url`, polled to `FINISHED`, published, record stamped `status="published"`, `posted_at`, `provider="graph"`, `ig_media_id`, permalink from `get_media`); copyright-match path (a `matches_found` outcome with a MUTE/BLOCK action raises `CopyrightBlockedError`; the record keeps `status="ready"` and stamps `copyright_status` — the veto stays human-visible, NOT `last_error`-driven auto-retry).

- [x] **Step 2: Run to verify failure**

- [x] **Step 3: Implement.** `send_post_via_graph` mirrors `send_post_to_buffer`'s shape (typed errors, reload-then-save). Graph has no queue: `mode` is ignored; a sent post goes straight to `published`. Dispatch in `api/app.py`'s send route and the autopilot `send_ready_post` closure via `send_ready_post_for_provider`. `/v1/publishing/config` + `/healthz` gain non-secret provider booleans.

- [x] **Step 4: Run** — `.venv/bin/python -m pytest api/test_publishing.py api/test_api_v1.py api/storage -v` → PASS

- [x] **Step 5: Commit** — `feat(publishing): ECLYPTE_PUBLISH_PROVIDER=graph - direct Graph API reel publishing with cover + copyright canary`

---

### Task 3b (CONDITIONAL on Task 0 audio decision): attached licensed audio

**Files:**
- Modify: `api/publishing.py`, `api/instagram_graph.py`
- Test: `api/test_publishing.py`

Only if the probe confirmed offset-capable `audio_configuration`: resolve the post's song via `search_audio` (query = cleaned song name), attach `audio_configuration={audio_id, ...offset per probe...}` muting the container's own track per probed volume fields, and verify post-publish with `get_media(fields="media_audio_type,audio_id")` — `MUSIC` + the attached id, recorded on the post. A failed search/attach falls back to burned-in audio with a log (never blocks the send). Renders themselves stay unchanged (burned-in audio remains the master; attachment replaces it at publish time only when verified safe).

Commit: `feat(publishing): attach licensed library audio to graph-published reels`

---

### Task 4: Slot-based auto-send for the graph provider

**Files:**
- Modify: `api/autopilot.py` (`_auto_send_ready_posts`)
- Test: `api/test_autopilot.py`

- [x] **Step 1: Failing tests** — with provider `graph`: a ready post sends only when `now - newest published posted_at >= 86400 / daily_target` seconds (first-ever post sends immediately); at most one graph send per pass (each pass publishes immediately — the queue-backstop check translates to "published today < daily_target"); provider `buffer` behavior byte-identical to today.

- [x] **Step 2: Run to verify failure**

- [x] **Step 3: Implement** a pure `graph_slot_due(published_posts, daily_target, now) -> bool` + the provider branch in `_auto_send_ready_posts` (reusing `SEND_LOCK`, backoff, and budget scaffolding; Buffer branch untouched).

- [x] **Step 4: Run** — `.venv/bin/python -m pytest api/test_autopilot.py -v` → PASS

- [x] **Step 5: Commit** — `feat(autopilot): slot-spaced auto-publish for the graph provider`

---

### Task 5: Graph-side status + metrics refresh

**Files:**
- Modify: `api/autopilot.py` (`_reconcile_buffer_statuses` naming/dispatch, `_refresh_post_metrics`), `api/app.py` (refresh-status route + fetch closures)
- Test: `api/test_autopilot.py`, `api/test_publishing.py`

- [x] **Step 1: Failing tests** — a `published` graph post with `ig_media_id` refreshes metrics through `GraphPublisher.get_insights` folded by the existing `apply_post_metrics` (cadence/cap/retention constants unchanged; absent metrics stay absent); permalink backfill via `get_media`; Buffer posts keep using `get_post_metrics`; a graph post is skipped by the Buffer reconcile pass (nothing to reconcile — no queue).

- [x] **Step 2: Run to verify failure**

- [x] **Step 3: Implement** — provider dispatch inside the metrics pass keyed on `provider`/`ig_media_id`; insight metric names normalized to the same lowercase keys the Buffer path stores (probe-verified list, e.g. `views, reach, likes, comments, shares, saved`) so `performance_score`'s views→impressions fallback keeps working across providers.

- [x] **Step 4: Run** — `.venv/bin/python -m pytest api/test_autopilot.py api/test_publishing.py -v` → PASS

- [x] **Step 5: Commit** — `feat(autopilot): first-party insights metrics for graph-published posts`

---

### Task 5b (CONDITIONAL, requires 3b): audio attribution verification in refresh

Extend the status-refresh pass to re-check `media_audio_type` on graph posts that attached audio and surface a mismatch on the dashboard post card (attribution silently reverting to `ORIGINAL_SOUND` means the attach failed).

---

### Task 6: Frontend + docs + deploy

**Files:**
- Modify: `web/src/services/eclypteApi.ts` (PublishingPost fields + config response), `web/src/app/dashboard/page.tsx` (send-mode UI: hide queue/schedule modes when provider is graph — send is "post at next slot"), `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `api/COMMANDS.md`

- [x] **Step 1: Frontend** — surface `publish_provider` from `/v1/publishing/config`; graph mode collapses the ReviewSheet's queue/schedule/now choice into a single "Approve — posts at the next slot" action; copy stays creator-facing (no "Graph API" in UI text). `npm run lint && npm run build` clean.

- [x] **Step 2: Docs** — provider setup + token refresh runbook in `api/COMMANDS.md`; CLAUDE.md/AGENTS/ARCHITECTURE reconciliation (publishing section, env vars, healthz booleans, the Buffer-metrics licensing note gains "graph provider removes this constraint for graph-published posts").

- [x] **Step 3: Full suite** — `.venv/bin/python -m pytest api -v` + web lint/build.

- [x] **Step 4: Deploy checklist (operator)** — set the three graph env vars on Railway; flip `ECLYPTE_PUBLISH_PROVIDER=graph`; run the live veto drill (approve one post, watch the canary fields, verify it lands on the account with the right cover/caption; check Account Status stays clean); calendar the 60-day token refresh.

- [x] **Step 5: Commit** — `feat(publishing): graph provider frontend + runbook`

---

## Deferred (explicitly out of Phase B)

- Trial Reels (`trial_params`) — blocked on ~1,000 followers; revisit at the milestone.
- Collab posts (`collaborators`) — needs manual partner accept; treat as an operator workflow first.
- TikTok / YouTube Shorts cross-posting — separate copyright strategy per spec.
- Buffer removal — keep the provider switch until graph publishing has weeks of clean operation.
