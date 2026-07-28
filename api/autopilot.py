"""Review-gated autopilot: turns the curated content queue into ready publish packages.

The tick is a synchronous, idempotent pass over `AutopilotState`: it advances
in-flight items by reading run manifests, packages completed renders through
the existing publishing helper, and starts new work while under the daily
target. Long-running workflow execution is delegated to injected callables so
the tick itself stays fast and unit-testable.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from api.publishing import create_publish_post_for_render
from api.storage.models import AutopilotItem, AutopilotState, RunManifest
from api.storage.refs import FileVersionRef, RunRef
from api.storage.repository import StorageRepository
from api.timeutil import utc_now as utc_now_iso

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

ACTIVE_ITEM_STATUSES = {"analyzing", "editing"}

# Serializes state read-modify-write between the tick loop and API routes in
# this single-replica deployment; R2 has no conditional writes to lean on.
STATE_LOCK = threading.Lock()


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
    now: datetime | None = None,
) -> AutopilotState:
    with STATE_LOCK:
        return _run_tick_locked(
            repo,
            user_id=user_id,
            start_music_analysis=start_music_analysis,
            start_edit=start_edit,
            now=now,
        )


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
    recycling = state.recycling
    waiting_for_library = state.waiting_for_library

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
            "format": "reels_cinematic",
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
        }
    )
    return repo.save_autopilot_state(state)


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
