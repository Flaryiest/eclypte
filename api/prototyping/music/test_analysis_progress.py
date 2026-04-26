from types import SimpleNamespace
import importlib
import sys

import numpy as np


def test_music_analysis_reports_real_substep_progress(monkeypatch, tmp_path):
    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"wav")
    fake_librosa = SimpleNamespace(
        load=lambda path, sr, mono: (np.ones(22050 * 6, dtype=np.float32), 22050),
        feature=SimpleNamespace(
            rms=lambda y, hop_length: np.ones((1, 4), dtype=np.float32),
        ),
    )
    fake_allin1 = SimpleNamespace(
        analyze=lambda path: SimpleNamespace(
            bpm=120,
            beats=[0.0, 1.0],
            downbeats=[0.0],
            segments=[SimpleNamespace(start=0.0, end=6.0, label="chorus")],
        ),
    )
    monkeypatch.setitem(sys.modules, "librosa", fake_librosa)
    monkeypatch.setitem(sys.modules, "allin1", fake_allin1)
    sys.modules.pop("api.prototyping.music.analysis", None)
    analysis = importlib.import_module("api.prototyping.music.analysis")
    events = []

    analysis.analyze(
        audio_path,
        tmp_path / "song.json",
        progress_callback=lambda percent, detail: events.append((percent, detail)),
    )

    assert events == [
        (10, "Loading audio"),
        (30, "Computed energy curve"),
        (55, "Running structure analysis"),
        (85, "Structure analysis complete"),
        (100, "Music analysis complete"),
    ]
