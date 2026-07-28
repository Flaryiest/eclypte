# Performance Feedback Loop (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest per-reel performance from Buffer's post-metrics API and surface it in the dashboard, storing it so Phase 2 (adaptive steering) needs no migration.

**Architecture:** A metrics-refresh pass joins `run_autopilot_tick`'s post-lock phase (sibling of `_auto_send_ready_posts`), polling Buffer's `Post.metrics` for published posts on a 12h cadence via a new `BufferClient.get_post_metrics`, applied through pure helpers (snapshot policy, baseline-relative log-median scoring) in `api/publishing.py`. New fields ride the existing `PublishingPostRecord`/`PublishingPostView`; the Home feed renders a compact metrics line + relative chip.

**Tech Stack:** FastAPI + Pydantic v2 (strict models), Buffer GraphQL over stdlib urllib, R2-backed `StorageRepository`, Next.js 16 dashboard, pytest with in-memory fakes.

**Spec:** `docs/superpowers/specs/2026-07-27-performance-feedback-loop-design.md`

## Global Constraints

- Run backend tests with `.venv/bin/python -m pytest ...` from the repo root (system pythons lack deps).
- Every Pydantic model uses `ConfigDict(extra="forbid")`; ALL new fields additive with defaults so persisted R2 JSON keeps loading.
- `api/publishing.py` stays stdlib-only for HTTP.
- **Absent ≠ 0**: a metric missing from Buffer's response is never stored, rendered, or treated as zero.
- Metrics work NEVER touches `PublishingPostRecord.last_error` (it drives the auto-send backoff) and never counts toward the autopilot halt.
- Build against Buffer's NEW normalized metric names only (legacy types are removed Dec 1, 2026).
- Constants (exact values): `METRICS_REFRESH_INTERVAL_SEC = 43200`, `METRICS_RETENTION_DAYS = 30`, `METRICS_MAX_PER_PASS = 20`. Snapshot cap: keep the FIRST 2 + LAST 10 entries. Score cohort: ≤10 most recent published posts by `posted_at`, minimum 5 to produce a score.
- Dashboard copy is sentence case, creator-facing — no "Buffer", no raw metric enum names in UI text.
- Frontend verification: `npm run lint` && `npm run build` from `web/`.

---

### Task 0: Live probe (attempt) — which metrics does Buffer populate for an IG Reel?

**Files:**
- None committed (findings go into the Task 8 docs step and, if surprising, back into this plan).

- [ ] **Step 1: Attempt the probe**

Only possible where `BUFFER_API_KEY` is set (Railway env or your shell — it is NOT on this dev machine). If unavailable, skip to Step 2's fallback.

```bash
curl -s https://api.buffer.com -H "Authorization: Bearer $BUFFER_API_KEY" \
  -H "Content-Type: application/json" -d '{
  "query": "query Post($input: PostInput!) { post(input: $input) { id metricsUpdatedAt metrics { type name value unit } } }",
  "variables": {"input": {"id": "<a real sent buffer_post_id from R2 post JSON>"}}
}' | python3 -m json.tool
```

Record: which metric `name`s appear for a Reel (floor expectation: impressions/likes/comments; hoped: views/reach/saves/shares/totalTimeWatched), and whether `metricsUpdatedAt` is populated.

- [ ] **Step 2: Record the outcome**

If probed: note the populated names in your report (Task 8 folds them into docs). If NOT probed (no key locally): note that the implementation below is deliberately shape-agnostic (stores whatever names arrive) and add the probe to the deploy checklist in Task 8's docs step. Either way this task produces no commit.

---

### Task 1: Data model — metrics fields + snapshot model + lineage ids

**Files:**
- Modify: `api/storage/models.py` (new `PostMetricsSnapshot` model above `PublishingPostRecord` ~line 151; fields on `PublishingPostRecord`)
- Test: `api/storage/test_models.py`

**Interfaces:**
- Produces: `PostMetricsSnapshot(captured_at: str, metrics: dict[str, float])` (extra="forbid"); `PublishingPostRecord.metrics: dict[str, float] = {}`, `.metrics_updated_at: str | None = None`, `.metrics_checked_at: str | None = None`, `.metrics_history: list[PostMetricsSnapshot] = []`, `.source_video_file_id: str | None = None`, `.song_file_id: str | None = None`. Later tasks rely on these exact names.

- [ ] **Step 1: Write the failing test**

Append to `api/storage/test_models.py` (import `PostMetricsSnapshot`, `PublishingPostRecord` at the top if absent):

```python
def test_publishing_post_metrics_fields_default_empty_and_round_trip():
    legacy = PublishingPostRecord.model_validate(
        {
            "post_id": "pub_1",
            "owner_user_id": "u1",
            "status": "ready",
            "render_file_id": "rf",
            "render_version_id": "rv",
            "render_display_name": "reel.mp4",
            "created_at": "2026-07-27T00:00:00Z",
            "updated_at": "2026-07-27T00:00:00Z",
        }
    )
    assert legacy.metrics == {}
    assert legacy.metrics_updated_at is None
    assert legacy.metrics_checked_at is None
    assert legacy.metrics_history == []
    assert legacy.source_video_file_id is None
    assert legacy.song_file_id is None

    stamped = legacy.model_copy(
        update={
            "metrics": {"views": 1200.0, "likes": 88.0},
            "metrics_updated_at": "2026-07-27T09:00:00Z",
            "metrics_checked_at": "2026-07-27T10:00:00Z",
            "metrics_history": [
                PostMetricsSnapshot(
                    captured_at="2026-07-26T10:00:00Z", metrics={"views": 400.0}
                )
            ],
            "source_video_file_id": "file_film",
            "song_file_id": "file_song",
        }
    )
    reloaded = PublishingPostRecord.model_validate(stamped.model_dump(mode="json"))
    assert reloaded.metrics == {"views": 1200.0, "likes": 88.0}
    assert reloaded.metrics_history[0].metrics == {"views": 400.0}
    assert reloaded.song_file_id == "file_song"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest api/storage/test_models.py -v -k metrics_fields`
Expected: FAIL with `ImportError: cannot import name 'PostMetricsSnapshot'`

- [ ] **Step 3: Implement**

In `api/storage/models.py`, above `PublishingPostRecord`:

```python
class PostMetricsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    captured_at: str
    metrics: dict[str, float]
```

In `PublishingPostRecord`, after `auto_created: bool = False`:

```python
    # Latest per-post performance pulled from the publishing provider. A
    # metric absent from the map was not reported — absent is NOT zero.
    metrics: dict[str, float] = Field(default_factory=dict)
    metrics_updated_at: str | None = None   # provider's ingestion stamp
    metrics_checked_at: str | None = None   # our last poll (cadence control)
    metrics_history: list[PostMetricsSnapshot] = Field(default_factory=list)
    # Lineage ids captured at packaging so Phase 2 attribution never has to
    # walk run manifests.
    source_video_file_id: str | None = None
    song_file_id: str | None = None
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest api/storage/test_models.py api/test_publishing.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/storage/models.py api/storage/test_models.py
git commit -m "feat(publishing): metrics/snapshot/lineage fields on PublishingPostRecord"
```

---

### Task 2: `BufferClient.get_post_metrics`

**Files:**
- Modify: `api/publishing.py` (payload builder near `build_buffer_get_post_payload` ~line 190; client method after `delete_post`)
- Test: `api/test_publishing.py`

**Interfaces:**
- Produces: `build_buffer_post_metrics_payload(*, post_id: str) -> dict`; `BufferClient.get_post_metrics(*, post_id: str) -> tuple[dict[str, float], str | None]` returning `(metrics_by_name, metrics_updated_at)`. Raises `BufferClientError` on errors array / wrong shape. Entries missing `name` or a numeric `value` are skipped (absent ≠ 0). An empty/None `metrics` list returns `({}, updated_at)` — valid (new post, nothing ingested yet).

- [ ] **Step 1: Write the failing test**

Append to `api/test_publishing.py`:

```python
def test_get_post_metrics_payload_and_parse():
    from api.publishing import BufferClient, build_buffer_post_metrics_payload

    payload = build_buffer_post_metrics_payload(post_id="buf_1")
    assert payload["variables"]["input"]["id"] == "buf_1"
    assert "metrics" in payload["query"] and "metricsUpdatedAt" in payload["query"]

    client = BufferClient(api_key="k")
    client._graphql = lambda p: {
        "data": {
            "post": {
                "id": "buf_1",
                "metricsUpdatedAt": "2026-07-27T06:00:00Z",
                "metrics": [
                    {"type": "views", "name": "views", "value": 1234, "unit": "count"},
                    {"type": "likes", "name": "likes", "value": 56, "unit": "count"},
                    {"type": "engagementRate", "name": "engagementRate", "value": None},
                ],
            }
        }
    }
    metrics, updated_at = client.get_post_metrics(post_id="buf_1")
    assert metrics == {"views": 1234.0, "likes": 56.0}  # None value skipped
    assert updated_at == "2026-07-27T06:00:00Z"

    # New post: no metrics ingested yet — empty map, not an error.
    client._graphql = lambda p: {"data": {"post": {"id": "buf_1", "metricsUpdatedAt": None, "metrics": None}}}
    assert client.get_post_metrics(post_id="buf_1") == ({}, None)

    client._graphql = lambda p: {"errors": [{"message": "nope"}]}
    with pytest.raises(BufferClientError):
        client.get_post_metrics(post_id="buf_1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k get_post_metrics`
Expected: FAIL with `ImportError: cannot import name 'build_buffer_post_metrics_payload'`

- [ ] **Step 3: Implement**

Payload builder after `build_buffer_get_post_payload`:

```python
def build_buffer_post_metrics_payload(*, post_id: str) -> dict[str, Any]:
    return {
        "query": """
            query PostMetrics($input: PostInput!) {
              post(input: $input) {
                id
                metricsUpdatedAt
                metrics {
                  type
                  name
                  value
                  unit
                }
              }
            }
        """,
        "variables": {"input": {"id": post_id}},
    }
```

Client method after `delete_post`:

```python
    def get_post_metrics(self, *, post_id: str) -> tuple[dict[str, float], str | None]:
        """Latest normalized metrics for a sent post.

        Only metrics the provider actually reported are returned — an absent
        metric is NOT zero. An empty list just means nothing has been
        ingested yet (metrics arrive ~daily)."""
        response = self._graphql(build_buffer_post_metrics_payload(post_id=post_id))
        if response.get("errors"):
            raise BufferClientError(_first_error_message(response["errors"]))
        post = response.get("data", {}).get("post")
        if not isinstance(post, dict) or not post.get("id"):
            raise BufferClientError("Buffer did not return a post for metrics")
        metrics: dict[str, float] = {}
        for entry in post.get("metrics") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("type")
            value = entry.get("value")
            if not name or not isinstance(value, (int, float)):
                continue
            metrics[str(name)] = float(value)
        return metrics, optional_str(post.get("metricsUpdatedAt"))
```

(`optional_str` already exists in this file.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/publishing.py api/test_publishing.py
git commit -m "feat(publishing): BufferClient.get_post_metrics"
```

---

### Task 3: Pure helpers — `apply_post_metrics` and `performance_score`

**Files:**
- Modify: `api/publishing.py` (near the bottom, after `immediate_due_at`)
- Test: `api/test_publishing.py`

**Interfaces:**
- Consumes: Task 1 fields.
- Produces:
  - `METRICS_HISTORY_HEAD = 2`, `METRICS_HISTORY_TAIL = 10` module constants.
  - `apply_post_metrics(post, *, metrics, metrics_updated_at, now) -> PublishingPostRecord` — pure (no repo): always stamps `metrics_checked_at=now` and `updated_at=now`; when `metrics` is non-empty AND differs from `post.metrics`, replaces `metrics`, sets `metrics_updated_at`, and appends a `PostMetricsSnapshot(captured_at=now, metrics=metrics)` capped to first-2 + last-10; when `metrics` is empty or identical, only the stamps change (empty never clobbers stored values). NEVER touches `last_error` or `status`.
  - `performance_score(post, cohort) -> float | None` — pure: primary = `post.metrics["views"]` if present and > 0 else `post.metrics["impressions"]` if present and > 0 else None; cohort primaries computed the same way per post; requires ≥5 cohort posts with a primary; returns `math.log(primary) - math.log(median(cohort_primaries))`.

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_post_metrics_snapshots_and_stamps():
    from api.publishing import apply_post_metrics

    repo, store, post = make_ready_post()
    now1 = "2026-07-27T10:00:00Z"
    updated = apply_post_metrics(
        post, metrics={"views": 100.0}, metrics_updated_at="2026-07-27T06:00:00Z", now=now1
    )
    assert updated.metrics == {"views": 100.0}
    assert updated.metrics_checked_at == now1
    assert len(updated.metrics_history) == 1
    assert updated.last_error is None and updated.status == post.status

    # Identical values: stamps move, no new snapshot.
    updated2 = apply_post_metrics(
        updated, metrics={"views": 100.0}, metrics_updated_at="2026-07-27T06:00:00Z",
        now="2026-07-27T22:00:00Z",
    )
    assert len(updated2.metrics_history) == 1
    assert updated2.metrics_checked_at == "2026-07-27T22:00:00Z"

    # Empty response never clobbers stored values.
    updated3 = apply_post_metrics(
        updated2, metrics={}, metrics_updated_at=None, now="2026-07-28T10:00:00Z"
    )
    assert updated3.metrics == {"views": 100.0}
    assert updated3.metrics_history == updated2.metrics_history


def test_apply_post_metrics_history_cap_keeps_head_and_tail():
    from api.publishing import apply_post_metrics

    repo, store, post = make_ready_post()
    for i in range(15):
        post = apply_post_metrics(
            post, metrics={"views": float(i + 1)}, metrics_updated_at=None,
            now=f"2026-07-{10 + i:02d}T00:00:00Z",
        )
    history = post.metrics_history
    assert len(history) == 12
    assert history[0].metrics == {"views": 1.0}   # head preserved
    assert history[1].metrics == {"views": 2.0}
    assert history[-1].metrics == {"views": 15.0}  # tail is most recent


def test_performance_score_log_median_and_cold_start():
    import math
    from api.publishing import performance_score

    def scored_post(views):
        _, _, p = make_ready_post()
        return p.model_copy(update={"metrics": {"views": float(views)}})

    cohort = [scored_post(v) for v in (100, 100, 100, 100, 100)]
    target = scored_post(200)
    score = performance_score(target, cohort)
    assert score is not None and abs(score - math.log(2.0)) < 1e-9

    assert performance_score(target, cohort[:4]) is None      # <5 scored posts
    _, _, bare = make_ready_post()
    assert performance_score(bare, cohort) is None            # no primary metric

    fallback = bare.model_copy(update={"metrics": {"impressions": 100.0}})
    assert performance_score(fallback, cohort) is not None    # impressions fallback
```

(`make_ready_post()` exists in this file; each call builds an isolated repo+post. If it returns colliding post_ids across calls within one test, adapt using its internals — the helpers under test are pure, so only the records matter.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k "apply_post_metrics or performance_score"`
Expected: FAIL with `ImportError: cannot import name 'apply_post_metrics'`

- [ ] **Step 3: Implement**

```python
METRICS_HISTORY_HEAD = 2   # earliest readings ≈ the ~24h provisional
METRICS_HISTORY_TAIL = 10  # the settle curve


def apply_post_metrics(
    post: PublishingPostRecord,
    *,
    metrics: dict[str, float],
    metrics_updated_at: str | None,
    now: str,
) -> PublishingPostRecord:
    """Fold a metrics reading into the record. Pure; never touches
    last_error/status. An empty reading only moves the checked stamp —
    absent is not zero and never clobbers stored values."""
    update: dict[str, object] = {"metrics_checked_at": now, "updated_at": now}
    if metrics and metrics != post.metrics:
        history = [*post.metrics_history, PostMetricsSnapshot(captured_at=now, metrics=metrics)]
        if len(history) > METRICS_HISTORY_HEAD + METRICS_HISTORY_TAIL:
            history = history[:METRICS_HISTORY_HEAD] + history[-METRICS_HISTORY_TAIL:]
        update.update(
            metrics=metrics, metrics_updated_at=metrics_updated_at, metrics_history=history
        )
    return post.model_copy(update=update)


def _primary_metric(post: PublishingPostRecord) -> float | None:
    for name in ("views", "impressions"):
        value = post.metrics.get(name)
        if value is not None and value > 0:
            return value
    return None


def performance_score(
    post: PublishingPostRecord, cohort: list[PublishingPostRecord]
) -> float | None:
    """log(primary) − log(median primary of the cohort); None on cold start.

    Baseline-relative because reel counts are heavy-tailed — absolute
    thresholds don't survive account drift."""
    import math
    from statistics import median

    primary = _primary_metric(post)
    if primary is None:
        return None
    cohort_primaries = [
        value for value in (_primary_metric(p) for p in cohort) if value is not None
    ]
    if len(cohort_primaries) < 5:
        return None
    return math.log(primary) - math.log(median(cohort_primaries))
```

(Move the `import math` / `from statistics import median` to the module top with the other imports — shown inline here only for locality.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/publishing.py api/test_publishing.py
git commit -m "feat(publishing): apply_post_metrics snapshot policy + baseline-relative performance_score"
```

---

### Task 4: Tick metrics pass + app wiring

**Files:**
- Modify: `api/autopilot.py` (constants near `AUTO_SEND_RETRY_BACKOFF_SEC` ~line 40; `FetchPostMetrics` protocol near `SendReadyPost`; `run_autopilot_tick` signature + call; new `_refresh_post_metrics` after `_auto_send_ready_posts` ~line 596)
- Modify: `api/app.py` (`autopilot_callables` returns a 4th callable; both call sites pass it)
- Test: `api/test_autopilot.py`

**Interfaces:**
- Consumes: Task 2 `get_post_metrics`, Task 3 `apply_post_metrics`.
- Produces:
  - `class FetchPostMetrics(Protocol): def __call__(self, user_id: str, *, buffer_post_id: str) -> tuple[dict[str, float], str | None]: ...`
  - `run_autopilot_tick(..., fetch_post_metrics: FetchPostMetrics | None = None)` (backward compatible).
  - `METRICS_REFRESH_INTERVAL_SEC = 43200`, `METRICS_RETENTION_DAYS = 30`, `METRICS_MAX_PER_PASS = 20`.
  - `_refresh_post_metrics(repo, *, user_id, fetch_post_metrics, now)` — runs after `_auto_send_ready_posts` in `run_autopilot_tick`, NOT gated on `enabled`/`auto_pair`/`auto_publish`/halt (per spec: metrics wanted in review-gated mode; the background loop only ticks enabled users anyway). Targets `status=="published"` with a `buffer_post_id`; skips posts checked within 43200s (via `metrics_checked_at`); skips posts whose `posted_at` is older than 30 days; caps at 20 per pass; on fetch failure logs + saves ONLY the `metrics_checked_at`/`updated_at` stamps (via `apply_post_metrics(post, metrics={}, ...)`), never `last_error`.
- App wiring: `autopilot_callables` builds `fetch_post_metrics(uid, *, buffer_post_id)` = `resolve_buffer_client().get_post_metrics(post_id=buffer_post_id)`; may raise — the tick pass catches per post.

- [ ] **Step 1: Write the failing tests**

Append to `api/test_autopilot.py`. Extend the `tick()` helper with `fetch=None` passed as `fetch_post_metrics=fetch` (keep existing params), and extend the `save_post` helper to accept `status`, `posted_at=None`, `buffer_post_id=None`, `metrics_checked_at=None` passthroughs (all already fields on the record). Then:

```python
class RecordingFetch:
    def __init__(self, metrics=None, fail=False):
        self.calls = []
        self.metrics = metrics if metrics is not None else {"views": 500.0}
        self.fail = fail

    def __call__(self, user_id, *, buffer_post_id):
        self.calls.append(buffer_post_id)
        if self.fail:
            raise RuntimeError("metrics fetch exploded")
        return self.metrics, "2026-06-09T06:00:00Z"


def test_metrics_pass_polls_published_posts_and_stores(monkeypatch=None):
    repo = build_repo()
    fetch = RecordingFetch()
    save_post(repo, post_id="p_pub", status="published",
              buffer_post_id="buf_1", posted_at="2026-06-08T12:00:00Z")
    save_post(repo, post_id="p_ready")  # ready: not polled
    save_state(repo)

    tick(repo, RecordingStarts(), fetch=fetch)

    assert fetch.calls == ["buf_1"]
    stored = next(p for p in repo.list_publishing_posts(USER) if p.post_id == "p_pub")
    assert stored.metrics == {"views": 500.0}
    assert stored.metrics_checked_at is not None
    assert len(stored.metrics_history) == 1


def test_metrics_pass_respects_cadence_retirement_and_cap():
    repo = build_repo()
    fetch = RecordingFetch()
    # Checked 1h before NOW -> inside the 12h cadence, skipped.
    save_post(repo, post_id="p_fresh", status="published", buffer_post_id="buf_f",
              posted_at="2026-06-08T12:00:00Z", metrics_checked_at="2026-06-09T11:00:00Z")
    # Posted 40 days before NOW -> retired, skipped.
    save_post(repo, post_id="p_old", status="published", buffer_post_id="buf_o",
              posted_at="2026-04-30T12:00:00Z")
    # Stale check -> polled.
    save_post(repo, post_id="p_due", status="published", buffer_post_id="buf_d",
              posted_at="2026-06-01T12:00:00Z", metrics_checked_at="2026-06-08T00:00:00Z")
    save_state(repo)

    tick(repo, RecordingStarts(), fetch=fetch)

    assert fetch.calls == ["buf_d"]


def test_metrics_fetch_failure_stamps_check_but_not_last_error():
    repo = build_repo()
    fetch = RecordingFetch(fail=True)
    save_post(repo, post_id="p_pub", status="published",
              buffer_post_id="buf_1", posted_at="2026-06-08T12:00:00Z")
    save_state(repo)

    tick(repo, RecordingStarts(), fetch=fetch)  # must not raise

    stored = next(p for p in repo.list_publishing_posts(USER) if p.post_id == "p_pub")
    assert stored.metrics_checked_at is not None  # won't hammer next tick
    assert stored.last_error is None
    assert stored.metrics == {}
```

(If `save_post`'s current signature lacks `posted_at`/`buffer_post_id`/`metrics_checked_at`, extend it — they are existing/new record fields with defaults.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k metrics`
Expected: FAIL with `TypeError: run_autopilot_tick() got an unexpected keyword argument 'fetch_post_metrics'`

- [ ] **Step 3: Implement the tick pass**

In `api/autopilot.py` — constants near `AUTO_SEND_RETRY_BACKOFF_SEC`:

```python
METRICS_REFRESH_INTERVAL_SEC = 43200  # ~12h; Buffer ingests metrics daily
METRICS_RETENTION_DAYS = 30           # metrics have settled; stop polling
METRICS_MAX_PER_PASS = 20
```

Protocol near `SendReadyPost`:

```python
class FetchPostMetrics(Protocol):
    def __call__(
        self, user_id: str, *, buffer_post_id: str
    ) -> tuple[dict[str, float], str | None]: ...
```

Import `apply_post_metrics` alongside the existing `create_publish_post_for_render` import. Thread `fetch_post_metrics: FetchPostMetrics | None = None` through `run_autopilot_tick` and call the pass after `_auto_send_ready_posts`:

```python
    _refresh_post_metrics(
        repo,
        user_id=user_id,
        fetch_post_metrics=fetch_post_metrics,
        now=now or datetime.now(timezone.utc),
    )
```

The pass, after `_auto_send_ready_posts`:

```python
def _refresh_post_metrics(
    repo: StorageRepository,
    *,
    user_id: str,
    fetch_post_metrics: FetchPostMetrics | None,
    now: datetime,
) -> None:
    """Pull per-post performance for published posts on a slow cadence.

    Runs outside STATE_LOCK and regardless of the autonomy flags — metrics
    are wanted in review-gated mode too. Best-effort by contract: failures
    log and stamp the check time (so the next tick doesn't hammer) but never
    touch last_error (it drives the auto-send backoff) or the halt."""
    if fetch_post_metrics is None:
        return
    now_iso = utc_now_iso(now)
    refreshed = 0
    for post in repo.list_publishing_posts(user_id, status="published"):
        if refreshed >= METRICS_MAX_PER_PASS:
            break
        if not post.buffer_post_id:
            continue
        if post.metrics_checked_at and not _older_than(
            post.metrics_checked_at, now, METRICS_REFRESH_INTERVAL_SEC
        ):
            continue
        if post.posted_at and _older_than(
            post.posted_at, now, METRICS_RETENTION_DAYS * 86400
        ):
            continue
        refreshed += 1
        try:
            metrics, updated_at = fetch_post_metrics(
                user_id, buffer_post_id=post.buffer_post_id
            )
        except Exception:  # noqa: BLE001 — metrics must never break the tick
            logger.warning(
                "metrics fetch failed for post %s", post.post_id, exc_info=True
            )
            metrics, updated_at = {}, None
        repo.save_publishing_post(
            apply_post_metrics(
                post, metrics=metrics, metrics_updated_at=updated_at, now=now_iso
            )
        )


def _older_than(stamp: str, now_dt: datetime, seconds: float) -> bool:
    try:
        parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return True  # unparseable stamp: treat as due rather than starving
    return (now_dt - parsed).total_seconds() > seconds
```

- [ ] **Step 4: Run the autopilot suite**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v`
Expected: all PASS (existing tests unaffected — the param defaults to None).

- [ ] **Step 5: Wire app.py**

In `autopilot_callables` (which already returns three callables), add and return a fourth:

```python
        def fetch_post_metrics(
            uid: str, *, buffer_post_id: str
        ) -> tuple[dict[str, float], str | None]:
            return resolve_buffer_client().get_post_metrics(post_id=buffer_post_id)

        return start_music_analysis, start_edit, send_ready_post, fetch_post_metrics
```

Update BOTH call sites (`trigger_autopilot_tick`, `_autopilot_tick_all_users`) to unpack four values and pass `fetch_post_metrics=fetch_post_metrics` into `run_autopilot_tick`. (`resolve_buffer_client` raises HTTPException when unconfigured — that surfaces as a caught per-post failure in the tick pass, which is the intended degraded mode when Buffer isn't configured.)

- [ ] **Step 6: Run the API suites**

Run: `.venv/bin/python -m pytest api/test_autopilot.py api/test_api_v1.py api/test_publishing.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add api/autopilot.py api/app.py api/test_autopilot.py
git commit -m "feat(autopilot): per-post metrics refresh pass on the tick"
```

---

### Task 5: Lineage ids at packaging + refresh-status metrics pull

**Files:**
- Modify: `api/publishing.py` (`create_publish_post_for_render` ~line 451 — the `source_run` block already loaded for poster refs)
- Modify: `api/app.py` (`refresh_publishing_post_status` route ~line 1312)
- Test: `api/test_publishing.py`

**Interfaces:**
- Consumes: Task 1 fields, Task 2 `get_post_metrics`, Task 3 `apply_post_metrics`.
- Produces: packaging stamps `source_video_file_id` / `song_file_id` from `source_run.inputs` (`"source_video_file_id"`, `"audio_file_id"`), best-effort None. The refresh-status route, AFTER `apply_buffer_status`, additionally pulls metrics when the (possibly just-updated) post is `published` with a `buffer_post_id`; a metrics failure there logs only — it must NOT set `last_error` (unlike the status-lookup failure path above it, which keeps its existing behavior).

- [ ] **Step 1: Write the failing tests**

```python
def test_packaging_captures_lineage_ids():
    # Extend the EXISTING create_publish_post_for_render lineage test (the
    # one that builds a render manifest with source_run_id and asserts
    # source_name/song_name): after the existing assertions add
    assert post.source_video_file_id == "<the film file_id that test seeds>"
    assert post.song_file_id == "<the audio file_id that test seeds>"


def test_refresh_status_pulls_metrics_for_published_post():
    # Mirror the existing refresh-status API test harness (fake Buffer client
    # injected). Give the fake client BOTH get_post (returning a sent status)
    # and get_post_metrics (returning ({"views": 321.0}, "2026-07-27T06:00:00Z")).
    # POST /v1/publishing/posts/{id}/refresh-status on a queued post with a
    # buffer_post_id; assert the response shows status "published" AND
    # metrics {"views": 321.0}.
    ...


def test_refresh_status_metrics_failure_does_not_set_last_error():
    # Same harness; get_post succeeds (sent), get_post_metrics raises
    # BufferClientError. Assert response status is "published", last_error
    # is None, and the HTTP status is 200.
    ...
```

Write these as real tests following the file's existing refresh-status tests (they already build the app with an injectable fake Buffer client — extend that fake with the two methods; the `...` bodies above describe exactly what to assert, and the seeded ids come from the existing test's fixtures).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k "lineage_ids or refresh_status_pulls or refresh_status_metrics"`
Expected: FAIL (missing fields / metrics not pulled).

- [ ] **Step 3: Implement packaging ids**

In `create_publish_post_for_render`, the existing poster-ref block already loads `source_run`; capture inputs there too:

```python
    poster_file_id: str | None = None
    poster_version_id: str | None = None
    source_video_file_id: str | None = None
    song_file_id: str | None = None
    if manifest.source_run_id:
        try:
            source_run = repo.load_run_manifest(
                RunRef(user_id=user_id, run_id=manifest.source_run_id)
            )
            poster_file_id = source_run.outputs.get("render_poster_file_id")
            poster_version_id = source_run.outputs.get("render_poster_version_id")
            source_video_file_id = source_run.inputs.get("source_video_file_id")
            song_file_id = source_run.inputs.get("audio_file_id")
        except KeyError:
            pass
```

…and pass both into the `PublishingPostRecord(...)` constructor (`source_video_file_id=source_video_file_id, song_file_id=song_file_id`).

- [ ] **Step 4: Implement the refresh-status extension**

In `refresh_publishing_post_status`, replace the final save/return with:

```python
        saved = repo.save_publishing_post(apply_buffer_status(post, result, now=utc_now()))
        if saved.status == "published" and saved.buffer_post_id:
            try:
                metrics, metrics_updated_at = client.get_post_metrics(
                    post_id=saved.buffer_post_id
                )
                saved = repo.save_publishing_post(
                    apply_post_metrics(
                        saved,
                        metrics=metrics,
                        metrics_updated_at=metrics_updated_at,
                        now=utc_now(),
                    )
                )
            except BufferClientError as exc:
                # Metrics are decoration on this route; a failure must not
                # touch last_error (auto-send backoff) or fail the refresh.
                logger.warning(
                    "metrics fetch failed during refresh for post %s: %s",
                    saved.post_id,
                    exc,
                )
        return publishing_post_view(saved, uid, resolved_store)
```

Import `apply_post_metrics` in app.py's publishing imports.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest api/test_publishing.py api/test_api_v1.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/publishing.py api/app.py api/test_publishing.py
git commit -m "feat(publishing): lineage ids at packaging + metrics pull on refresh-status"
```

---

### Task 6: `performance_score` on the post listing

**Files:**
- Modify: `api/app.py` (`PublishingPostView` ~line 264; `publishing_post_view` ~line 1122; `list_publishing_posts` route ~line 1176)
- Test: `api/test_publishing.py`

**Interfaces:**
- Consumes: Task 3 `performance_score`.
- Produces: `PublishingPostView.performance_score: float | None = None`; `publishing_post_view(post, uid, store, performance_score=None)` optional param; the LIST route computes each published post's score against its cohort (the other published posts, ≤10 most recent by `posted_at`, min 5) and passes it in. Single-post routes (send/cancel/refresh/etc.) pass nothing → null score (documented: scores appear on list responses).

- [ ] **Step 1: Write the failing test**

```python
def test_listing_carries_performance_scores():
    # Using the app-level harness: seed 6 published posts with
    # metrics {"views": 100.0} and posted_at values on consecutive days, and
    # one with {"views": 200.0}. GET /v1/publishing/posts?status=all.
    # Assert: the 200-views post has performance_score ≈ math.log(2.0)
    # (cohort median 100 over the other 6); a post with no metrics has
    # performance_score None.
```

Write it concretely against the file's existing app-construction helper (`build_publishing_test_app` or the equivalent the earlier tests use), seeding via `repo.save_publishing_post(...)` with explicit `posted_at`/`metrics`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k listing_carries`
Expected: FAIL (`performance_score` missing / None everywhere).

- [ ] **Step 3: Implement**

`PublishingPostView` gains:

```python
    # Baseline-relative log score vs the account's recent median; computed
    # per list response, never persisted. Null until ≥5 published posts
    # carry a primary metric (honest cold start).
    performance_score: float | None = None
```

`publishing_post_view` gains an optional `performance_score: float | None = None` parameter, passed through to the constructor. In the list route, before building views:

```python
        published = [p for p in records if p.status == "published"]
        recent = sorted(
            published, key=lambda p: p.posted_at or p.updated_at, reverse=True
        )[:11]  # each post's cohort = the other ≤10 most recent
        scores = {
            p.post_id: performance_score(
                p, [c for c in recent if c.post_id != p.post_id][:10]
            )
            for p in published
        }
```

…and pass `performance_score=scores.get(record.post_id)` when building each view. Import `performance_score` from `api.publishing`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest api/test_publishing.py api/test_api_v1.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app.py api/test_publishing.py
git commit -m "feat(api): performance_score on publishing post listings"
```

---

### Task 7: Frontend — metrics line, relative chip, sheet detail

**Files:**
- Modify: `web/src/services/eclypteApi.ts` (`PublishingPost` type ~line 103)
- Modify: `web/src/app/dashboard/page.tsx` (posted-strip card ~line 452; `ReviewSheet` published-state body)

**Interfaces:**
- Consumes: Task 6's JSON: `metrics: Record<string, number>`, `metrics_updated_at: string | null`, `metrics_checked_at: string | null`, `metrics_history: Array<{ captured_at: string; metrics: Record<string, number> }>`, `performance_score: number | null`, `source_video_file_id: string | null`, `song_file_id: string | null`.
- Produces: UI only.

- [ ] **Step 1: Extend the types**

Add the seven fields above to `PublishingPost` in `eclypteApi.ts` (exact names/types as listed).

- [ ] **Step 2: Card metrics line + chip**

In `page.tsx`, a small helper near the other formatters:

```tsx
const METRIC_LABELS: Record<string, string> = {
    views: "views",
    impressions: "views",   // impressions is the views fallback; one word for creators
    likes: "likes",
    comments: "comments",
    shares: "shares",
    saves: "saves",
    reach: "reached",
}

function metricsLine(post: PublishingPost): string | null {
    const parts: string[] = []
    for (const key of ["views", "impressions", "likes", "comments", "shares", "saves"]) {
        const value = post.metrics?.[key]
        if (value === undefined) continue
        if (key === "impressions" && post.metrics?.views !== undefined) continue
        parts.push(`${Math.round(value).toLocaleString()} ${METRIC_LABELS[key]}`)
    }
    return parts.length ? parts.join(" · ") : null
}

function relativeChip(score: number | null): string | null {
    if (score === null || score === undefined) return null
    const ratio = Math.exp(score)
    if (ratio >= 1.5) return `${ratio.toFixed(1)}× your median`
    if (ratio <= 1 / 1.5) return "below median"
    return "around median"
}
```

In the posted-strip card (the `styles.postedCard` button), under the existing title/status content, render:

```tsx
{post.status === "published" && (
    metricsLine(post)
        ? <span className={styles.smallText}>
              {metricsLine(post)}
              {relativeChip(post.performance_score) ? ` · ${relativeChip(post.performance_score)}` : ""}
          </span>
        : <span className={styles.smallText}>numbers arrive about a day after posting</span>
)}
```

(Match the card's real inner markup — reuse whatever muted small-text class its neighbors use if `styles.smallText` isn't it.)

- [ ] **Step 3: ReviewSheet detail**

In `ReviewSheet`, when the displayed post is `published`: render a "How it's doing" block — one row per entry in `post.metrics` (humanized: `METRIC_LABELS[name] ?? humanizeLabel(name)` + `Math.round(value).toLocaleString()`), the freshness line when `metrics` is empty, and beneath it a dated history list from `metrics_history` (`formatDate(snapshot.captured_at)` + its views/impressions value only — keep it one line per snapshot). Sentence case throughout; no service names.

- [ ] **Step 4: Lint + build**

Run from `web/`: `npm run lint && npm run build`
Expected: 0 errors (the pre-existing marketing `<img>` warning is fine).

- [ ] **Step 5: Commit**

```bash
git add web/src/services/eclypteApi.ts web/src/app/dashboard/page.tsx
git commit -m "feat(dashboard): per-reel performance line, relative chip, sheet detail"
```

---

### Task 8: Docs + full verification

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `api/COMMANDS.md`, `web/AGENTS.md`

- [ ] **Step 1: Update the five docs**

Weave into the existing autopilot/publishing sections (match each doc's voice): the tick's metrics-refresh pass (12h cadence, 30-day retirement, 20/pass cap, absent≠0, failure isolation from `last_error`/halt), `BufferClient.get_post_metrics`, the snapshot policy (first 2 + last 10), `performance_score` (log vs trailing-median, ≥5 posts, list responses only), the refresh-status metrics pull, the new `PublishingPostRecord` fields (a frontend contract — list them in web/AGENTS.md), and the paused-autopilot consequence (background metrics refresh pauses too; manual Refresh still works). In `api/COMMANDS.md`, add the deploy-time note: run the Task 0 probe against a real sent post if it wasn't run during implementation, recording which metric names Buffer populates for Reels; note Buffer metrics are licensed for personal workflows only (multi-tenant blocker → direct Meta route).

- [ ] **Step 2: Full verification**

Run: `.venv/bin/python -m pytest api -q` — expected: all pass.
Run from `web/`: `npm run lint && npm run build` — expected: clean.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md AGENTS.md ARCHITECTURE.md api/COMMANDS.md web/AGENTS.md
git commit -m "docs: performance feedback loop (Phase 1)"
```
