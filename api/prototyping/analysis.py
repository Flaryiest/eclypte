from pathlib import Path
import json

import allin1
import librosa
import numpy as np

SR = 22050
ENERGY_RATE_HZ = 10
RMS_HOP_LENGTH = 512
MIN_DURATION_SEC = 5.0
SCHEMA_VERSION = 1


def analyze(audio_path, out_path=None):
    audio_path = Path(audio_path)
    y, sr = _load_audio(audio_path)
    duration_sec = len(y) / sr
    if duration_sec < MIN_DURATION_SEC:
        raise ValueError("audio too short for analysis")

    energy_values = _energy_curve(y, sr, rate_hz=ENERGY_RATE_HZ)
    structure = _beats_and_structure(audio_path)

    result = _assemble(
        source_path=str(audio_path),
        duration_sec=duration_sec,
        sample_rate=sr,
        energy_values=energy_values,
        energy_rate_hz=ENERGY_RATE_HZ,
        **structure,
    )

    if out_path is None:
        out_path = audio_path.with_suffix(".json")
    Path(out_path).write_text(json.dumps(result, indent=2))
    return result


def _load_audio(path):
    return librosa.load(str(path), sr=SR, mono=True)


def _energy_curve(y, sr, rate_hz):
    rms = librosa.feature.rms(y=y, hop_length=RMS_HOP_LENGTH)[0]
    native_rate = sr / RMS_HOP_LENGTH
    duration = len(y) / sr
    target_len = max(1, int(round(duration * rate_hz)))
    src_times = np.arange(len(rms)) / native_rate
    dst_times = np.arange(target_len) / rate_hz
    resampled = np.interp(dst_times, src_times, rms)
    peak = float(resampled.max())
    if peak > 0:
        resampled = resampled / peak
    return [round(float(v), 4) for v in resampled]


def _beats_and_structure(audio_path):
    result = allin1.analyze(str(audio_path))
    if isinstance(result, list):
        result = result[0]
    segments = [
        {
            "start_sec": round(float(s.start), 3),
            "end_sec": round(float(s.end), 3),
            "label": s.label,
        }
        for s in result.segments
    ]
    return {
        "tempo_bpm": round(float(result.bpm), 2),
        "beats_sec": [round(float(b), 3) for b in result.beats],
        "downbeats_sec": [round(float(b), 3) for b in result.downbeats],
        "segments": segments,
    }


def _assemble(*, source_path, duration_sec, sample_rate, tempo_bpm,
              beats_sec, downbeats_sec, segments, energy_values, energy_rate_hz):
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "path": source_path,
            "duration_sec": round(duration_sec, 3),
            "sample_rate": int(sample_rate),
        },
        "tempo_bpm": tempo_bpm,
        "beats_sec": beats_sec,
        "downbeats_sec": downbeats_sec,
        "energy": {
            "rate_hz": energy_rate_hz,
            "values": energy_values,
        },
        "segments": segments,
    }


if __name__ == "__main__":
    analyze("./content/output.wav", "./content/output.json")
