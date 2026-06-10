"""Review-gated autopilot: turns the curated content queue into ready publish packages.

The tick is a synchronous, idempotent pass over `AutopilotState`: it advances
in-flight items by reading run manifests, packages completed renders through
the existing publishing helper, and starts new work while under the daily
target. Long-running workflow execution is delegated to injected callables so
the tick itself stays fast and unit-testable.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Protocol

from api.publishing import create_publish_post_for_render
from api.storage.models import AutopilotItem, AutopilotState, RunManifest
from api.storage.refs import FileVersionRef, RunRef
from api.storage.repository import StorageRepository

TRIM_TARGET_SEC = 30.0
TRIM_MIN_SEC = 25.0
TRIM_MAX_SEC = 35.0
COMBO_WINDOW_BUCKET_SEC = 5
MAX_CONSECUTIVE_FAILURES = 3
MAX_FINISHED_ITEMS = 50
PACKAGED_COUNT_RETENTION_DAYS = 14

ACTIVE_ITEM_STATUSES = {"importing", "editing"}

# Serializes state read-modify-write between the tick loop and API routes in
# this single-replica deployment; R2 has no conditional writes to lean on.
STATE_LOCK = threading.Lock()


class StartSongImport(Protocol):
    def __call__(self, user_id: str, url: str) -> str: ...


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


def utc_now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def combo_key(
    video_file_id: str,
    song_file_id: str,
    window: tuple[float, float] | None,
) -> str:
    if window is None:
        return f"{video_file_id}|{song_file_id}|full"
    start_bucket = int(window[0] // COMBO_WINDOW_BUCKET_SEC) * COMBO_WINDOW_BUCKET_SEC
    return f"{video_file_id}|{song_file_id}|{start_bucket}"


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
        add_candidate(start, bonus=0.15 if "chorus" in label else 0.0)

    step = COMBO_WINDOW_BUCKET_SEC
    start = 0.0
    while start <= duration - min_sec:
        add_candidate(start)
        start += step

    ranked = sorted(candidates.values(), key=lambda entry: entry[0], reverse=True)
    return [window for _, window in ranked]


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
        file_id = run.outputs.get("music_analysis_file_id")
        version_id = run.outputs.get("music_analysis_version_id")
        if not file_id or not version_id:
            continue
        try:
            body = repo.read_version_bytes(
                FileVersionRef(user_id=user_id, file_id=file_id, version_id=version_id)
            )
            return json.loads(body.decode("utf-8"))
        except (KeyError, ValueError):
            continue
    return None


def run_autopilot_tick(
    repo: StorageRepository,
    *,
    user_id: str,
    start_song_import: StartSongImport,
    start_edit: StartEdit,
    now: datetime | None = None,
) -> AutopilotState:
    with STATE_LOCK:
        return _run_tick_locked(
            repo,
            user_id=user_id,
            start_song_import=start_song_import,
            start_edit=start_edit,
            now=now,
        )


def _run_tick_locked(
    repo: StorageRepository,
    *,
    user_id: str,
    start_song_import: StartSongImport,
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

    def fail_item(item: AutopilotItem, error: str, *, count_failure: bool = True) -> AutopilotItem:
        nonlocal consecutive_failures
        if count_failure:
            consecutive_failures += 1
        return item.model_copy(
            update={"status": "failed", "last_error": error, "updated_at": now_iso}
        )

    def start_edit_for_item(item: AutopilotItem) -> AutopilotItem:
        nonlocal consecutive_failures
        if not item.song_file_id or not item.song_version_id:
            return fail_item(item, "item has no song to edit with")
        analysis = find_music_analysis(
            repo, user_id=user_id, song_version_id=item.song_version_id
        )
        windows = select_trim_windows(analysis)
        window: tuple[float, float] | None = None
        if windows:
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
                return fail_item(
                    item,
                    "every trim window for this video/song pair was already used",
                    count_failure=False,
                )
        else:
            if (
                combo_key(item.source_video_file_id, item.song_file_id, None)
                in used_combos
            ):
                return fail_item(
                    item,
                    "this video/song pair was already used in full",
                    count_failure=False,
                )

        export_options: dict[str, object] = {"format": "youtube_16_9"}
        if window is not None:
            export_options["audio_start_sec"] = window[0]
            export_options["audio_end_sec"] = window[1]

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
                "audio_start_sec": window[0] if window else None,
                "audio_end_sec": window[1] if window else None,
                "updated_at": now_iso,
            }
        )

    # Advance in-flight items first so completed work frees capacity this tick.
    for index, item in enumerate(items):
        if item.status == "importing" and item.import_run_id:
            run = _load_run(repo, user_id=user_id, run_id=item.import_run_id)
            if run is None or run.status in {"failed", "canceled"}:
                error = (run.last_error if run else None) or "song import did not complete"
                items[index] = fail_item(item, error)
            elif run.status == "completed":
                song_file_id = run.outputs.get("audio_file_id")
                song_version_id = run.outputs.get("audio_version_id")
                if not song_file_id or not song_version_id:
                    items[index] = fail_item(item, "song import completed without audio outputs")
                else:
                    items[index] = start_edit_for_item(
                        item.model_copy(
                            update={
                                "song_file_id": song_file_id,
                                "song_version_id": song_version_id,
                                "updated_at": now_iso,
                            }
                        )
                    )
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
                items[next_index] = start_edit_for_item(item)
            elif item.song_youtube_url:
                try:
                    import_run_id = start_song_import(user_id, item.song_youtube_url)
                except Exception as exc:
                    items[next_index] = fail_item(item, f"failed to start song import: {exc}")
                else:
                    items[next_index] = item.model_copy(
                        update={
                            "status": "importing",
                            "import_run_id": import_run_id,
                            "updated_at": now_iso,
                        }
                    )
            else:
                items[next_index] = fail_item(item, "item has neither a song asset nor a YouTube URL")
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
        }
    )
    return repo.save_autopilot_state(state)


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
