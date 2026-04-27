from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import ceil, floor
from typing import Any, Literal


ExportFormat = Literal["reels_9_16", "youtube_16_9"]
OutputCrop = Literal["fill", "letterbox"]


@dataclass(frozen=True)
class ResolvedExportOptions:
    format: ExportFormat
    audio_start_sec: float
    audio_end_sec: float | None
    crop_focus_x: float
    output_size: tuple[int, int]
    crop: OutputCrop
    explicit: bool

    def as_payload(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "audio_start_sec": self.audio_start_sec,
            "audio_end_sec": self.audio_end_sec,
            "crop_focus_x": self.crop_focus_x,
        }

    def as_run_inputs(self) -> dict[str, str]:
        values = {
            "export_format": self.format,
            "audio_start_sec": _format_seconds(self.audio_start_sec),
            "crop_focus_x": _format_seconds(self.crop_focus_x),
        }
        if self.audio_end_sec is not None:
            values["audio_end_sec"] = _format_seconds(self.audio_end_sec)
        return values


def resolve_export_options(
    export_options: Any,
    *,
    max_duration_sec: float | None = None,
) -> ResolvedExportOptions:
    raw = _coerce_export_options(export_options)
    explicit = raw is not None or max_duration_sec is not None
    raw = raw or {}

    format_value = str(raw.get("format") or "youtube_16_9")
    if format_value not in {"reels_9_16", "youtube_16_9"}:
        raise ValueError("export format must be reels_9_16 or youtube_16_9")

    audio_start_sec = float(raw.get("audio_start_sec") or 0.0)
    if audio_start_sec < 0:
        raise ValueError("audio_start_sec must be greater than or equal to 0")

    audio_end_raw = raw.get("audio_end_sec")
    audio_end_sec = float(audio_end_raw) if audio_end_raw is not None else None
    if audio_end_sec is None and max_duration_sec is not None:
        audio_end_sec = audio_start_sec + float(max_duration_sec)
    if audio_end_sec is not None and audio_end_sec <= audio_start_sec:
        raise ValueError("audio_end_sec must be after audio_start_sec")

    crop_focus_x = float(raw.get("crop_focus_x", 0.5))
    if crop_focus_x < 0 or crop_focus_x > 1:
        raise ValueError("crop_focus_x must be between 0 and 1")

    if format_value == "reels_9_16":
        output_size = (1080, 1920)
        crop = "fill"
    else:
        output_size = (1920, 1080)
        crop = "letterbox"

    return ResolvedExportOptions(
        format=format_value,  # type: ignore[arg-type]
        audio_start_sec=audio_start_sec,
        audio_end_sec=audio_end_sec,
        crop_focus_x=crop_focus_x,
        output_size=output_size,
        crop=crop,  # type: ignore[arg-type]
        explicit=explicit,
    )


def trim_song_analysis(
    song: dict[str, Any],
    *,
    start_sec: float,
    end_sec: float | None,
) -> dict[str, Any]:
    duration = float(song.get("source", {}).get("duration_sec", 0.0) or 0.0)
    start_sec = float(start_sec)
    end_sec = duration if end_sec is None else float(end_sec)

    if start_sec < 0:
        raise ValueError("audio_start_sec must be greater than or equal to 0")
    if end_sec <= start_sec:
        raise ValueError("audio_end_sec must be after audio_start_sec")
    if end_sec > duration:
        raise ValueError("audio_end_sec exceeds song duration")

    trimmed = deepcopy(song)
    selected_duration = round(end_sec - start_sec, 3)
    source = dict(trimmed.get("source") or {})
    source["duration_sec"] = selected_duration
    source["trim_start_sec"] = round(start_sec, 3)
    source["trim_end_sec"] = round(end_sec, 3)
    trimmed["source"] = source
    trimmed["beats_sec"] = _clip_times(song.get("beats_sec") or [], start_sec, end_sec)
    trimmed["downbeats_sec"] = _clip_times(song.get("downbeats_sec") or [], start_sec, end_sec)
    trimmed["segments"] = _clip_segments(song.get("segments") or [], start_sec, end_sec)
    if "energy" in song:
        trimmed["energy"] = _clip_energy(song["energy"], start_sec, end_sec)
    return trimmed


def _coerce_export_options(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def _clip_times(values: list[float], start_sec: float, end_sec: float) -> list[float]:
    return [
        round(float(value) - start_sec, 3)
        for value in values
        if start_sec <= float(value) < end_sec
    ]


def _clip_segments(
    segments: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:
    clipped = []
    for segment in segments:
        seg_start = float(segment["start_sec"])
        seg_end = float(segment["end_sec"])
        overlap_start = max(seg_start, start_sec)
        overlap_end = min(seg_end, end_sec)
        if overlap_end <= overlap_start:
            continue
        next_segment = dict(segment)
        next_segment["start_sec"] = round(overlap_start - start_sec, 3)
        next_segment["end_sec"] = round(overlap_end - start_sec, 3)
        clipped.append(next_segment)
    return clipped


def _clip_energy(energy: dict[str, Any], start_sec: float, end_sec: float) -> dict[str, Any]:
    rate_hz = float(energy.get("rate_hz", 0) or 0)
    values = list(energy.get("values") or [])
    if rate_hz <= 0 or not values:
        return dict(energy)
    start_index = max(0, floor(start_sec * rate_hz))
    end_index = min(len(values), ceil(end_sec * rate_hz))
    clipped = dict(energy)
    clipped["values"] = values[start_index:end_index]
    return clipped


def _format_seconds(value: float) -> str:
    return f"{float(value):.3f}"
