"""Review-gated autopilot: turns the curated content queue into ready publish packages.

The tick is a synchronous, idempotent pass over `AutopilotState`: it advances
in-flight items by reading run manifests, packages completed renders through
the existing publishing helper, and starts new work while under the daily
target. Long-running workflow execution is delegated to injected callables so
the tick itself stays fast and unit-testable.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from api.publishing import (
    BufferPostNotFoundError,
    BufferPostResult,
    apply_buffer_status,
    apply_post_metrics,
    create_publish_post_for_render,
)
from api.storage.models import AutopilotItem, AutopilotState, PublishingPostRecord, RunManifest
from api.storage.refs import FileVersionRef, RunRef
from api.storage.repository import StorageRepository
from api.timeutil import utc_now as utc_now_iso

logger = logging.getLogger("eclypte.autopilot")

TRIM_TARGET_SEC = 25.0
TRIM_MIN_SEC = 20.0
TRIM_MAX_SEC = 30.0
# Begin a section-anchored window this many seconds before the section starts, so a
# chorus-anchored reel captures the build-in rather than cutting in on the downbeat.
CHORUS_LEAD_IN_SEC = 5.0
COMBO_WINDOW_BUCKET_SEC = 5
MAX_CONSECUTIVE_FAILURES = 3
MAX_FINISHED_ITEMS = 50
PACKAGED_COUNT_RETENTION_DAYS = 14
# A failed auto-send is retried after this many seconds; a fresh error-free
# package sends immediately (no backoff applies until a send actually fails).
AUTO_SEND_RETRY_BACKOFF_SEC = 1800

METRICS_REFRESH_INTERVAL_SEC = 43200  # ~12h; Buffer ingests metrics daily
METRICS_RETENTION_DAYS = 30           # metrics have settled; stop polling
METRICS_MAX_PER_PASS = 20

# Server-side sent-status convergence for queued/scheduled posts: without it,
# statuses only update while the dashboard is open (the browser poll), so the
# send budget and creation brake would act on stale counts unattended.
STATUS_RECONCILE_INTERVAL_SEC = 3600  # Buffer slots are hours apart
STATUS_RECONCILE_MAX_PER_PASS = 10

ACTIVE_ITEM_STATUSES = {"analyzing", "editing"}

# Serializes state read-modify-write between the tick loop and API routes in
# this single-replica deployment; R2 has no conditional writes to lean on.
STATE_LOCK = threading.Lock()

# Serializes auto-send passes so concurrent ticks (background loop + manual
# tick) can't double-send the same ready post; sends stay outside STATE_LOCK
# so slow Buffer/R2 I/O never blocks state reads/writes.
SEND_LOCK = threading.Lock()

# Serializes metrics passes the same way SEND_LOCK serializes sends; a
# concurrent pass just skips (the 12h cadence retries next tick).
METRICS_LOCK = threading.Lock()

# Serializes status-reconcile passes (same non-blocking skip pattern).
RECONCILE_LOCK = threading.Lock()


class StartMusicAnalysis(Protocol):
    def __call__(self, user_id: str, *, audio: dict[str, str]) -> str: ...


class StartEdit(Protocol):
    def __call__(
        self,
        user_id: str,
        *,
        audio: dict[str, str],
        source_video: dict[str, str],
        creative_brief: str,
        title: str,
        export_options: dict[str, object] | None,
    ) -> str: ...


class SendReadyPost(Protocol):
    def __call__(
        self, user_id: str, *, post: "PublishingPostRecord"
    ) -> "PublishingPostRecord": ...


class FetchPostMetrics(Protocol):
    def __call__(
        self, user_id: str, *, buffer_post_id: str
    ) -> tuple[dict[str, float], str | None]: ...


class FetchPostStatus(Protocol):
    def __call__(self, user_id: str, *, buffer_post_id: str) -> "BufferPostResult": ...


def combo_key(
    video_file_id: str,
    song_file_id: str,
    window: tuple[float, float] | None,
) -> str:
    if window is None:
        return f"{video_file_id}|{song_file_id}|full"
    start_bucket = int(window[0] // COMBO_WINDOW_BUCKET_SEC) * COMBO_WINDOW_BUCKET_SEC
    return f"{video_file_id}|{song_file_id}|{start_bucket}"


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


def select_trim_windows(
    analysis: dict | None,
    *,
    target_sec: float = TRIM_TARGET_SEC,
    min_sec: float = TRIM_MIN_SEC,
    max_sec: float = TRIM_MAX_SEC,
) -> list[tuple[float, float]]:
    """Rank candidate audio windows by energy, best first.

    Returns an empty list when there is no analysis to work from (caller
    falls back to the full song) and the full span when the song is already
    short enough for a reel.
    """
    if not analysis:
        return []
    source = analysis.get("source") or {}
    duration = float(source.get("duration_sec") or 0.0)
    if duration <= 0:
        return []
    if duration <= max_sec:
        return [(0.0, round(duration, 3))]

    energy = analysis.get("energy") or {}
    values = [float(v) for v in (energy.get("values") or [])]
    rate_hz = float(energy.get("rate_hz") or 10.0)

    def window_score(start: float, end: float) -> float:
        if not values or rate_hz <= 0:
            return 0.0
        lo = max(0, int(start * rate_hz))
        hi = min(len(values), int(end * rate_hz))
        if hi <= lo:
            return 0.0
        return sum(values[lo:hi]) / (hi - lo)

    def clamp_window(start: float) -> tuple[float, float]:
        start = max(0.0, min(start, duration - min_sec))
        end = min(start + target_sec, duration)
        if end - start < min_sec:
            start = max(0.0, end - min_sec)
        return round(start, 3), round(end, 3)

    candidates: dict[int, tuple[float, tuple[float, float]]] = {}

    def add_candidate(start: float, bonus: float = 0.0) -> None:
        window = clamp_window(start)
        score = window_score(*window) + bonus
        bucket = int(window[0] // COMBO_WINDOW_BUCKET_SEC)
        existing = candidates.get(bucket)
        if existing is None or score > existing[0]:
            candidates[bucket] = (score, window)

    for segment in analysis.get("segments") or []:
        try:
            start = float(segment.get("start_sec"))
        except (TypeError, ValueError):
            continue
        label = str(segment.get("label") or "").lower()
        add_candidate(start - CHORUS_LEAD_IN_SEC, bonus=0.15 if "chorus" in label else 0.0)

    step = COMBO_WINDOW_BUCKET_SEC
    start = 0.0
    while start <= duration - min_sec:
        add_candidate(start)
        start += step

    ranked = sorted(candidates.values(), key=lambda entry: entry[0], reverse=True)
    return [window for _, window in ranked]


def _read_analysis_artifact(
    repo: StorageRepository,
    *,
    user_id: str,
    file_id: str | None,
    version_id: str | None,
) -> dict | None:
    if not file_id or not version_id:
        return None
    try:
        body = repo.read_version_bytes(
            FileVersionRef(user_id=user_id, file_id=file_id, version_id=version_id)
        )
        return json.loads(body.decode("utf-8"))
    except (KeyError, ValueError):
        return None


def find_music_analysis(
    repo: StorageRepository,
    *,
    user_id: str,
    song_version_id: str,
) -> dict | None:
    for run in repo.list_run_manifests(user_id):
        if run.status != "completed":
            continue
        is_analysis = (
            run.workflow_type == "music_analysis"
            and run.inputs.get("audio_version_id") == song_version_id
        )
        is_import = (
            run.workflow_type == "youtube_song_import"
            and run.outputs.get("audio_version_id") == song_version_id
        )
        if not (is_analysis or is_import):
            continue
        analysis = _read_analysis_artifact(
            repo,
            user_id=user_id,
            file_id=run.outputs.get("music_analysis_file_id"),
            version_id=run.outputs.get("music_analysis_version_id"),
        )
        if analysis is not None:
            return analysis
    return None


def run_autopilot_tick(
    repo: StorageRepository,
    *,
    user_id: str,
    start_music_analysis: StartMusicAnalysis,
    start_edit: StartEdit,
    send_ready_post: SendReadyPost | None = None,
    fetch_post_metrics: FetchPostMetrics | None = None,
    fetch_post_status: FetchPostStatus | None = None,
    now: datetime | None = None,
) -> AutopilotState:
    with STATE_LOCK:
        state = _run_tick_locked(
            repo,
            user_id=user_id,
            start_music_analysis=start_music_analysis,
            start_edit=start_edit,
            now=now,
        )
    # Status reconcile runs BEFORE auto-send so the send budget (and the next
    # tick's creation brake) see real queued/published counts even with the
    # dashboard closed.
    _reconcile_buffer_statuses(
        repo,
        user_id=user_id,
        fetch_post_status=fetch_post_status,
        now=now or datetime.now(timezone.utc),
    )
    # Auto-send does real network I/O (R2 media copy + Buffer HTTP call) per
    # post, so it runs outside STATE_LOCK: it only reads autopilot state and
    # mutates publishing posts, which the lock never protected, and holding
    # the lock for a multi-post send would block every dashboard autopilot
    # route for as long as the sends take.
    _auto_send_ready_posts(
        repo,
        user_id=user_id,
        state=state,
        send_ready_post=send_ready_post,
        now=now or datetime.now(timezone.utc),
    )
    _refresh_post_metrics(
        repo,
        user_id=user_id,
        fetch_post_metrics=fetch_post_metrics,
        now=now or datetime.now(timezone.utc),
    )
    return state


def _run_tick_locked(
    repo: StorageRepository,
    *,
    user_id: str,
    start_music_analysis: StartMusicAnalysis,
    start_edit: StartEdit,
    now: datetime | None,
) -> AutopilotState:
    now_dt = now or datetime.now(timezone.utc)
    today = now_dt.strftime("%Y-%m-%d")
    now_iso = utc_now_iso(now_dt)

    state = repo.get_autopilot_state(user_id=user_id)
    state = state.model_copy(update={"last_tick_at": now_iso})
    if not state.enabled or state.halted_reason:
        return repo.save_autopilot_state(state)

    items = list(state.items)
    used_combos = list(state.used_combos)
    packaged_counts = dict(state.packaged_counts)
    consecutive_failures = state.consecutive_failures
    exhausted_pairs = list(state.exhausted_pairs)
    last_paired_at = dict(state.last_paired_at)
    # Re-derived fresh each tick (not carried over from prior state): stale
    # True values must not persist when auto_pair is off, a pending item
    # already exists, or capacity is full — the replenish gate below is the
    # only place that stamps them True.
    recycling = False
    waiting_for_library = False
    backlog_paused = False

    def fail_item(item: AutopilotItem, error: str, *, count_failure: bool = True) -> AutopilotItem:
        nonlocal consecutive_failures
        if count_failure:
            consecutive_failures += 1
        return item.model_copy(
            update={"status": "failed", "last_error": error, "updated_at": now_iso}
        )

    def begin_edit_or_analysis(item: AutopilotItem) -> AutopilotItem:
        """Start the trimmed edit, or kick off music analysis first if missing.

        The trim window is derived from the song's music analysis, so a song
        without analysis cannot yield a window — starting an edit anyway would
        render the full song. Instead we run analysis first and pick up the edit
        on a later tick (the edit pipeline reuses this analysis).
        """
        if not item.song_file_id or not item.song_version_id:
            return fail_item(item, "item has no song to edit with")
        analysis = find_music_analysis(
            repo, user_id=user_id, song_version_id=item.song_version_id
        )
        if analysis is None:
            try:
                analysis_run_id = start_music_analysis(
                    user_id,
                    audio={
                        "file_id": item.song_file_id,
                        "version_id": item.song_version_id,
                    },
                )
            except Exception as exc:
                return fail_item(item, f"failed to start music analysis: {exc}")
            return item.model_copy(
                update={
                    "status": "analyzing",
                    "analysis_run_id": analysis_run_id,
                    "updated_at": now_iso,
                }
            )
        return start_trimmed_edit(item, analysis)

    def start_trimmed_edit(item: AutopilotItem, analysis: dict) -> AutopilotItem:
        windows = select_trim_windows(analysis)
        if not windows:
            return fail_item(item, "music analysis produced no usable trim window")
        window = next(
            (
                candidate
                for candidate in windows
                if combo_key(item.source_video_file_id, item.song_file_id, candidate)
                not in used_combos
            ),
            None,
        )
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

        export_options: dict[str, object] = {
            # Fill-frame: letterboxed reels sit on Instagram's official
            # "shown less often" list and leave ~24% picture for a 2.39:1 film.
            "format": "reels_9_16",
            "audio_start_sec": window[0],
            "audio_end_sec": window[1],
        }

        title = _edit_title(repo, user_id=user_id, item=item)
        try:
            edit_run_id = start_edit(
                user_id,
                audio={"file_id": item.song_file_id, "version_id": item.song_version_id},
                source_video={
                    "file_id": item.source_video_file_id,
                    "version_id": item.source_video_version_id,
                },
                creative_brief=item.creative_brief,
                title=title,
                export_options=export_options,
            )
        except Exception as exc:
            return fail_item(item, f"failed to start edit: {exc}")
        used_combos.append(
            combo_key(item.source_video_file_id, item.song_file_id, window)
        )
        return item.model_copy(
            update={
                "status": "editing",
                "edit_run_id": edit_run_id,
                "audio_start_sec": window[0],
                "audio_end_sec": window[1],
                "updated_at": now_iso,
            }
        )

    # Advance in-flight items first so completed work frees capacity this tick.
    for index, item in enumerate(items):
        if item.status == "analyzing" and item.analysis_run_id:
            run = _load_run(repo, user_id=user_id, run_id=item.analysis_run_id)
            if run is None or run.status in {"failed", "canceled"}:
                error = (run.last_error if run else None) or "music analysis did not complete"
                items[index] = fail_item(item, error)
            elif run.status == "completed":
                analysis = _read_analysis_artifact(
                    repo,
                    user_id=user_id,
                    file_id=run.outputs.get("music_analysis_file_id"),
                    version_id=run.outputs.get("music_analysis_version_id"),
                )
                if analysis is None:
                    items[index] = fail_item(
                        item, "music analysis completed without an analysis output"
                    )
                else:
                    items[index] = start_trimmed_edit(item, analysis)
        elif item.status == "editing" and item.edit_run_id:
            run = _load_run(repo, user_id=user_id, run_id=item.edit_run_id)
            if run is None or run.status in {"failed", "canceled"}:
                error = (run.last_error if run else None) or "edit run did not complete"
                items[index] = fail_item(item, error)
            elif run.status == "completed":
                file_id = run.outputs.get("render_output_file_id")
                version_id = run.outputs.get("render_output_version_id")
                if not file_id or not version_id:
                    items[index] = fail_item(item, "edit completed without a render output")
                else:
                    try:
                        post = create_publish_post_for_render(
                            repo,
                            user_id=user_id,
                            render_output={"file_id": file_id, "version_id": version_id},
                            auto_created=True,
                        )
                    except Exception as exc:
                        items[index] = fail_item(item, f"failed to create publish package: {exc}")
                    else:
                        items[index] = item.model_copy(
                            update={
                                "status": "packaged",
                                "post_id": post.post_id,
                                "updated_at": now_iso,
                            }
                        )
                        packaged_counts[today] = packaged_counts.get(today, 0) + 1
                        consecutive_failures = 0

    halted_reason = state.halted_reason
    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        halted_reason = (
            f"halted after {consecutive_failures} consecutive failures; "
            "fix the queue and clear the halt to resume"
        )

    # Replenish: synthesize one queue item when auto-pair is on and there is
    # capacity but nothing pending. Runs before start-new-work so the
    # synthesized item is consumed this same tick.
    if halted_reason is None and state.auto_pair:
        has_pending = any(item.status == "pending" for item in items)
        in_flight = sum(1 for item in items if item.status in ACTIVE_ITEM_STATUSES)
        packaged_today = packaged_counts.get(today, 0)
        if not has_pending and in_flight + packaged_today < state.daily_target:
            # Creation brake: production must not outrun Buffer's posting
            # slots. While unposted auto-created posts already cover 2x the
            # daily target, skip pairing entirely — the backlog drains at
            # Buffer's schedule, then production resumes.
            unposted_backlog = sum(
                1
                for p in repo.list_publishing_posts(user_id)
                if p.auto_created and p.status in {"ready", "queued", "scheduled"}
            )
            backlog_paused = unposted_backlog >= 2 * state.daily_target
        if (
            not has_pending
            and in_flight + packaged_today < state.daily_target
            and not backlog_paused
        ):
            films, songs = _list_pairable_assets(repo, user_id=user_id)
            waiting_for_library = not films or not songs
            known = {a["file_id"] for a in films + songs}
            last_paired_at = {k: v for k, v in last_paired_at.items() if k in known}
            pick = select_next_pair(
                films,
                songs,
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

    # Start new work while under the daily target.
    if halted_reason is None:
        while True:
            in_flight = sum(1 for item in items if item.status in ACTIVE_ITEM_STATUSES)
            packaged_today = packaged_counts.get(today, 0)
            if in_flight + packaged_today >= state.daily_target:
                break
            next_index = next(
                (i for i, item in enumerate(items) if item.status == "pending"),
                None,
            )
            if next_index is None:
                break
            item = items[next_index]
            if item.song_file_id and item.song_version_id:
                items[next_index] = begin_edit_or_analysis(item)
            else:
                items[next_index] = fail_item(item, "item has no saved song")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                halted_reason = (
                    f"halted after {consecutive_failures} consecutive failures; "
                    "fix the queue and clear the halt to resume"
                )
                break

    state = state.model_copy(
        update={
            "items": _prune_items(items),
            "used_combos": used_combos,
            "packaged_counts": _prune_counts(packaged_counts, today),
            "consecutive_failures": consecutive_failures,
            "halted_reason": halted_reason,
            "exhausted_pairs": exhausted_pairs,
            "last_paired_at": last_paired_at,
            "recycling": recycling,
            "waiting_for_library": waiting_for_library,
            "backlog_paused": backlog_paused,
        }
    )
    return repo.save_autopilot_state(state)


def _reconcile_buffer_statuses(
    repo: StorageRepository,
    *,
    user_id: str,
    fetch_post_status: FetchPostStatus | None,
    now: datetime,
) -> None:
    """Converge queued/scheduled posts with Buffer's real sent state.

    Runs outside STATE_LOCK, regardless of the autonomy flags — review-gated
    posts need status convergence too. Best-effort by contract: a failure
    logs and stamps `status_checked_at` only (so the next tick doesn't
    hammer), never `last_error` or the halt."""
    if fetch_post_status is None:
        return
    if not RECONCILE_LOCK.acquire(blocking=False):
        return
    try:
        now_iso = utc_now_iso(now)
        checked = 0
        for status in ("queued", "scheduled"):
            for post in repo.list_publishing_posts(user_id, status=status):
                if checked >= STATUS_RECONCILE_MAX_PER_PASS:
                    return
                if not post.buffer_post_id:
                    continue
                if post.status_checked_at and not _older_than(
                    post.status_checked_at,
                    now,
                    STATUS_RECONCILE_INTERVAL_SEC,
                    on_unparseable=True,
                ):
                    continue
                checked += 1
                result: BufferPostResult | None = None
                vanished = False
                try:
                    result = fetch_post_status(
                        user_id, buffer_post_id=post.buffer_post_id
                    )
                except BufferPostNotFoundError:
                    # Deleted in Buffer's UI (the natural cleanup for an
                    # over-full queue). Converge to canceled — otherwise the
                    # phantom counts against the send ceiling and the
                    # creation brake forever.
                    vanished = True
                except Exception:  # noqa: BLE001 — reconcile must never break the tick
                    logger.warning(
                        "status reconcile failed for post %s",
                        post.post_id,
                        exc_info=True,
                    )
                try:
                    fresh = repo.load_publishing_post(
                        user_id=user_id, post_id=post.post_id
                    )
                except KeyError:
                    continue
                if fresh.status not in {"queued", "scheduled"}:
                    continue  # changed mid-fetch (canceled/marked); leave it
                if vanished:
                    logger.warning(
                        "post %s no longer exists in Buffer; marking canceled",
                        post.post_id,
                    )
                    fresh = fresh.model_copy(update={"status": "canceled"})
                elif result is not None:
                    fresh = apply_buffer_status(fresh, result, now=now_iso)
                repo.save_publishing_post(
                    fresh.model_copy(update={"status_checked_at": now_iso})
                )
    finally:
        RECONCILE_LOCK.release()


def _auto_send_ready_posts(
    repo: StorageRepository,
    *,
    user_id: str,
    state: AutopilotState,
    send_ready_post: SendReadyPost | None,
    now: datetime,
) -> None:
    """Push ready auto-created packages into Buffer's queue.

    Runs outside STATE_LOCK (see `run_autopilot_tick`): it only reads
    autopilot state and mutates publishing posts, neither of which the lock
    protects. Buffer's channel posting schedule decides when each actually
    posts; the gap until that slot is the human veto window.
    """
    if (
        not state.enabled
        or not state.auto_publish
        or send_ready_post is None
        or state.halted_reason is not None
    ):
        return
    if not SEND_LOCK.acquire(blocking=False):
        return
    try:
        # Budget both ceilings on every send, not once per pass: Buffer's
        # queue must never exceed 2x the daily target, and a single pass must
        # never queue more than daily_target reels — a first pass over an
        # accumulated ready backlog once dumped weeks of packages into Buffer
        # at go-live. Growth is tracked via each send's returned record (the
        # fake/live callable both return the saved post).
        # Scheduled posts occupy Buffer slots too — count them toward the
        # ceiling for symmetry with the creation brake.
        queued_count = len(repo.list_publishing_posts(user_id, status="queued")) + len(
            repo.list_publishing_posts(user_id, status="scheduled")
        )
        sent_this_pass = 0
        failed_this_pass = 0
        for post in repo.list_publishing_posts(user_id, status="ready"):
            if queued_count >= 2 * state.daily_target:
                break
            if sent_this_pass >= state.daily_target:
                break
            if failed_this_pass >= state.daily_target:
                # A systemic Buffer outage over a large ready backlog would
                # otherwise burn an R2 media copy + Buffer call per ready
                # post per pass; the 30-min backoff takes over from here.
                break
            if not post.auto_created:
                continue
            if post.last_error and _within_backoff(post.updated_at, now):
                continue
            try:
                result = send_ready_post(user_id, post=post)
            except Exception:  # noqa: BLE001 — sends must never break the tick
                logger.warning("auto-send crashed for post %s", post.post_id, exc_info=True)
                failed_this_pass += 1
                continue
            if result is not None and result.status in {"queued", "scheduled"}:
                queued_count += 1
                sent_this_pass += 1
            else:
                failed_this_pass += 1
    finally:
        SEND_LOCK.release()


def _within_backoff(updated_at: str, now_dt: datetime) -> bool:
    try:
        stamped = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return (now_dt - stamped).total_seconds() < AUTO_SEND_RETRY_BACKOFF_SEC


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
    if not METRICS_LOCK.acquire(blocking=False):
        return
    try:
        now_iso = utc_now_iso(now)
        refreshed = 0
        for post in repo.list_publishing_posts(user_id, status="published"):
            if refreshed >= METRICS_MAX_PER_PASS:
                break
            if not post.buffer_post_id:
                continue
            if post.metrics_checked_at and not _older_than(
                post.metrics_checked_at,
                now,
                METRICS_REFRESH_INTERVAL_SEC,
                on_unparseable=True,
            ):
                continue
            if post.posted_at and _older_than(
                post.posted_at,
                now,
                METRICS_RETENTION_DAYS * 86400,
                on_unparseable=False,
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
            # Save onto a freshly loaded record, not the pre-fetch snapshot: a
            # concurrent save (permalink backfill, mark-posted, cancel) landing
            # during the fetch must not be silently reverted by this write.
            try:
                fresh = repo.load_publishing_post(user_id=user_id, post_id=post.post_id)
            except KeyError:
                continue
            if fresh.status != "published":
                continue  # canceled/changed mid-fetch; don't resurrect old state
            repo.save_publishing_post(
                apply_post_metrics(
                    fresh, metrics=metrics, metrics_updated_at=updated_at, now=now_iso
                )
            )
    finally:
        METRICS_LOCK.release()


def _older_than(
    stamp: str, now_dt: datetime, seconds: float, *, on_unparseable: bool
) -> bool:
    """Whether `stamp` is more than `seconds` in the past.

    `on_unparseable` forces each call site to choose what an unparseable
    stamp means for it: the cadence check wants True (poll it — treat as
    due rather than starving), the retirement check wants False (do NOT
    retire it — keep polling rather than abandoning it forever)."""
    try:
        parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return on_unparseable
    return (now_dt - parsed).total_seconds() > seconds


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


def _edit_title(repo: StorageRepository, *, user_id: str, item: AutopilotItem) -> str:
    from api.storage.refs import FileRef

    names = []
    for file_id in (item.source_video_file_id, item.song_file_id):
        if not file_id:
            continue
        try:
            manifest = repo.load_file_manifest(FileRef(user_id=user_id, file_id=file_id))
            names.append(manifest.display_name)
        except KeyError:
            continue
    if len(names) == 2:
        return f"Autopilot: {names[0]} x {names[1]}"
    return f"Autopilot {item.item_id}"


def _load_run(repo: StorageRepository, *, user_id: str, run_id: str) -> RunManifest | None:
    try:
        return repo.load_run_manifest(RunRef(user_id=user_id, run_id=run_id))
    except KeyError:
        return None


def _prune_items(items: list[AutopilotItem]) -> list[AutopilotItem]:
    finished = [item for item in items if item.status in {"packaged", "failed"}]
    if len(finished) <= MAX_FINISHED_ITEMS:
        return items
    cutoff = sorted(finished, key=lambda item: item.updated_at, reverse=True)
    keep_ids = {item.item_id for item in cutoff[:MAX_FINISHED_ITEMS]}
    return [
        item
        for item in items
        if item.status not in {"packaged", "failed"} or item.item_id in keep_ids
    ]


def _prune_counts(counts: dict[str, int], today: str) -> dict[str, int]:
    days = sorted(counts)
    if len(days) <= PACKAGED_COUNT_RETENTION_DAYS:
        return counts
    keep = set(days[-PACKAGED_COUNT_RETENTION_DAYS:]) | {today}
    return {day: count for day, count in counts.items() if day in keep}
