import pytest

from api.prototyping.edit.synthesis.style_profile import derive_style_profile


def _metrics(offset_median=None, densities=None):
    m = {}
    if offset_median is not None:
        m["cut_offsets_to_downbeats"] = {"n": 10, "median": offset_median}
    if densities:
        m["cut_density_per_section"] = {
            label: {"cuts_per_downbeat": cpd, "cuts_per_sec": 0.5}
            for label, cpd in densities.items()
        }
    return m


def test_lead_derived_from_negative_offset_medians():
    # References cut before the beat (negative offsets) -> a positive lead.
    profile = derive_style_profile([
        _metrics(offset_median=-0.06),
        _metrics(offset_median=-0.02),
    ])
    assert profile["cut_lead_sec"] == pytest.approx(0.04)
    assert profile["reference_count"] == 2


def test_lead_clamped_to_sane_range():
    assert derive_style_profile([_metrics(offset_median=-0.5)])["cut_lead_sec"] == pytest.approx(0.08)
    # cuts AFTER the beat never produce a negative lead
    assert derive_style_profile([_metrics(offset_median=0.3)])["cut_lead_sec"] == pytest.approx(0.0)


def test_pacing_bands_from_cut_density():
    # cuts_per_downbeat 2.0 -> 2.0 beats/shot (4-beat bars); band = (0.6m, 1.4m)
    profile = derive_style_profile([_metrics(densities={"chorus": 2.0})])
    lo, hi = profile["pacing_bands_beats"]["chorus"]
    assert lo == pytest.approx(1.2)
    assert hi == pytest.approx(2.8)


def test_pacing_bands_take_median_across_references():
    profile = derive_style_profile([
        _metrics(densities={"chorus": 2.0}),   # 2.0 beats/shot
        _metrics(densities={"chorus": 4.0}),   # 1.0 beats/shot
    ])
    lo, hi = profile["pacing_bands_beats"]["chorus"]
    # median beats/shot = 1.5 -> (max(1.0, 0.9), 1.4*1.5)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(2.1)


def test_empty_or_malformed_metrics_yield_empty_profile():
    assert derive_style_profile([]) == {}
    assert derive_style_profile([{}, {"cut_density_per_section": "garbage"}]) == {}
    assert derive_style_profile([{"cut_offsets_to_downbeats": {"median": None}}]) == {}


def test_partial_profile_when_only_density_available():
    profile = derive_style_profile([_metrics(densities={"verse": 1.0})])
    assert "cut_lead_sec" not in profile
    assert profile["pacing_bands_beats"]["verse"][0] > 0
    assert profile["reference_count"] == 1
