import pytest

from api.prototyping.edit.synthesis.rhythm import (
    CUT_LEAD_SEC,
    pacing_bands_for,
    pick_snap_beat,
    register_impacts_to_downbeats,
    split_overlong_section_shots,
    sync_report,
)
from api.prototyping.edit.synthesis.timeline_schema import Shot, ShotSource


def _shot(index, start, end, src_start):
    return Shot(
        index=index,
        timeline_start_sec=start,
        timeline_end_sec=end,
        source=ShotSource(start_sec=src_start, end_sec=src_start + (end - start)),
    )


def _video_with_impacts(impacts):
    """Minimal video-analysis dict: one scene carrying the given impact frames."""
    return {
        "source": {"duration_sec": 300.0},
        "scenes": [
            {
                "index": 0,
                "start_sec": 0.0,
                "end_sec": 300.0,
                "impacts": {
                    "impact_frames": [
                        {"timestamp_sec": ts, "intensity": inten} for ts, inten in impacts
                    ]
                },
            }
        ],
    }


# ---------------------------------------------------------------- pick_snap_beat


def test_pick_snap_beat_applies_early_cut_lead():
    # A boundary exactly on the beat still moves CUT_LEAD_SEC early.
    got = pick_snap_beat(2.0, [2.0], [])
    assert got is not None
    target, anchor = got
    assert target == pytest.approx(2.0 - CUT_LEAD_SEC)
    assert anchor == pytest.approx(2.0)


def test_pick_snap_beat_prefers_downbeat_over_nearer_beat():
    # Beat 2.0 is nearer to the boundary than downbeat 2.1, but the downbeat wins.
    got = pick_snap_beat(1.98, [2.0], [2.1])
    assert got is not None
    target, anchor = got
    assert anchor == pytest.approx(2.1)
    assert target == pytest.approx(2.1 - CUT_LEAD_SEC)


def test_pick_snap_beat_falls_back_to_beat_when_downbeat_out_of_reach():
    got = pick_snap_beat(2.0, [2.0], [5.0])
    assert got is not None
    _, anchor = got
    assert anchor == pytest.approx(2.0)


def test_pick_snap_beat_none_outside_tolerance():
    assert pick_snap_beat(3.0, [2.0], []) is None


def test_pick_snap_beat_none_when_no_beats():
    assert pick_snap_beat(3.0, [], []) is None


# ---------------------------------------------------------------- pacing_bands_for


def test_pacing_bands_converts_beats_to_seconds():
    bands = pacing_bands_for(120.0)  # 0.5s per beat
    assert bands["chorus"] == pytest.approx((1.0, 2.0))
    assert bands["verse"] == pytest.approx((2.0, 4.0))
    assert bands["default"][0] > 0


def test_pacing_bands_chorus_faster_than_verse():
    bands = pacing_bands_for(100.0)
    assert bands["chorus"][1] < bands["verse"][1]


def test_pacing_bands_bad_tempo_falls_back():
    bands = pacing_bands_for(0.0)
    assert bands == pacing_bands_for(120.0)


# ------------------------------------------------- register_impacts_to_downbeats


def test_register_shifts_source_window_onto_downbeat():
    # Impact at source 102.5 naturally lands at timeline 2.5; downbeat is at 2.0,
    # so the whole source window shifts +0.5s.
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    video = _video_with_impacts([(102.5, 0.9)])
    out, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=300.0
    )
    assert out[0].source.start_sec == pytest.approx(100.5)
    assert out[0].source.end_sec == pytest.approx(104.5)
    # timeline positions untouched
    assert out[0].timeline_start_sec == 0.0
    assert out[0].timeline_end_sec == 4.0
    assert len(regs) == 1
    assert regs[0]["shift_sec"] == pytest.approx(0.5)
    assert regs[0]["downbeat_sec"] == pytest.approx(2.0)


def test_register_respects_shift_budget():
    # Needed shift is 1.5s > budget -> no change, no registration.
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    video = _video_with_impacts([(103.5, 0.9)])
    out, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=300.0
    )
    assert out[0].source.start_sec == pytest.approx(100.0)
    assert regs == []


def test_register_respects_source_bounds():
    # Shift +0.5 would push source.end past effective_source_end -> skipped.
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    video = _video_with_impacts([(102.5, 0.9)])
    out, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=104.2
    )
    assert out[0].source.start_sec == pytest.approx(100.0)
    assert regs == []


def test_register_respects_uniqueness_against_other_shots():
    # Shifting shot 0 to 100.5 would land within 1.0s of shot 1's source start.
    shots = [_shot(0, 0.0, 4.0, 100.0), _shot(1, 4.0, 6.0, 101.2)]
    video = _video_with_impacts([(102.5, 0.9)])
    out, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=300.0
    )
    assert out[0].source.start_sec == pytest.approx(100.0)
    assert regs == []


def test_register_noop_without_impact_data():
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    out, regs = register_impacts_to_downbeats(
        shots, {"source": {"duration_sec": 300.0}}, [2.0], effective_source_end=300.0
    )
    assert out[0].source.start_sec == pytest.approx(100.0)
    assert regs == []


def test_register_already_aligned_records_zero_shift():
    # Impact already lands exactly on the downbeat -> recorded, not shifted.
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    video = _video_with_impacts([(102.0, 0.9)])
    out, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=300.0
    )
    assert out[0].source.start_sec == pytest.approx(100.0)
    assert len(regs) == 1
    assert regs[0]["shift_sec"] == pytest.approx(0.0)


def test_register_prefers_strongest_impact():
    # The 0.9-intensity impact needs a +0.5 shift; the weak 0.2 one only -0.1.
    # The strongest impact wins.
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    video = _video_with_impacts([(101.9, 0.2), (102.5, 0.9)])
    out, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=300.0
    )
    assert out[0].source.start_sec == pytest.approx(100.5)
    assert regs[0]["impact_sec"] == pytest.approx(102.5)


# ------------------------------------------------ split_overlong_section_shots


CHORUS_SECTIONS = [{"start_sec": 0.0, "end_sec": 30.0, "label": "chorus"}]


def test_split_overlong_chorus_shot_at_downbeats():
    # 6s chorus shot, band (1.0, 2.0): split at downbeats 2.0 and 4.0 into 3 pieces.
    bands = pacing_bands_for(120.0)
    shots = [_shot(0, 0.0, 6.0, 50.0)]
    out, splits = split_overlong_section_shots(
        shots, CHORUS_SECTIONS, [0.0, 2.0, 4.0, 6.0], bands, effective_source_end=300.0
    )
    assert [s.timeline_start_sec for s in out] == [0.0, 2.0, 4.0]
    assert [s.timeline_end_sec for s in out] == [2.0, 4.0, 6.0]
    # piece 1 keeps its source; later pieces jump forward (+2.0s default jump)
    assert out[0].source.start_sec == pytest.approx(50.0)
    assert out[0].source.end_sec == pytest.approx(52.0)
    assert out[1].source.start_sec == pytest.approx(54.0)
    assert out[2].source.start_sec == pytest.approx(56.0)
    # contiguous indices
    assert [s.index for s in out] == [0, 1, 2]
    assert len(splits) == 1
    assert splits[0]["pieces"] == 3


def test_split_leaves_short_chorus_shot_alone():
    bands = pacing_bands_for(120.0)  # trigger is 2 * 2.0 = 4.0s
    shots = [_shot(0, 0.0, 3.5, 50.0)]
    out, splits = split_overlong_section_shots(
        shots, CHORUS_SECTIONS, [0.0, 2.0], bands, effective_source_end=300.0
    )
    assert len(out) == 1
    assert splits == []


def test_split_leaves_verse_shot_alone():
    bands = pacing_bands_for(120.0)
    sections = [{"start_sec": 0.0, "end_sec": 30.0, "label": "verse"}]
    shots = [_shot(0, 0.0, 6.0, 50.0)]
    out, splits = split_overlong_section_shots(
        shots, sections, [0.0, 2.0, 4.0, 6.0], bands, effective_source_end=300.0
    )
    assert len(out) == 1
    assert splits == []


def test_split_aborts_when_jump_would_overrun_source():
    bands = pacing_bands_for(120.0)
    shots = [_shot(0, 0.0, 6.0, 50.0)]
    out, splits = split_overlong_section_shots(
        shots, CHORUS_SECTIONS, [0.0, 2.0, 4.0, 6.0], bands, effective_source_end=55.0
    )
    assert len(out) == 1
    assert out[0].source.start_sec == pytest.approx(50.0)
    assert splits == []


def test_split_jumps_to_next_impact_when_available():
    # 4.4s chorus shot splits once at downbeat 2.0; the second piece jumps to the
    # next impact frame (57.0) instead of the +2.0s default.
    bands = pacing_bands_for(120.0)
    shots = [_shot(0, 0.0, 4.4, 50.0)]
    video = _video_with_impacts([(57.0, 0.8)])
    out, splits = split_overlong_section_shots(
        shots,
        CHORUS_SECTIONS,
        [0.0, 2.0, 4.0],
        bands,
        video=video,
        effective_source_end=300.0,
    )
    assert len(out) == 2
    assert out[0].source.start_sec == pytest.approx(50.0)
    assert out[1].source.start_sec == pytest.approx(57.0)
    assert out[1].timeline_start_sec == pytest.approx(2.0)
    assert out[1].timeline_end_sec == pytest.approx(4.4)


def test_split_preserves_transition_on_first_piece_only():
    from api.prototyping.edit.synthesis.timeline_schema import Transition

    bands = pacing_bands_for(120.0)
    shot = _shot(0, 0.0, 6.0, 50.0).model_copy(
        update={"transition_in": Transition(type="crossfade", duration_sec=0.3)}
    )
    out, _ = split_overlong_section_shots(
        [shot], CHORUS_SECTIONS, [0.0, 2.0, 4.0, 6.0], bands, effective_source_end=300.0
    )
    assert out[0].transition_in.type == "crossfade"
    assert all(s.transition_in.type == "cut" for s in out[1:])


# ----------------------------------------------------------- auto_accent_overlays


def test_auto_accents_pick_strongest_registrations():
    from api.prototyping.edit.synthesis.rhythm import auto_accent_overlays

    registrations = [
        {"shot_index": 0, "impact_sec": 101.0, "downbeat_sec": 2.0, "shift_sec": 0.1, "intensity": 0.4},
        {"shot_index": 1, "impact_sec": 201.0, "downbeat_sec": 6.0, "shift_sec": 0.0, "intensity": 0.9},
        {"shot_index": 2, "impact_sec": 301.0, "downbeat_sec": 10.0, "shift_sec": 0.2, "intensity": 0.7},
    ]
    accents = auto_accent_overlays(registrations, 12.0, max_accents=2)

    assert len(accents) == 2
    assert accents[0]["skill_id"] == "impact.shake"
    # strongest first: downbeats 6.0 then 10.0; window is [d-0.05, d+0.40]
    assert accents[0]["start_time"] == pytest.approx(5.95)
    assert accents[0]["end_time"] == pytest.approx(6.4)
    assert accents[1]["start_time"] == pytest.approx(9.95)


def test_auto_accents_clamp_to_reel_bounds():
    from api.prototyping.edit.synthesis.rhythm import auto_accent_overlays

    registrations = [
        {"shot_index": 0, "impact_sec": 1.0, "downbeat_sec": 0.02, "shift_sec": 0.0, "intensity": 0.9},
    ]
    accents = auto_accent_overlays(registrations, 0.3, max_accents=2)
    assert accents[0]["start_time"] == pytest.approx(0.0)
    assert accents[0]["end_time"] == pytest.approx(0.3)


def test_registration_records_carry_intensity():
    shots = [_shot(0, 0.0, 4.0, 100.0)]
    video = _video_with_impacts([(102.5, 0.9)])
    _, regs = register_impacts_to_downbeats(
        shots, video, [2.0], effective_source_end=300.0
    )
    assert regs[0]["intensity"] == pytest.approx(0.9)


# ------------------------------------------------------------------ sync_report


def test_sync_report_counts_on_beat_cuts_and_registrations():
    song = {
        "source": {"duration_sec": 6.0},
        "tempo_bpm": 120.0,
        "beats_sec": [0.5, 2.0, 4.5],
        "downbeats_sec": [2.0],
        "segments": [{"start_sec": 0.0, "end_sec": 6.0, "label": "chorus"}],
    }
    # Interior boundaries at 1.96 and 4.46 (both one lead early of a beat).
    shots = [
        _shot(0, 0.0, 1.96, 10.0),
        _shot(1, 1.96, 4.46, 60.0),
        _shot(2, 4.46, 6.0, 120.0),
    ]
    # Shot 1's impact at source 60.04 lands at 1.96+(60.04-60)=2.0, the downbeat.
    video = _video_with_impacts([(60.04, 0.9)])

    report = sync_report(shots, song, video)

    assert report["interior_cut_count"] == 2
    assert report["cuts_on_beat_pct"] == pytest.approx(100.0)
    assert report["cuts_on_downbeat_pct"] == pytest.approx(50.0)
    assert report["cut_offset_median_sec"] == pytest.approx(-CUT_LEAD_SEC)
    assert report["impact_on_downbeat_shots"] == 1
    assert report["shot_count"] == 3
    assert "chorus" in report["sections"]
    assert report["sections"]["chorus"]["mean_shot_sec"] == pytest.approx(2.0)


def test_sync_report_handles_missing_data():
    song = {"source": {"duration_sec": 6.0}}
    shots = [_shot(0, 0.0, 6.0, 10.0)]
    report = sync_report(shots, song, {"source": {"duration_sec": 300.0}})
    assert report["interior_cut_count"] == 0
    assert report["shot_count"] == 1
