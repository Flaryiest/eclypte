# Performance feedback loop, Phase 1 — design

Date: 2026-07-27
Status: approved by Eric (brainstorm session); ready for implementation planning.

## Problem

Eclypte now creates and posts reels autonomously (2/day via Buffer → Instagram)
but learns nothing from how they perform. There is no way to see, in the
dashboard, whether a reel did well — let alone steer future pairing/window
choices by it. This spec is Phase 1 of a two-phase plan: **ingest per-reel
performance and surface it**, with the data model shaped so Phase 2
(adaptive steering + the montage-vs-single-scene retention experiment) bolts
on without migration.

## Research grounding (July 2026)

- **Buffer's GraphQL API shipped post metrics in June 2026**: `Post.metrics`
  (normalized `PostMetric` entries; enum includes reactions, comments,
  shares, reposts, reach, impressions, views, clicks, engagementRate, saves,
  follows, totalTimeWatched) plus `metricsUpdatedAt` and an
  `aggregatedPostMetrics` query. Ingestion is ~daily; a newly sent post can
  take ~24h to show anything. Legacy metric types are removed Dec 1, 2026 —
  build against the new enum only.
- **Open question (settle at implementation step 0)**: Buffer's Analyze docs
  say only impressions/likes/comments come through for Instagram REELS; the
  API enum is cross-network, so actual field population for a reel is
  unverified. Probe one real sent post with the live key first. Phase 1 is
  fully useful at the impressions/likes/comments floor.
- **Terms**: Buffer post metrics are for "personal workflows and automations
  only" (personal API key). Fine for the current single-operator product;
  known blocker for multi-tenant SaaS (would then need route B below).
- **Upgrade path (route B, not built)**: direct Meta "Instagram API with
  Instagram Login" — full Reels metrics (views, reach, saves, shares,
  avg watch time, skip rate), no Facebook Page, no App Review for one's own
  professional account, but a Meta app + 60-day token with a dead-man
  refresh. Deliberately avoided per Eric's preference; the storage design
  below (raw metric maps) lets Meta-sourced metrics merge in later.
- **Scoring prior art** (unanimous across vidIQ / Buffer Answers / research
  literature): raw counts are heavy-tailed; score each reel on a log scale
  relative to the account's own trailing median, never against absolute
  thresholds. At 2 posts/day a bandit is the wrong tool; Phase 2 should be
  marginal per-attribute score-and-weight with a fixed exploration floor
  (spec'd separately later). Two readings per reel (24h provisional,
  ~day-7 settle) capture the decay curve that matters.

## Decisions made during brainstorming

- **Buffer-native (approach A).** Metrics read through the existing
  `BufferClient`/API key, keyed by the stored `buffer_post_id`. No Meta
  console, no aggregator vendor ($149/mo Ayrshare rejected; Upload-Post
  would duplicate the posting path).
- **Phased: see it, then steer.** This spec ships ingestion + visibility
  only. Phase 2 (adaptation) is a future spec that consumes this data.

## Non-goals (Phase 1)

- No adaptive pairing/window steering, no experiments, no virality
  prediction.
- No charts/sparklines in the dashboard — text-first metric rows.
- No account-level (follower) analytics; per-post only.
- No new HTTP endpoints; new data rides existing responses.

## Architecture

### Ingestion (control plane)

- `BufferClient.get_post_metrics(post_id) -> (metrics: dict[str, float], metrics_updated_at: str | None)`
  — one GraphQL query for `post(input:{id}) { metrics { type name value } metricsUpdatedAt }`,
  house-style tolerant parse (errors array → raise; wrong shape → raise).
  Only metrics present in the response are returned — **absent ≠ 0**.
- `_refresh_post_metrics(repo, *, user_id, now)` in `api/autopilot.py`, a
  sibling of `_auto_send_ready_posts`, called from `run_autopilot_tick`
  after the send pass (outside `STATE_LOCK`; it touches only publishing
  posts). Runs whenever the tick runs — **not** gated on `auto_pair` /
  `auto_publish` (metrics are wanted in review-gated mode too). Documented
  consequence of riding the tick: with autopilot paused (`enabled=false`)
  the background loop stops ticking that user, so metrics refresh only via
  the manual "Refresh from Buffer" button until autopilot resumes —
  accepted for Phase 1.
  - Targets: posts with `status == "published"` and a `buffer_post_id`.
  - Cadence: skip posts whose `metrics_checked_at` is younger than 12h
    (`METRICS_REFRESH_INTERVAL_SEC = 43200`).
  - Retirement: skip posts whose `posted_at` is older than 30 days
    (`METRICS_RETENTION_DAYS = 30`) — metrics have settled.
  - Cap: at most 20 posts per pass (`METRICS_MAX_PER_PASS`).
  - Failure policy: log + stamp `metrics_checked_at` (prevents hammering),
    **never** touch `last_error` (that field drives the auto-send backoff on
    ready posts and stays isolated), never counts toward the autopilot halt.
- The existing `POST /v1/publishing/posts/{id}/refresh-status` route also
  pulls metrics when the post is published — the manual "Refresh from
  Buffer" button gets metrics for free, same failure isolation.

### Data model (all additive with defaults; `extra="forbid"` stays intact)

New model:

```
class PostMetricsSnapshot(BaseModel):        # extra="forbid"
    captured_at: str                          # our clock, utc_now()
    metrics: dict[str, float]
```

`PublishingPostRecord` additions:

- `metrics: dict[str, float] = {}` — latest values by normalized metric name.
- `metrics_updated_at: str | None = None` — Buffer's ingestion stamp.
- `metrics_checked_at: str | None = None` — our last poll (cadence control).
- `metrics_history: list[PostMetricsSnapshot] = []` — appended only when
  values changed vs the stored `metrics`; capped by keeping the FIRST 2
  snapshots and the LAST 10 (early readings ≈ the 24h provisional; the tail
  is the settle curve).
- Phase 2 enablers, captured at packaging time in
  `create_publish_post_for_render`: `source_video_file_id: str | None = None`,
  `song_file_id: str | None = None` (resolved from the render's run lineage
  alongside the existing `source_name`/`song_name`; best-effort, None on any
  miss).

### Scoring & API surface

- `performance_score(post, cohort) -> float | None`, a pure helper in
  `api/publishing.py`: `log(primary) − log(median(primary over cohort))`
  where `primary` = the post's `views` metric, falling back to
  `impressions`. Cohort = the user's ≤10 most recent published
  posts by `posted_at` (excluding the post itself) that have a primary
  metric. Returns None when the post
  has no primary metric or the cohort has fewer than 5 scored posts
  (honest cold start; no fake precision).
- `PublishingPostView` gains the record's new fields automatically plus a
  per-response computed `performance_score: float | None` (computed in the
  post-listing assembly in `api/app.py`; never persisted).

### Frontend (Home feed only)

- Posted-strip cards: one compact line — `views · likes · comments` (only
  metrics that exist; absent metrics simply don't render) and a relative
  chip derived from `performance_score` (`e^score ≥ 1.5` → "N.N× your
  median", `≤ 1/1.5` → "below median", else "around median"; no chip when
  score is null).
- ReviewSheet, for a published post: full metric rows (humanized names) +
  dated history entries (text list), plus the freshness line "numbers
  arrive about a day after posting" when `metrics` is empty.
- `eclypteApi.ts`: `PublishingPost` gains `metrics`, `metrics_updated_at`,
  `metrics_history`, `performance_score`, and the two lineage id fields.
- Copy stays creator-facing: no "Buffer", no raw enum names.

## Error handling summary

| Condition | Behavior |
| --- | --- |
| Buffer metrics query fails | Log, stamp `metrics_checked_at`, skip post; nothing else changes |
| Metric absent in response | Not stored, not rendered — absent ≠ 0, per Buffer's own semantics |
| Post has no metrics yet (<~24h) | Freshness copy in UI; poll continues on cadence |
| Rate-limit uncertainty | 12h cadence + 20/pass + 30-day retirement keeps volume at a handful of calls/day; if Buffer publishes limits later, respect them |
| Cold start (<5 scored posts) | `performance_score` is null; no chip |

## Testing

Against existing fakes (no live Buffer): `get_post_metrics` parse (incl.
errors array and absent metrics); tick pass — cadence gating, retirement,
cap, snapshot append/dedupe/cap policy, `last_error` untouched on failure;
`performance_score` math (log-median, fallback to impressions, cold-start
null); refresh-status route pulling metrics for published posts only;
packaging captures the two lineage ids; frontend `npm run lint` + build.

## Implementation step 0 (live, before building)

With the production `BUFFER_API_KEY`: query one really-sent reel's
`post { metrics ... }` to record (in the plan) exactly which metric names
Buffer populates for an Instagram Reel, and re-check
developers.buffer.com for a published rate-limits page. This settles the
Analyze-docs-vs-API-enum depth conflict before any code assumes fields.

## Operational notes

- No new env vars; uses the existing `BUFFER_API_KEY`.
- Docs to update: CLAUDE.md, AGENTS.md, ARCHITECTURE.md, api/COMMANDS.md,
  web/AGENTS.md (post-record fields are a frontend contract).
- Known constraint to carry forward: Buffer post metrics are licensed for
  personal workflows only — revisit (route B: direct Meta) before any
  multi-tenant launch.
