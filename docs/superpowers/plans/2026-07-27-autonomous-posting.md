# Autonomous Pairing & Posting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Autopilot picks film+song pairs itself and sends finished reels to Buffer's queue without manual review, with Buffer's posting schedule as the veto window.

**Architecture:** Two default-off booleans on `AutopilotState` (`auto_pair`, `auto_publish`) gate two new steps inside the existing `run_autopilot_tick` state machine: a replenish step that synthesizes queue items via LRU rotation with exhaustion/recycle tracking, and an auto-send step that pushes `ready`+`auto_created` publishing posts through a shared `send_post_to_buffer` function (extracted from the send-buffer route). Veto = the existing cancel endpoint extended with a Buffer `deletePost` call.

**Tech Stack:** FastAPI + Pydantic v2 (strict models), R2-backed `StorageRepository`, Buffer GraphQL over stdlib urllib, Next.js 16 dashboard, pytest with in-memory fakes.

**Spec:** `docs/superpowers/specs/2026-07-27-autonomous-posting-design.md`

## Global Constraints

- Run backend tests with `.venv/bin/python -m pytest ...` from the repo root (system pythons lack deps).
- Every Pydantic model uses `ConfigDict(extra="forbid")`; ALL new fields must be additive with defaults so persisted R2 JSON keeps loading.
- Autopilot state mutations from API routes go under `AUTOPILOT_STATE_LOCK` (app.py) / `STATE_LOCK` (autopilot.py); the tick already holds it.
- `api/publishing.py` stays stdlib-only for HTTP (urllib, no requests/httpx).
- Frontend verification is `npm run lint` and `npm run build` from `web/`.
- Commit after each task; end commit messages with the repo's Co-Authored-By line only if the session already does so — otherwise plain messages are fine.
- Both new booleans default **off**: with them off, every existing test and behavior must be unchanged.

---

### Task 1: State model fields

**Files:**
- Modify: `api/storage/models.py` (AutopilotItem ~line 187, AutopilotState ~line 210)
- Test: `api/storage/test_models.py`

**Interfaces:**
- Produces: `AutopilotState.auto_pair: bool`, `.auto_publish: bool`, `.last_paired_at: dict[str, str]`, `.exhausted_pairs: list[str]`, `.recycling: bool`, `.waiting_for_library: bool`; `AutopilotItem.auto_paired: bool`. All defaulted; later tasks rely on these exact names.

- [ ] **Step 1: Write the failing test**

Append to `api/storage/test_models.py`:

```python
def test_autopilot_state_autonomy_fields_default_off_and_round_trip():
    # Legacy persisted JSON (no autonomy fields) must load under extra="forbid".
    legacy = AutopilotState.model_validate(
        {"owner_user_id": "u1", "updated_at": "2026-07-27T00:00:00Z"}
    )
    assert legacy.auto_pair is False
    assert legacy.auto_publish is False
    assert legacy.last_paired_at == {}
    assert legacy.exhausted_pairs == []
    assert legacy.recycling is False
    assert legacy.waiting_for_library is False

    state = legacy.model_copy(
        update={
            "auto_pair": True,
            "auto_publish": True,
            "last_paired_at": {"file_a": "2026-07-27T01:00:00Z"},
            "exhausted_pairs": ["file_a::file_b"],
            "recycling": True,
            "waiting_for_library": False,
        }
    )
    reloaded = AutopilotState.model_validate(state.model_dump(mode="json"))
    assert reloaded.last_paired_at == {"file_a": "2026-07-27T01:00:00Z"}
    assert reloaded.exhausted_pairs == ["file_a::file_b"]


def test_autopilot_item_auto_paired_defaults_false():
    item = AutopilotItem(
        item_id="ap_1",
        source_video_file_id="fv",
        source_video_version_id="vv",
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:00Z",
    )
    assert item.auto_paired is False
    assert AutopilotItem.model_validate(item.model_dump(mode="json")).auto_paired is False
```

(`AutopilotState`/`AutopilotItem` are already imported in that test file; add them to the import if not.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest api/storage/test_models.py -v -k autonomy`
Expected: FAIL with `AttributeError: 'AutopilotState' object has no attribute 'auto_pair'`

- [ ] **Step 3: Add the fields**

In `api/storage/models.py`, `AutopilotItem`: after `creative_brief: str = ""` add:

```python
    auto_paired: bool = False
```

In `AutopilotState`: after `daily_target: int = Field(default=3, ge=1, le=10)` add:

```python
    auto_pair: bool = False
    auto_publish: bool = False
    # file_id -> ISO timestamp of the last time replenish paired this asset.
    last_paired_at: dict[str, str] = Field(default_factory=dict)
    # "{video_file_id}::{song_file_id}" keys whose trim windows are all used.
    exhausted_pairs: list[str] = Field(default_factory=list)
    # Stamped by each replenish run (not computed at read time).
    recycling: bool = False
    waiting_for_library: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest api/storage/test_models.py api/test_autopilot.py -v`
Expected: all PASS (existing autopilot tests unaffected — fields are defaulted).

- [ ] **Step 5: Commit**

```bash
git add api/storage/models.py api/storage/test_models.py
git commit -m "feat(autopilot): autonomy fields on AutopilotState/AutopilotItem"
```

---

### Task 2: Extract `send_post_to_buffer` into publishing.py

**Files:**
- Modify: `api/publishing.py` (new exception classes + function, near `prepare_public_media_copy` ~line 501)
- Modify: `api/app.py` (`send_publishing_post_to_buffer` route, lines 1247–1318; `resolve_buffer_channel_id`/`resolve_public_media_base_url` at lines 394–410 stay for the config route but the send route stops using them)
- Test: `api/test_publishing.py`

**Interfaces:**
- Produces (in `api/publishing.py`):
  - `class BufferConfigError(BufferClientError)` — missing env config.
  - `class SendToBufferError(Exception)` with attributes `record: PublishingPostRecord` (the prepared post, public copy already made) and `cause: BufferClientError`.
  - `def send_post_to_buffer(repo, *, store, post, mode, scheduled_at=None, client=None) -> PublishingPostRecord` where `mode` is `"queue" | "schedule" | "now"`. Resolves channel id (`BUFFER_INSTAGRAM_CHANNEL_ID`) and public base URL (`ECLYPTE_R2_PUBLIC_BASE_URL`) from env, raising `BufferConfigError` when missing; maps mode exactly like the current route (`now` → `customScheduled` + `immediate_due_at()`, `schedule` → `customScheduled` + required `scheduled_at`/`post.scheduled_at` else `ValueError`, `queue` → `addToQueue`); calls `prepare_public_media_copy`, then `create_video_post`; on `BufferClientError` raises `SendToBufferError(prepared, exc)` WITHOUT changing the post status; on success saves and returns the record with `status=queue_status_for_mode(mode)`, `buffer_*` fields, `scheduled_at`, `post_url`, `last_error=None`.
  - The `client` parameter defaults to `BufferClient.from_env()` — tests inject fakes.
- Consumed by: the route (this task) and the tick's send callable (Task 6).

- [ ] **Step 1: Write the failing test**

Append to `api/test_publishing.py` (it already has `build_repo`-style helpers, a `FakeBufferClient`-style pattern in the send-buffer tests, and an `InMemoryObjectStore`; reuse the file's existing post-creation helper — the tests around line 300 build a ready post via `create_publish_post_for_render`):

```python
def test_send_post_to_buffer_queue_mode_shared_function(monkeypatch):
    from api.publishing import SendToBufferError, send_post_to_buffer

    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "chan_1")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    repo, store, post = make_ready_post()  # use/extract the existing helper pattern

    class RecordingBufferClient:
        def __init__(self):
            self.calls = []

        def create_video_post(self, **kwargs):
            self.calls.append(kwargs)
            return BufferPostResult(post_id="buf_1", status="added", post_url=None, sent_at=None)

    client = RecordingBufferClient()
    saved = send_post_to_buffer(repo, store=store, post=post, mode="queue", client=client)

    assert saved.status == "queued"
    assert saved.buffer_post_id == "buf_1"
    assert saved.public_media_url and saved.public_media_url.startswith("https://media.example.com/")
    assert client.calls[0]["mode"] == "addToQueue"
    assert client.calls[0]["due_at"] is None


def test_send_post_to_buffer_failure_raises_with_prepared_record(monkeypatch):
    from api.publishing import SendToBufferError, send_post_to_buffer

    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "chan_1")
    monkeypatch.setenv("ECLYPTE_R2_PUBLIC_BASE_URL", "https://media.example.com")
    repo, store, post = make_ready_post()

    class BrokenBufferClient:
        def create_video_post(self, **kwargs):
            raise BufferClientError("buffer down")

    with pytest.raises(SendToBufferError) as excinfo:
        send_post_to_buffer(repo, store=store, post=post, mode="queue", client=BrokenBufferClient())
    # The prepared record (public copy done) is attached; status untouched.
    assert excinfo.value.record.public_media_key
    assert excinfo.value.record.status == "ready"


def test_send_post_to_buffer_missing_config_raises_config_error(monkeypatch):
    from api.publishing import BufferConfigError, send_post_to_buffer

    monkeypatch.delenv("BUFFER_INSTAGRAM_CHANNEL_ID", raising=False)
    repo, store, post = make_ready_post()
    with pytest.raises(BufferConfigError):
        send_post_to_buffer(repo, store=store, post=post, mode="queue", client=object())
```

If `make_ready_post()` doesn't exist yet, extract it from the existing send-buffer API test setup in this file: build `StorageRepository(InMemoryObjectStore())`, publish a render_output artifact, call `create_publish_post_for_render(...)`, return `(repo, store, post)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k send_post_to_buffer`
Expected: FAIL with `ImportError: cannot import name 'send_post_to_buffer'`

- [ ] **Step 3: Implement in `api/publishing.py`**

Add near `prepare_public_media_copy`:

```python
class BufferConfigError(BufferClientError):
    """Buffer publishing is not configured (missing env)."""


class SendToBufferError(Exception):
    """Buffer rejected the send. `record` is the prepared post (public media
    copy already made, status untouched) so callers decide the failure policy."""

    def __init__(self, record: PublishingPostRecord, cause: BufferClientError):
        super().__init__(str(cause))
        self.record = record
        self.cause = cause


def resolve_buffer_channel_id_env() -> str:
    channel_id = os.environ.get("BUFFER_INSTAGRAM_CHANNEL_ID")
    if not channel_id:
        raise BufferConfigError("BUFFER_INSTAGRAM_CHANNEL_ID is not configured")
    return channel_id


def resolve_public_media_base_url_env() -> str:
    base_url = os.environ.get("ECLYPTE_R2_PUBLIC_BASE_URL")
    if not base_url:
        raise BufferConfigError("ECLYPTE_R2_PUBLIC_BASE_URL is not configured")
    return base_url


def send_post_to_buffer(
    repo: StorageRepository,
    *,
    store: ObjectStore,
    post: PublishingPostRecord,
    mode: str,
    scheduled_at: str | None = None,
    client: Any | None = None,
) -> PublishingPostRecord:
    """Shared send path used by the send-buffer route and the autopilot tick.

    Mode mapping mirrors the API contract: "now" -> customScheduled at
    immediate_due_at(); "schedule" -> customScheduled at the given/stored
    scheduled_at; "queue" -> addToQueue (Buffer's posting schedule decides
    when it publishes).
    """
    channel_id = resolve_buffer_channel_id_env()
    public_base_url = resolve_public_media_base_url_env()
    if mode == "now":
        buffer_mode: BufferShareMode = "customScheduled"
        due_at: str | None = immediate_due_at()
    elif mode == "schedule":
        buffer_mode = "customScheduled"
        due_at = scheduled_at or post.scheduled_at
        if not due_at:
            raise ValueError("scheduled_at is required for schedule mode")
    else:
        buffer_mode = "addToQueue"
        due_at = scheduled_at or post.scheduled_at
    prepared = prepare_public_media_copy(
        repo, store=store, post=post, public_base_url=public_base_url
    )
    buffer_client = client if client is not None else BufferClient.from_env()
    try:
        result = buffer_client.create_video_post(
            channel_id=channel_id,
            text=format_post_text(prepared.caption, prepared.hashtags),
            media_url=prepared.public_media_url or "",
            mode=buffer_mode,
            due_at=due_at,
        )
    except BufferClientError as exc:
        raise SendToBufferError(prepared, exc) from exc
    return repo.save_publishing_post(
        prepared.model_copy(
            update={
                "status": queue_status_for_mode(buffer_mode),
                "buffer_channel_id": channel_id,
                "buffer_post_id": result.post_id,
                "buffer_status": result.status,
                "scheduled_at": due_at,
                "post_url": result.post_url,
                "last_error": None,
                "updated_at": _utc_now(),
            }
        )
    )
```

(`ObjectStore` import: `from api.storage.r2_client import ObjectStore` if not already imported; it may need a `TYPE_CHECKING` import to match the file's existing style.)

- [ ] **Step 4: Rewrite the route to use it**

Replace the body of `send_publishing_post_to_buffer` in `api/app.py` (keep the mode/`scheduled_at` request semantics identical):

```python
        post = publishing_post_or_404(repo, uid, post_id)
        if post.status == "canceled":
            raise HTTPException(status_code=400, detail="publishing post is canceled")
        try:
            saved = send_post_to_buffer(
                repo,
                store=resolved_store,
                post=post,
                mode=request.mode,
                scheduled_at=request.scheduled_at,
            )
        except BufferConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SendToBufferError as exc:
            repo.save_publishing_post(
                exc.record.model_copy(
                    update={
                        "status": "failed",
                        "last_error": str(exc),
                        "updated_at": utc_now(),
                    }
                )
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return publishing_post_view(saved, uid, resolved_store)
```

Import `send_post_to_buffer`, `SendToBufferError`, `BufferConfigError` from `api.publishing` at the top of `app.py`. The route no longer calls `resolve_buffer_channel_id`/`resolve_public_media_base_url`/`resolve_buffer_client` — leave those helpers in place (the config/diagnostics route still uses them).

- [ ] **Step 5: Run the full publishing + API suites**

Run: `.venv/bin/python -m pytest api/test_publishing.py api/test_api_v1.py -v`
Expected: all PASS — the existing send-buffer API tests are the parity check for the extraction (same statuses, same 502/503 behavior, same Buffer payloads).

- [ ] **Step 6: Commit**

```bash
git add api/publishing.py api/app.py api/test_publishing.py
git commit -m "refactor(publishing): extract shared send_post_to_buffer from the send-buffer route"
```

---

### Task 3: Buffer deletePost + veto in the cancel route

**Files:**
- Modify: `api/publishing.py` (payload builder + `BufferClient.delete_post` after `get_post`, ~line 103)
- Modify: `api/app.py` (`cancel_publishing_post`, lines 1353–1370)
- Test: `api/test_publishing.py`

**Interfaces:**
- Produces: `build_buffer_delete_post_payload(*, post_id: str) -> dict`, `BufferClient.delete_post(*, post_id: str) -> None` (raises `BufferClientError` on any error shape).
- Cancel route contract: posts with `buffer_post_id` AND `status in {"queued", "scheduled"}` delete from Buffer first (502 on failure, post untouched); all other posts cancel locally as today.

**Note:** The exact mutation shape must be confirmed against Buffer's live GraphQL schema during this task (the spec flags this). Start from the shape below (mirrors `createPost`/`post` conventions in this file); if introspection shows a different name/response, adjust builder + parser + tests together in this task.

- [ ] **Step 1: Verify the mutation name against Buffer's schema**

Run (uses the real API key from Railway env or your local shell; skip and trust the fallback if unavailable):

```bash
curl -s https://api.buffer.com -H "Authorization: Bearer $BUFFER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __type(name: \"Mutation\") { fields { name } } }"}' | python3 -m json.tool | grep -i -A1 delet
```

Expected: a mutation field named `deletePost` (or similar — e.g. `postDelete`). Use whatever the schema actually names it in the code below.

- [ ] **Step 2: Write the failing tests**

Append to `api/test_publishing.py`:

```python
def test_delete_post_payload_and_parsing():
    from api.publishing import BufferClient, build_buffer_delete_post_payload

    payload = build_buffer_delete_post_payload(post_id="buf_1")
    assert payload["variables"]["input"]["id"] == "buf_1"
    assert "deletePost" in payload["query"]

    client = BufferClient(api_key="k")
    client._graphql = lambda p: {"data": {"deletePost": {"success": True}}}
    client.delete_post(post_id="buf_1")  # no raise

    client._graphql = lambda p: {"errors": [{"message": "not found"}]}
    with pytest.raises(BufferClientError):
        client.delete_post(post_id="buf_1")


def test_cancel_queued_post_deletes_from_buffer():
    # API-level: a queued post with a buffer_post_id is deleted in Buffer, then
    # canceled locally; an unsent ready post cancels without touching Buffer.
    client_calls = []

    class FakeBufferClient:
        def delete_post(self, *, post_id):
            client_calls.append(post_id)

    app_client, repo, store = build_publishing_test_app(buffer_client=FakeBufferClient())
    queued = save_queued_post(repo, buffer_post_id="buf_9")  # helper: ready post flipped to queued
    response = app_client.post(
        f"/v1/publishing/posts/{queued.post_id}/cancel", headers={"X-User-Id": USER}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    assert client_calls == ["buf_9"]
```

Adapt `build_publishing_test_app`/`save_queued_post` to this file's existing app-construction helpers (the send-buffer API tests already build a TestClient with an injected fake Buffer client — follow that exact pattern; if injection is via `create_app(buffer_client=...)` or monkeypatching `resolve_buffer_client`, mirror the existing tests').

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k "delete_post or cancel_queued"`
Expected: FAIL with `ImportError: cannot import name 'build_buffer_delete_post_payload'`

- [ ] **Step 4: Implement builder + client method**

In `api/publishing.py` after `build_buffer_get_post_payload`:

```python
def build_buffer_delete_post_payload(*, post_id: str) -> dict[str, Any]:
    return {
        "query": """
            mutation DeletePost($input: DeletePostInput!) {
              deletePost(input: $input) {
                ... on PostActionSuccess { success }
                ... on MutationError { message }
              }
            }
        """,
        "variables": {"input": {"id": post_id}},
    }
```

In `BufferClient` after `get_post`:

```python
    def delete_post(self, *, post_id: str) -> None:
        response = self._graphql(build_buffer_delete_post_payload(post_id=post_id))
        if response.get("errors"):
            raise BufferClientError(_first_error_message(response["errors"]))
        result = response.get("data", {}).get("deletePost")
        if not isinstance(result, dict):
            raise BufferClientError("Buffer did not return a deletePost result")
        if result.get("message"):
            raise BufferClientError(str(result["message"]))
```

(Adjust the query/fragments to whatever Step 1 found; keep the three-way error handling shape.)

- [ ] **Step 5: Extend the cancel route**

In `api/app.py`, `cancel_publishing_post` — before the local save:

```python
        post = publishing_post_or_404(repo, uid, post_id)
        if post.buffer_post_id and post.status in {"queued", "scheduled"}:
            client = resolve_buffer_client()
            try:
                client.delete_post(post_id=post.buffer_post_id)
            except BufferClientError as exc:
                # Veto failed: leave the post queued and visible rather than
                # marking it canceled while Buffer still holds it.
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        saved = repo.save_publishing_post(
            ...  # existing canceled model_copy, unchanged
        )
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add api/publishing.py api/app.py api/test_publishing.py
git commit -m "feat(publishing): Buffer deletePost + veto-cancel for queued posts"
```

---

### Task 4: Pure pair selection (`select_next_pair`)

**Files:**
- Modify: `api/autopilot.py` (new pure helpers near `combo_key`, ~line 58)
- Test: `api/test_autopilot.py`

**Interfaces:**
- Produces:
  - `def pair_key(video_file_id: str, song_file_id: str) -> str` → `"{video}::{song}"`.
  - `@dataclass(frozen=True) class PairSelection: video: dict[str, str]; song: dict[str, str]; recycled: bool` (dicts are `{"file_id": ..., "version_id": ...}`).
  - `def select_next_pair(films, songs, *, last_paired_at, exhausted_pairs) -> PairSelection | None` — films/songs are lists of `{"file_id", "version_id"}` dicts; LRU order by `last_paired_at.get(file_id, "")` (missing → first) with `file_id` as tiebreak; returns the first pairing not in `exhausted_pairs` with `recycled=False`; if every pairing is exhausted, returns the pairing minimizing `max(last_paired_at of the two assets)` with `recycled=True`; returns `None` when either list is empty.

- [ ] **Step 1: Write the failing tests**

Append to `api/test_autopilot.py`:

```python
from api.autopilot import pair_key, select_next_pair


def _asset(file_id):
    return {"file_id": file_id, "version_id": f"v_{file_id}"}


def test_select_next_pair_prefers_least_recently_used():
    films = [_asset("f_new"), _asset("f_old")]
    songs = [_asset("s_new"), _asset("s_old")]
    last = {
        "f_new": "2026-07-27T10:00:00Z",
        "s_new": "2026-07-27T10:00:00Z",
        # f_old / s_old never paired -> sort first
    }
    pick = select_next_pair(films, songs, last_paired_at=last, exhausted_pairs=[])
    assert pick.video["file_id"] == "f_old"
    assert pick.song["file_id"] == "s_old"
    assert pick.recycled is False


def test_select_next_pair_skips_exhausted_pairs():
    films, songs = [_asset("f1")], [_asset("s1"), _asset("s2")]
    pick = select_next_pair(
        films, songs, last_paired_at={}, exhausted_pairs=[pair_key("f1", "s1")]
    )
    assert (pick.video["file_id"], pick.song["file_id"]) == ("f1", "s2")


def test_select_next_pair_recycles_least_recent_when_all_exhausted():
    films, songs = [_asset("f1"), _asset("f2")], [_asset("s1")]
    exhausted = [pair_key("f1", "s1"), pair_key("f2", "s1")]
    last = {
        "f1": "2026-07-20T00:00:00Z",
        "f2": "2026-07-26T00:00:00Z",
        "s1": "2026-07-26T00:00:00Z",
    }
    pick = select_next_pair(films, songs, last_paired_at=last, exhausted_pairs=exhausted)
    assert pick.recycled is True
    assert pick.video["file_id"] == "f1"  # max(f1, s1) < max(f2, s1) tie-broken by key


def test_select_next_pair_empty_library_returns_none():
    assert select_next_pair([], [_asset("s1")], last_paired_at={}, exhausted_pairs=[]) is None
    assert select_next_pair([_asset("f1")], [], last_paired_at={}, exhausted_pairs=[]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k select_next_pair`
Expected: FAIL with `ImportError: cannot import name 'pair_key'`

- [ ] **Step 3: Implement**

In `api/autopilot.py` (add `from dataclasses import dataclass` to imports):

```python
def pair_key(video_file_id: str, song_file_id: str) -> str:
    return f"{video_file_id}::{song_file_id}"


@dataclass(frozen=True)
class PairSelection:
    video: dict[str, str]
    song: dict[str, str]
    recycled: bool


def select_next_pair(
    films: list[dict[str, str]],
    songs: list[dict[str, str]],
    *,
    last_paired_at: dict[str, str],
    exhausted_pairs: list[str],
) -> PairSelection | None:
    """LRU rotation: least-recently-paired film x song, skipping exhausted
    pairs; when everything is exhausted, recycle the least-recently-paired
    pairing (caller clears its window dedupe)."""
    if not films or not songs:
        return None

    def lru(assets: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(
            assets, key=lambda a: (last_paired_at.get(a["file_id"], ""), a["file_id"])
        )

    films_lru, songs_lru = lru(films), lru(songs)
    exhausted = set(exhausted_pairs)
    for film in films_lru:
        for song in songs_lru:
            if pair_key(film["file_id"], song["file_id"]) not in exhausted:
                return PairSelection(video=film, song=song, recycled=False)

    def pair_recency(film: dict[str, str], song: dict[str, str]) -> tuple[str, str]:
        stamps = (
            last_paired_at.get(film["file_id"], ""),
            last_paired_at.get(song["file_id"], ""),
        )
        return (max(stamps), pair_key(film["file_id"], song["file_id"]))

    film, song = min(
        ((f, s) for f in films_lru for s in songs_lru),
        key=lambda pair: pair_recency(*pair),
    )
    return PairSelection(video=film, song=song, recycled=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k select_next_pair`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/autopilot.py api/test_autopilot.py
git commit -m "feat(autopilot): pure LRU pair selection with exhaustion + recycle"
```

---

### Task 5: Replenish step in the tick

**Files:**
- Modify: `api/autopilot.py` (`_run_tick_locked` — replenish before the start-new-work loop, ~line 380; `start_trimmed_edit`'s no-window branch ~line 281)
- Test: `api/test_autopilot.py`

**Interfaces:**
- Consumes: Task 1 fields, Task 4 `select_next_pair`/`pair_key`.
- Produces: tick behavior — when `state.auto_pair` and not halted and no `pending` item and `in_flight + packaged_today < daily_target`: lists non-archived assets with a `current_version_id` from `repo.list_file_manifests(user_id)` (kinds `source_video` / `song_audio`), synthesizes ONE `AutopilotItem` (`auto_paired=True`, empty brief, `item_id=f"ap_{secrets.token_hex(6)}"`), stamps `last_paired_at` for both file_ids with `now_iso`, and stamps `waiting_for_library`/`recycling` booleans on state every replenish evaluation. On recycle: removes the pair's entries from `used_combos` (prefix `f"{video}|{song}|"`) and from `exhausted_pairs`. The no-window failure in `start_trimmed_edit` additionally appends `pair_key(...)` to `exhausted_pairs`.

- [ ] **Step 1: Write the failing tests**

Append to `api/test_autopilot.py`. First a small asset helper (place near `build_repo`):

```python
from api.storage.refs import FileRef


def publish_asset(repo, *, file_id, kind, name="asset"):
    file_ref = FileRef(user_id=USER, file_id=file_id)
    repo.create_file_manifest(file_ref=file_ref, kind=kind, display_name=name)
    version_ref = repo.publish_bytes(
        file_ref=file_ref,
        body=b"data",
        content_type="application/octet-stream",
        original_filename=name,
        created_by_step="test",
        derived_from_step="test",
        input_file_version_ids=[],
    )
    return {"file_id": file_id, "version_id": version_ref.version_id}
```

Then the tests:

```python
def test_auto_pair_replenishes_one_item_and_stamps_lru():
    repo = build_repo()
    starts = RecordingStarts()
    publish_asset(repo, file_id="f_film", kind="source_video", name="film.mp4")
    song = publish_asset(repo, file_id="f_song", kind="song_audio", name="song.wav")
    save_state(repo, auto_pair=True)

    state = tick(repo, starts)

    assert len(state.items) == 1
    item = state.items[0]
    assert item.auto_paired is True
    assert item.source_video_file_id == "f_film"
    assert item.song_file_id == "f_song"
    # The synthesized item was consumed by start-new-work in the same tick:
    # no analysis exists, so it should now be analyzing.
    assert item.status == "analyzing"
    assert starts.analysis_calls[0][1] == song
    assert set(state.last_paired_at) == {"f_film", "f_song"}
    assert state.waiting_for_library is False


def test_auto_pair_waits_for_library_when_empty():
    repo = build_repo()
    starts = RecordingStarts()
    publish_asset(repo, file_id="f_film", kind="source_video")  # no songs
    save_state(repo, auto_pair=True)

    state = tick(repo, starts)

    assert state.items == []
    assert state.waiting_for_library is True
    assert state.halted_reason is None


def test_auto_pair_skips_when_pending_item_exists():
    repo = build_repo()
    starts = RecordingStarts()
    publish_asset(repo, file_id="f_film", kind="source_video")
    publish_asset(repo, file_id="f_song", kind="song_audio")
    save_state(repo, auto_pair=True, items=[make_item(status="pending")])

    state = tick(repo, starts)

    # The manual pending item is consumed; replenish did not add a second.
    assert len(state.items) == 1
    assert state.items[0].auto_paired is False


def test_no_window_failure_marks_pair_exhausted():
    repo = build_repo()
    starts = RecordingStarts()
    _complete_analysis_run(repo)  # existing helper: analysis for v_song
    # Mark every window for the default analysis as used (existing test
    # pattern: seed used_combos from select_trim_windows output).
    from api.autopilot import combo_key, select_trim_windows
    analysis = DEFAULT_ANALYSIS  # reuse whatever _complete_analysis_run publishes
    used = [
        combo_key("file_video", "file_song", w) for w in select_trim_windows(analysis)
    ]
    save_state(repo, items=[make_item()], used_combos=used)

    state = tick(repo, starts)

    assert state.items[0].status == "failed"
    assert "already used" in (state.items[0].last_error or "")
    assert "file_video::file_song" in state.exhausted_pairs


def test_auto_pair_recycles_when_all_pairs_exhausted():
    repo = build_repo()
    starts = RecordingStarts()
    publish_asset(repo, file_id="f_film", kind="source_video")
    publish_asset(repo, file_id="f_song", kind="song_audio")
    save_state(
        repo,
        auto_pair=True,
        exhausted_pairs=["f_film::f_song"],
        used_combos=["f_film|f_song|0", "f_film|f_song|25"],
        last_paired_at={"f_film": "2026-07-20T00:00:00Z", "f_song": "2026-07-20T00:00:00Z"},
    )

    state = tick(repo, starts)

    assert state.recycling is True
    assert state.exhausted_pairs == []
    assert all(not c.startswith("f_film|f_song|") for c in state.used_combos)
    assert len(state.items) == 1 and state.items[0].auto_paired is True


def test_halt_stops_replenish():
    repo = build_repo()
    starts = RecordingStarts()
    publish_asset(repo, file_id="f_film", kind="source_video")
    publish_asset(repo, file_id="f_song", kind="song_audio")
    save_state(repo, auto_pair=True, halted_reason="halted for test")

    state = tick(repo, starts)

    assert state.items == []
```

Adapt `DEFAULT_ANALYSIS` / `_complete_analysis_run` usage to the helpers as they actually exist in the file (read them first; `test_no_window_failure_marks_pair_exhausted` should mirror the existing `test_tick_fails_item_when_every_window_used`-style test if present — extend that test instead of duplicating setup if cleaner).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k "auto_pair or exhausted"`
Expected: FAIL (`waiting_for_library` stays False / no items synthesized / no exhausted_pairs append).

- [ ] **Step 3: Implement in `_run_tick_locked`**

Add `import secrets` to autopilot.py's imports. Track new state pieces alongside the existing locals (after `consecutive_failures = state.consecutive_failures`):

```python
    exhausted_pairs = list(state.exhausted_pairs)
    last_paired_at = dict(state.last_paired_at)
    recycling = state.recycling
    waiting_for_library = state.waiting_for_library
```

In `start_trimmed_edit`, extend the no-window branch (keep `count_failure=False`):

```python
        if window is None:
            if item.song_file_id:
                key = pair_key(item.source_video_file_id, item.song_file_id)
                if key not in exhausted_pairs:
                    exhausted_pairs.append(key)
            return fail_item(
                item,
                "every trim window for this video/song pair was already used",
                count_failure=False,
            )
```

Insert the replenish step between the halt computation and the start-new-work loop:

```python
    # Replenish: synthesize one queue item when auto-pair is on and there is
    # capacity but nothing pending. Runs before start-new-work so the
    # synthesized item is consumed this same tick.
    if halted_reason is None and state.auto_pair:
        has_pending = any(item.status == "pending" for item in items)
        in_flight = sum(1 for item in items if item.status in ACTIVE_ITEM_STATUSES)
        packaged_today = packaged_counts.get(today, 0)
        if not has_pending and in_flight + packaged_today < state.daily_target:
            films, songs = _list_pairable_assets(repo, user_id=user_id)
            waiting_for_library = not films or not songs
            pick = select_next_pair(
                films, songs,
                last_paired_at=last_paired_at,
                exhausted_pairs=exhausted_pairs,
            )
            recycling = bool(pick and pick.recycled)
            if pick is not None:
                if pick.recycled:
                    prefix = f"{pick.video['file_id']}|{pick.song['file_id']}|"
                    used_combos = [c for c in used_combos if not c.startswith(prefix)]
                    key = pair_key(pick.video["file_id"], pick.song["file_id"])
                    exhausted_pairs = [k for k in exhausted_pairs if k != key]
                last_paired_at[pick.video["file_id"]] = now_iso
                last_paired_at[pick.song["file_id"]] = now_iso
                items.append(
                    AutopilotItem(
                        item_id=f"ap_{secrets.token_hex(6)}",
                        source_video_file_id=pick.video["file_id"],
                        source_video_version_id=pick.video["version_id"],
                        song_file_id=pick.song["file_id"],
                        song_version_id=pick.song["version_id"],
                        auto_paired=True,
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
                )
```

Module-level helper (near `_edit_title`):

```python
def _list_pairable_assets(
    repo: StorageRepository, *, user_id: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    films: list[dict[str, str]] = []
    songs: list[dict[str, str]] = []
    for manifest in repo.list_file_manifests(user_id):
        if manifest.archived_at is not None or not manifest.current_version_id:
            continue
        entry = {"file_id": manifest.file_id, "version_id": manifest.current_version_id}
        if manifest.kind == "source_video":
            films.append(entry)
        elif manifest.kind == "song_audio":
            songs.append(entry)
    return films, songs
```

Prune `last_paired_at` opportunistically (spec) inside the replenish branch, right after `_list_pairable_assets` returns, where `films`/`songs` are in scope:

```python
            known = {a["file_id"] for a in films + songs}
            last_paired_at = {k: v for k, v in last_paired_at.items() if k in known}
```

Then add the new fields to the final `state.model_copy(update={...})`:

```python
            "exhausted_pairs": exhausted_pairs,
            "last_paired_at": last_paired_at,
            "recycling": recycling,
            "waiting_for_library": waiting_for_library,
```

(When `auto_pair` is off nothing prunes — harmless.)

- [ ] **Step 4: Run the autopilot suite**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v`
Expected: all PASS, including every pre-existing tick test (auto_pair defaults off).

- [ ] **Step 5: Commit**

```bash
git add api/autopilot.py api/test_autopilot.py
git commit -m "feat(autopilot): auto-pair replenish step with exhaustion + recycle"
```

---

### Task 6: Auto-send step in the tick + app wiring

**Files:**
- Modify: `api/autopilot.py` (`SendReadyPost` protocol, tick signature, auto-send step after the advance loop)
- Modify: `api/app.py` (`autopilot_callables` returns a third callable; tick route + `_autopilot_tick_all_users` pass it)
- Test: `api/test_autopilot.py`

**Interfaces:**
- Produces (autopilot.py):
  - `class SendReadyPost(Protocol): def __call__(self, user_id: str, *, post: "PublishingPostRecord") -> "PublishingPostRecord": ...`
  - `run_autopilot_tick(..., send_ready_post: SendReadyPost | None = None)` (threaded through `_run_tick_locked`). Backward compatible — existing callers/tests unchanged.
  - `AUTO_SEND_RETRY_BACKOFF_SEC = 1800` module constant.
  - Auto-send rules: runs when `state.auto_publish` and `send_ready_post` is not None and not halted; targets `repo.list_publishing_posts(user_id, status="ready")` filtered to `auto_created=True`; skipped entirely when `len(repo.list_publishing_posts(user_id, status="queued")) > 2 * state.daily_target`; a post whose `last_error` is set AND whose `updated_at` is within `AUTO_SEND_RETRY_BACKOFF_SEC` of now is skipped (failure backoff — a fresh error-free package sends immediately); the callable never raises (app wiring catches).
- Produces (app.py): `autopilot_callables` returns `(start_music_analysis, start_edit, send_ready_post)` where `send_ready_post` calls `send_post_to_buffer(repo, store=..., post=post, mode="queue")`, catching `SendToBufferError` (save `last_error` on `exc.record`, keep status) and `BufferClientError`/config errors (save `last_error` on the post) — always returning the saved record.

- [ ] **Step 1: Write the failing tests**

Append to `api/test_autopilot.py`. Extend the `tick()` helper with an optional param:

```python
def tick(repo, starts, send=None):
    return run_autopilot_tick(
        repo,
        user_id=USER,
        start_music_analysis=starts.start_music_analysis,
        start_edit=starts.start_edit,
        send_ready_post=send,
        now=NOW,
    )
```

Post helpers + tests:

```python
from api.storage.models import PublishingPostRecord


def save_post(repo, *, post_id, status="ready", auto_created=True, last_error=None,
              updated_at="2026-06-09T11:00:00Z"):
    return repo.save_publishing_post(
        PublishingPostRecord(
            post_id=post_id,
            owner_user_id=USER,
            render_file_id=f"rf_{post_id}",
            render_version_id=f"rv_{post_id}",
            status=status,
            auto_created=auto_created,
            last_error=last_error,
            created_at="2026-06-09T11:00:00Z",
            updated_at=updated_at,
        )
    )
```

(Check `PublishingPostRecord`'s required fields in `api/storage/models.py` and fill any other non-defaulted ones — e.g. `render_display_name`/`caption` — with simple literals.)

```python
class RecordingSend:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, user_id, *, post):
        self.calls.append(post.post_id)
        return post.model_copy(update={"status": "queued"})


def test_auto_publish_sends_ready_auto_created_posts():
    repo = build_repo()
    starts = RecordingStarts()
    send = RecordingSend()
    save_post(repo, post_id="p_auto")
    save_post(repo, post_id="p_manual", auto_created=False)
    save_state(repo, auto_publish=True)

    tick(repo, starts, send=send)

    assert send.calls == ["p_auto"]  # manual packages stay review-gated


def test_auto_publish_off_sends_nothing():
    repo = build_repo()
    send = RecordingSend()
    save_post(repo, post_id="p_auto")
    save_state(repo)  # auto_publish defaults False

    tick(repo, RecordingStarts(), send=send)

    assert send.calls == []


def test_auto_publish_backoff_skips_recently_failed_post():
    repo = build_repo()
    send = RecordingSend()
    # Failed 5 minutes before NOW -> inside the 30-min backoff.
    save_post(repo, post_id="p_recent", last_error="buffer down",
              updated_at="2026-06-09T11:55:00Z")
    # Failed long ago -> retried.
    save_post(repo, post_id="p_stale", last_error="buffer down",
              updated_at="2026-06-09T09:00:00Z")
    save_state(repo, auto_publish=True)

    tick(repo, RecordingStarts(), send=send)

    assert send.calls == ["p_stale"]


def test_auto_publish_backstop_skips_when_queue_is_deep():
    repo = build_repo()
    send = RecordingSend()
    save_post(repo, post_id="p_ready")
    for i in range(7):  # > 2 * daily_target (3)
        save_post(repo, post_id=f"p_q{i}", status="queued")
    save_state(repo, auto_publish=True)

    tick(repo, RecordingStarts(), send=send)

    assert send.calls == []
```

(`NOW` is `2026-06-09T12:00:00Z` in this file — the backoff timestamps above are relative to it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k auto_publish`
Expected: FAIL with `TypeError: run_autopilot_tick() got an unexpected keyword argument 'send_ready_post'`

- [ ] **Step 3: Implement the tick step**

In `api/autopilot.py`: add the protocol + constant near `StartEdit`:

```python
class SendReadyPost(Protocol):
    def __call__(self, user_id: str, *, post: "PublishingPostRecord") -> "PublishingPostRecord": ...


AUTO_SEND_RETRY_BACKOFF_SEC = 1800
```

(Import `PublishingPostRecord` from `api.storage.models`.) Thread `send_ready_post: SendReadyPost | None = None` through `run_autopilot_tick` → `_run_tick_locked`. Insert the step right after the advance-in-flight loop (before the halt computation), so packages created this tick send this tick:

```python
    # Auto-publish: push ready auto-created packages into Buffer's queue.
    # Buffer's channel posting schedule decides when each actually posts; the
    # gap until that slot is the human veto window.
    if state.auto_publish and send_ready_post is not None and state.halted_reason is None:
        queued_count = len(repo.list_publishing_posts(user_id, status="queued"))
        if queued_count <= 2 * state.daily_target:
            for post in repo.list_publishing_posts(user_id, status="ready"):
                if not post.auto_created:
                    continue
                if post.last_error and _within_backoff(post.updated_at, now_dt):
                    continue
                send_ready_post(user_id, post=post)
```

Module-level helper:

```python
def _within_backoff(updated_at: str, now_dt: datetime) -> bool:
    try:
        stamped = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return (now_dt - stamped).total_seconds() < AUTO_SEND_RETRY_BACKOFF_SEC
```

- [ ] **Step 4: Run the autopilot suite**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire the real callable in `api/app.py`**

Extend `autopilot_callables` (line ~767) to build and return a third callable. It needs an object store: change the signature to `autopilot_callables(repo, schedule, store)` and update both call sites (`trigger_autopilot_tick` passes `resolved_store`; `_autopilot_tick_all_users` builds one via `from api.storage.factory import get_object_store` — the package `__init__` deliberately re-exports nothing, so use the dotted submodule path, mirroring how `build_background_repository` gets its store):

```python
        def send_ready_post(uid: str, *, post: PublishingPostRecord) -> PublishingPostRecord:
            try:
                return send_post_to_buffer(repo, store=store, post=post, mode="queue")
            except SendToBufferError as exc:
                logger.warning("autopilot send failed for post %s: %s", post.post_id, exc)
                return repo.save_publishing_post(
                    exc.record.model_copy(
                        update={"last_error": str(exc), "updated_at": utc_now()}
                    )
                )
            except (BufferClientError, ValueError) as exc:
                logger.warning("autopilot send failed for post %s: %s", post.post_id, exc)
                return repo.save_publishing_post(
                    post.model_copy(
                        update={"last_error": str(exc), "updated_at": utc_now()}
                    )
                )

        return start_music_analysis, start_edit, send_ready_post
```

Both tick call sites then pass `send_ready_post=send_ready_post` into `run_autopilot_tick`.

- [ ] **Step 6: Run the API suite**

Run: `.venv/bin/python -m pytest api/test_autopilot.py api/test_api_v1.py -v`
Expected: all PASS (the endpoint flow test in test_autopilot exercises the new wiring).

- [ ] **Step 7: Commit**

```bash
git add api/autopilot.py api/app.py api/test_autopilot.py
git commit -m "feat(autopilot): auto-publish ready packages to Buffer queue from the tick"
```

---

### Task 7: API surface — settings + status response

**Files:**
- Modify: `api/app.py` (`AutopilotUpdateRequest` line ~299, `AutopilotStatusResponse` line ~305, `autopilot_status_response` line ~810, `update_autopilot` line ~1404)
- Test: `api/test_autopilot.py` (the existing `test_autopilot_endpoints_flow` area) or `api/test_api_v1.py`

**Interfaces:**
- Produces: `PATCH /v1/autopilot` accepts `auto_pair: bool | None` and `auto_publish: bool | None`; the status response carries `auto_pair`, `auto_publish`, `recycling`, `waiting_for_library` (exact JSON keys the frontend reads in Task 8).

- [ ] **Step 1: Write the failing test**

```python
def test_autopilot_settings_round_trip_autonomy_flags():
    # Mirror test_autopilot_endpoints_flow's app construction exactly (it
    # imports create_app and RecordingWorkflowRunner from api.test_api_v1).
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.test_api_v1 import RecordingWorkflowRunner

    store = InMemoryObjectStore()
    app = create_app(store=store, workflow_runner=RecordingWorkflowRunner())
    client = TestClient(app)
    headers = {"X-User-Id": USER}

    response = client.patch(
        "/v1/autopilot", headers=headers,
        json={"enabled": True, "auto_pair": True, "auto_publish": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["auto_pair"] is True
    assert body["auto_publish"] is True
    assert body["recycling"] is False
    assert body["waiting_for_library"] is False

    # Flags persist and can be turned off independently.
    response = client.patch("/v1/autopilot", headers=headers, json={"auto_publish": False})
    body = response.json()
    assert body["auto_pair"] is True
    assert body["auto_publish"] is False
```

(Mirror the existing `test_autopilot_endpoints_flow` construction — if `create_app` requires a runner argument shape, copy it from that test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k settings_round_trip`
Expected: FAIL (422 unknown field or KeyError `auto_pair`).

- [ ] **Step 3: Implement**

`AutopilotUpdateRequest` — add:

```python
    auto_pair: bool | None = None
    auto_publish: bool | None = None
```

`update_autopilot` — add before the save:

```python
            if request.auto_pair is not None:
                update["auto_pair"] = request.auto_pair
            if request.auto_publish is not None:
                update["auto_publish"] = request.auto_publish
```

`AutopilotStatusResponse` — add:

```python
    auto_pair: bool
    auto_publish: bool
    recycling: bool
    waiting_for_library: bool
```

`autopilot_status_response` — add to the constructor:

```python
            auto_pair=state.auto_pair,
            auto_publish=state.auto_publish,
            recycling=state.recycling,
            waiting_for_library=state.waiting_for_library,
```

- [ ] **Step 4: Run the suites**

Run: `.venv/bin/python -m pytest api/test_autopilot.py api/test_api_v1.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app.py api/test_autopilot.py
git commit -m "feat(api): autopilot auto_pair/auto_publish settings + status flags"
```

---

### Task 8: Frontend — switches, labels, veto copy

**Files:**
- Modify: `web/src/services/eclypteApi.ts` (`AutopilotStatus` ~line 167, `AutopilotItem` ~line 172, `updateAutopilot` ~line 433)
- Modify: `web/src/app/dashboard/page.tsx` (autopilot controls ~lines 215–280, `WorkingRow`/queue rows, ReviewSheet queued-state copy)

**Interfaces:**
- Consumes: Task 7's JSON keys.
- Produces: UI only — no new exported symbols.

- [ ] **Step 1: Extend the API client types**

In `eclypteApi.ts` — `AutopilotStatus` gains:

```typescript
    auto_pair: boolean
    auto_publish: boolean
    recycling: boolean
    waiting_for_library: boolean
```

`AutopilotItem` gains `auto_paired: boolean`. `updateAutopilot` input and body gain the flags:

```typescript
    async updateAutopilot(
        input: {
            enabled?: boolean
            dailyTarget?: number
            clearHalt?: boolean
            autoPair?: boolean
            autoPublish?: boolean
        },
        signal?: AbortSignal,
    ) {
        return this.request<AutopilotStatus>("/v1/autopilot", {
            method: "PATCH",
            body: JSON.stringify({
                enabled: input.enabled,
                daily_target: input.dailyTarget,
                clear_halt: input.clearHalt ?? false,
                auto_pair: input.autoPair,
                auto_publish: input.autoPublish,
            }),
            signal,
        })
    }
```

- [ ] **Step 2: Add the two switches to the Home autopilot controls**

In `page.tsx`, extend `updateSettings`'s input type with `autoPair?: boolean; autoPublish?: boolean` (it already forwards the whole object to `api.updateAutopilot`). Next to the existing enable switch (the `styles.switchButton` block ~line 252), add two more switches following the identical pattern:

```tsx
    <button
        type="button"
        role="switch"
        className={`${styles.switchButton} ${autopilot?.auto_pair ? styles.switchButtonOn : ""}`}
        aria-checked={Boolean(autopilot?.auto_pair)}
        aria-label="Pick pairs for me"
        onClick={() => updateSettings({ autoPair: !autopilot?.auto_pair })}
    >
        Pick pairs for me
    </button>
    <button
        type="button"
        role="switch"
        className={`${styles.switchButton} ${autopilot?.auto_publish ? styles.switchButtonOn : ""}`}
        aria-checked={Boolean(autopilot?.auto_publish)}
        aria-label="Post without review"
        onClick={() => updateSettings({ autoPublish: !autopilot?.auto_publish })}
    >
        Post without review
    </button>
```

Match the exact JSX structure/classes of the existing enable switch when placing these (including any wrapping label/row elements the current markup uses — copy its pattern, not just the class names).

- [ ] **Step 3: Status notes + item chip + veto copy**

Under the halt banner block (~line 270), add the two quiet notes:

```tsx
    {autopilot?.waiting_for_library && (
        <p className={styles.mutedNote}>
            Waiting for library content — add a film and a song so autopilot can pair them.
        </p>
    )}
    {autopilot?.recycling && (
        <p className={styles.mutedNote}>
            Recycling your library — add films or songs for fresh combos.
        </p>
    )}
```

(If `styles.mutedNote` doesn't exist, reuse whatever muted/paragraph class the halt banner or empty states already use in `studio.module.css` — do not add new CSS unless nothing fits.)

Queue/working rows: where item titles render (`itemTitle` consumers), append a small chip when `item.auto_paired` is true, reusing the existing badge/chip class used for the "autopilot" label on review cards. In the ReviewSheet, when the displayed post's status is `queued`, show the veto copy near the actions: `Posts at your next Buffer slot — cancel to veto.` and ensure the existing Cancel button remains visible for `queued`/`scheduled` posts (it calls `cancelPublishingPost`, which now performs the Buffer delete server-side).

- [ ] **Step 4: Lint + build**

Run from `web/`: `npm run lint && npm run build`
Expected: 0 errors (the one pre-existing `<img>` warning on the marketing page is fine).

- [ ] **Step 5: Commit**

```bash
git add web/src/services/eclypteApi.ts web/src/app/dashboard/page.tsx
git commit -m "feat(dashboard): autopilot autonomy switches, recycle notes, veto copy"
```

---

### Task 9: Docs + full verification

**Files:**
- Modify: `CLAUDE.md` (autopilot route/description bullets), `AGENTS.md` (autopilot section), `ARCHITECTURE.md` (autopilot flow), `api/COMMANDS.md` (env/notes section)

- [ ] **Step 1: Update the four docs**

Reconcile each doc's autopilot description with: the two new default-off flags on `PATCH /v1/autopilot` (`auto_pair`, `auto_publish`), the replenish step (LRU rotation + exhausted-pair tracking + recycle-after-cooldown), auto-send of ready `auto_created` packages to Buffer's queue (Buffer's channel schedule = posting cadence + veto window; 30-min failure backoff; 2×daily_target queued backstop), the extended cancel (Buffer `deletePost` for queued/scheduled posts), and the new state fields. In `api/COMMANDS.md`, add one line to the Buffer env block noting the operational assumption: the Buffer channel's posting schedule (e.g. 2 slots/day) is configured in Buffer's dashboard and `daily_target` should match.

- [ ] **Step 2: Full backend + frontend verification**

Run: `.venv/bin/python -m pytest api -v` — expected: all pass.
Run from `web/`: `npm run lint && npm run build` — expected: clean.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md AGENTS.md ARCHITECTURE.md api/COMMANDS.md
git commit -m "docs: autonomous pairing + posting flow"
```
