"""Word-level lyrics timing via forced alignment (pure decision logic, lazy GPU deps).

`produce_lyrics_timing` force-aligns known lyric text against the actual audio
(stable-ts + Whisper, demucs vocal isolation) and falls back to transcription
when no text exists or the alignment fits poorly. Online lyric timestamps are
never trusted — audio sourced from YouTube is offset from provider timings, so
`lrc_plain_text` strips LRC down to text only.

The module stays importable on the control plane: torch/whisper/stable_whisper
imports live inside the `_load_model`/`_audio_duration`/`_detect_language`/
`_run_align`/`_run_transcribe` seams (which also make the decision flow testable
without GPU deps). Payload conventions match `analysis.py`: `schema_version`,
`_sec` suffixes, 3-dp rounding.
"""
from __future__ import annotations

import os
import re

SCHEMA_VERSION = 1
DEFAULT_MODEL = "large-v3"  # override with ECLYPTE_LYRICS_WHISPER_MODEL

# stable-ts aborts alignment when this ratio of words comes out zero-duration.
ALIGN_FAILURE_THRESHOLD = 0.5
# Our own acceptance gates on top of a completed alignment/transcription.
MAX_ZERO_DURATION_RATIO = 0.20
MIN_AVG_WORD_PROBABILITY = 0.45
MIN_COVERAGE_RATIO = 0.25  # aligned span / song duration; wrong-lyrics signature
COVERAGE_MIN_WORDS = 30  # coverage only meaningful for texts longer than this
MIN_TRANSCRIBED_WORDS = 10  # fewer means instrumental/hallucination -> no artifact

_ZERO_DURATION_EPS = 1e-6

# [mm:ss] / [mm:ss.xx] / [mm:ss.xxx] — minutes 1-3 digits, fractional 1-3 digits.
_TS_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(lrc: str | None) -> list[tuple[float, str]]:
    """Parse an LRC string into ascending `[(start_sec, line_text)]`.

    Lines without a timestamp (metadata like `[ar:...]`/`[ti:...]`) and lines with
    empty text are skipped. A line with multiple timestamps expands to one entry
    per timestamp. Exact `(time, text)` duplicates are removed.
    """
    if not lrc:
        return []

    entries: list[tuple[float, str]] = []
    for line in lrc.splitlines():
        stamps = list(_TS_RE.finditer(line))
        if not stamps:
            continue
        text = line[stamps[-1].end():].strip()
        if not text:
            continue
        for m in stamps:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            frac = m.group(3)
            total = minutes * 60 + seconds
            if frac:
                total += int(frac) / (10 ** len(frac))
            entries.append((round(total, 3), text))

    entries.sort(key=lambda pair: pair[0])
    deduped: list[tuple[float, str]] = []
    seen: set[tuple[float, str]] = set()
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return deduped


def lrc_plain_text(lrc: str | None) -> str | None:
    """LRC -> newline-joined line text in sung order, timestamps discarded.

    Multi-timestamp lines (repeated choruses) appear once per sung occurrence —
    forced alignment needs the text to match everything that is actually sung.
    """
    lines = parse_lrc(lrc)
    if not lines:
        return None
    return "\n".join(text for _, text in lines)


def alignment_quality(result: dict, duration_sec: float) -> dict:
    """Quality metrics for a whisper-style result dict (`segments[].words[]`)."""
    words = [w for seg in result.get("segments", []) for w in seg.get("words", [])]
    count = len(words)
    if not count:
        return {
            "avg_word_probability": 0.0,
            "zero_duration_word_ratio": 0.0,
            "coverage_ratio": 0.0,
            "word_count": 0,
        }
    zero = sum(
        1
        for w in words
        if float(w.get("end", 0.0)) - float(w.get("start", 0.0)) <= _ZERO_DURATION_EPS
    )
    span = max(float(w.get("end", 0.0)) for w in words) - min(
        float(w.get("start", 0.0)) for w in words
    )
    coverage = span / duration_sec if duration_sec > 0 else 0.0
    return {
        "avg_word_probability": round(
            sum(float(w.get("probability", 0.0)) for w in words) / count, 4
        ),
        "zero_duration_word_ratio": round(zero / count, 4),
        "coverage_ratio": round(coverage, 4),
        "word_count": count,
    }


def is_alignment_acceptable(quality: dict) -> bool:
    if quality["word_count"] < 1:
        return False
    if quality["zero_duration_word_ratio"] > MAX_ZERO_DURATION_RATIO:
        return False
    if quality["avg_word_probability"] < MIN_AVG_WORD_PROBABILITY:
        return False
    # Many words crammed into a sliver of the song = wrong lyrics text; short
    # texts legitimately cover little, so only gate long ones.
    if quality["word_count"] > COVERAGE_MIN_WORDS and quality["coverage_ratio"] < MIN_COVERAGE_RATIO:
        return False
    return True


def is_transcription_acceptable(quality: dict) -> bool:
    return (
        quality["word_count"] >= MIN_TRANSCRIBED_WORDS
        and quality["avg_word_probability"] >= MIN_AVG_WORD_PROBABILITY
    )


def assemble_lyrics_timing(*, duration_sec, mode, language, text_source,
                           model_name, quality, segments) -> dict:
    lines = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        lines.append(
            {
                "line_idx": len(lines),
                "start_sec": round(float(seg.get("start", 0.0)), 3),
                "end_sec": round(float(seg.get("end", 0.0)), 3),
                "text": text,
                "words": [
                    # .get defaults mirror alignment_quality's tolerance — a word
                    # missing timestamps passed the gate, so it must not crash here.
                    {
                        "word": str(w.get("word", "")).strip(),
                        "start_sec": round(float(w.get("start", 0.0)), 3),
                        "end_sec": round(float(w.get("end", 0.0)), 3),
                        "confidence": round(float(w.get("probability", 0.0)), 3),
                    }
                    for w in seg.get("words") or []
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {"duration_sec": round(float(duration_sec), 3)},
        "mode": mode,
        "language": language,
        "text_source": text_source,
        "model": model_name,
        "quality": quality,
        "lines": lines,
    }


def produce_lyrics_timing(audio_path, lyrics_text: str | None, *,
                          model_name: str | None = None,
                          progress_callback=None) -> dict | None:
    """Align `lyrics_text` to the audio, or transcribe when text is missing/bad.

    Returns the lyrics-timing payload, or None when nothing usable came out
    (instrumental, hallucinated transcription) — no artifact means "no words".
    """
    name = model_name or os.environ.get("ECLYPTE_LYRICS_WHISPER_MODEL") or DEFAULT_MODEL
    _report(progress_callback, 5, "Loading alignment model")
    model = _load_model(name)
    duration_sec = _audio_duration(audio_path)

    text = (lyrics_text or "").strip() or None
    if text:
        _report(progress_callback, 20, "Aligning lyrics to the vocal")
        try:
            language = _detect_language(model, audio_path)
        except Exception as exc:
            print(f"[lyrics_align] language detection failed: {exc}")
            language = None
        try:
            result = _run_align(model, audio_path, text, language)
        except Exception as exc:
            # stable-ts raises rather than returning None in several real cases
            # (language=None on plain text, CUDA OOM, internal errors) — treat a
            # crash exactly like a rejected alignment and fall through.
            print(f"[lyrics_align] alignment failed: {exc}")
            result = None
        if result:
            quality = alignment_quality(result, duration_sec)
            if is_alignment_acceptable(quality):
                _report(progress_callback, 100, "Lyrics aligned")
                return assemble_lyrics_timing(
                    duration_sec=duration_sec,
                    mode="aligned",
                    language=language or result.get("language"),
                    text_source="synced_lrc",
                    model_name=name,
                    quality=quality,
                    segments=result.get("segments", []),
                )
            print(f"[lyrics_align] alignment rejected by quality gate: {quality}")

    _report(progress_callback, 60, "Transcribing the vocal")
    result = _run_transcribe(model, audio_path)
    if result:
        quality = alignment_quality(result, duration_sec)
        if is_transcription_acceptable(quality):
            _report(progress_callback, 100, "Lyrics transcribed")
            return assemble_lyrics_timing(
                duration_sec=duration_sec,
                mode="transcribed",
                language=result.get("language"),
                text_source="none",
                model_name=name,
                quality=quality,
                segments=result.get("segments", []),
            )
        print(f"[lyrics_align] transcription rejected by quality gate: {quality}")
    return None


def _report(progress_callback, percent, detail):
    if progress_callback is not None:
        progress_callback(percent, detail)


def _load_model(name: str):
    import stable_whisper
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    return stable_whisper.load_model(name, device=device)


def _audio_duration(audio_path) -> float:
    import whisper

    return len(whisper.load_audio(str(audio_path))) / whisper.audio.SAMPLE_RATE


def _detect_language(model, audio_path) -> str:
    """Detect language from a 30s window ~40% into the song (skips intros)."""
    import whisper

    audio = whisper.load_audio(str(audio_path))
    window = whisper.audio.SAMPLE_RATE * 30
    start = max(0, int(len(audio) * 0.4) - window // 2)
    chunk = whisper.pad_or_trim(audio[start:start + window])
    mel = whisper.log_mel_spectrogram(chunk, n_mels=model.dims.n_mels).to(model.device)
    _, probs = model.detect_language(mel)
    return max(probs, key=probs.get)


def _run_align(model, audio_path, text: str, language: str | None) -> dict | None:
    """Force-align known text against the audio.

    A `failure_threshold` abort does NOT return None with these arguments
    (stable-ts only returns None with remove_instant_words=True) — it returns a
    result dominated by zero-duration words, which MAX_ZERO_DURATION_RATIO
    rejects. The None-check is defensive.
    """
    result = model.align(
        str(audio_path),
        text,
        language=language,
        original_split=True,
        failure_threshold=ALIGN_FAILURE_THRESHOLD,
        denoiser="demucs",
    )
    return result.to_dict() if result is not None else None


def _run_transcribe(model, audio_path) -> dict | None:
    result = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        denoiser="demucs",
        vad=True,
    )
    return result.to_dict() if result is not None else None
