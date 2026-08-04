# Reach Hygiene (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the distribution-level penalties Eclypte's auto-created reels currently trip — letterbox demotion, anti-loop fade, hashtag walls, near-duplicate windows, trailer-structure montages — without any new external integration.

**Architecture:** Control-plane-only changes: autopilot export/window constants (`api/autopilot.py`), the tail-fade contract (`timeline_schema.py` helper consumed by the adapter — both renderers already no-op on zero fades), caption/hashtag generation (`api/publishing.py`), a new `edit_focus` request field threaded app → workflows → agent that swaps the injected source-coverage block, and adapter telemetry. No new services; one Modal redeploy at the end purely because a bundled file (`timeline_schema.py`) changes.

**Tech Stack:** FastAPI + Pydantic v2 (strict models), pytest with the existing in-memory fakes, Next.js 16 typed client (`eclypteApi.ts`), OpenAI Responses API caption model.

**Spec:** `docs/superpowers/specs/2026-08-04-reels-reach-recovery-design.md`

## Global Constraints

- Run backend tests with `.venv/bin/python -m pytest ...` from the repo root (system pythons lack deps).
- Every new Pydantic field is additive with a default so persisted R2 JSON (autopilot state, run inputs) keeps loading. `AutopilotState` uses `extra="forbid"` — new fields must be added to the model, never smuggled.
- `edit_focus` values are exactly `"full_source"` and `"moment"`; anything absent/unknown resolves to `"full_source"`.
- The fade change must keep timeline JSON schema-compatible: values ride the existing `fade_out_sec` fields; the old deployed renderer image renders them correctly.
- Caption/hashtag output contract: ≤5 hashtags, never `#fyp`/`#foryou`/`#viral`/`#trending`/bare `#edit`/bare `#anime`; captions ≤2200 chars.
- Frontend verification: `npm run lint` && `npm run build` from `web/`.
- Keep `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `api/COMMANDS.md` reconciled in the final task — several currently document the old constants (`reels_cinematic` autopilot default, ≈5s chorus lead-in, audio+video tail fade).

---

### Task 1: Autopilot renders fill-frame (`reels_9_16`)

**Files:**
- Modify: `api/autopilot.py:434-438` (the `export_options` dict in `start_trimmed_edit`)
- Test: `api/test_autopilot.py:290`, `api/test_autopilot.py:518`

- [ ] **Step 1: Update the two existing assertions to expect the new format**

In `api/test_autopilot.py` line 290 change `assert options["format"] == "reels_cinematic"` to:

```python
    assert options["format"] == "reels_9_16"
```

Line 518 change `assert runs[0]["inputs"]["export_format"] == "reels_cinematic"` to:

```python
    assert runs[0]["inputs"]["export_format"] == "reels_9_16"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k "trim_window or export"`
Expected: the two touched tests FAIL (still receiving `reels_cinematic`)

- [ ] **Step 3: Implement**

In `api/autopilot.py` `start_trimmed_edit`, change the export options dict:

```python
        export_options: dict[str, object] = {
            # Fill-frame: letterboxed reels sit on Instagram's official
            # "shown less often" list and leave ~24% picture for a 2.39:1 film.
            "format": "reels_9_16",
            "audio_start_sec": window[0],
            "audio_end_sec": window[1],
        }
```

- [ ] **Step 4: Run the autopilot suite**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/autopilot.py api/test_autopilot.py
git commit -m "feat(autopilot): render auto reels fill-frame (reels_9_16), not letterboxed"
```

---

### Task 2: Chorus lead-in 5s → 1.5s

**Files:**
- Modify: `api/autopilot.py:37-39` (`CHORUS_LEAD_IN_SEC` + comment)
- Test: `api/test_autopilot.py:140-151` (`test_select_trim_windows_prefers_high_energy_chorus`)

- [ ] **Step 1: Update the window test**

The existing test (line 140) asserts a window starting ~5s before the chorus (see its comment on line 145). Update the expected start to 1.5s before the chorus section start and the comment to match, e.g. if the chorus starts at 60.0 the expectation becomes `54.999 <= start` → `58.5`:

```python
    # Begins CHORUS_LEAD_IN_SEC (1.5s) before the chorus: enough for the hook
    # shot to register before the drop, without opening on 5s of build-up.
    assert windows[0][0] == pytest.approx(58.5, abs=0.001)
```

(Adjust the literal to the fixture's actual chorus start minus 1.5 — read the fixture in the test body.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v -k chorus`
Expected: FAIL (window still starts 5s early)

- [ ] **Step 3: Implement**

```python
# Begin a section-anchored window this many seconds before the section starts.
# Kept short deliberately: the first ~2s decide stay-or-scroll, so the reel
# must not open on a long pre-chorus build.
CHORUS_LEAD_IN_SEC = 1.5
```

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest api/test_autopilot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/autopilot.py api/test_autopilot.py
git commit -m "feat(autopilot): open trim windows 1.5s before the section, not 5s"
```

---

### Task 3: Loop-friendly tail fade for short reels

**Files:**
- Modify: `api/prototyping/edit/synthesis/timeline_schema.py:7-21`
- Modify: `api/prototyping/edit/synthesis/adapter.py:282-294`
- Test: `api/prototyping/edit/synthesis/test_adapter.py:618-630`

**Interfaces:** `tail_fades_for(duration_sec: float) -> tuple[float, float]` returning `(audio_fade_sec, video_fade_sec)`. `tail_fade_for` is replaced (adapter + tests are its only consumers — verify with `git grep -n tail_fade_for`).

- [ ] **Step 1: Rewrite the fade tests**

Replace `test_tail_fade_for_clamps_to_a_third_of_short_reels` (test_adapter.py:618) with:

```python
def test_tail_fades_split_short_reels_from_long_form():
    from api.prototyping.edit.synthesis.timeline_schema import (
        SHORT_REEL_AUDIO_FADE_SEC,
        TAIL_FADE_SEC,
        tail_fades_for,
    )

    # Short reels (<=40s): tiny audio-only fade, NO fade-to-black — a visible
    # fade tells the viewer "it's over" and kills the loop/replay signal.
    assert tail_fades_for(25.0) == (SHORT_REEL_AUDIO_FADE_SEC, 0.0)
    assert tail_fades_for(40.0) == (SHORT_REEL_AUDIO_FADE_SEC, 0.0)
    # Long form keeps the classic tail fade on both tracks.
    assert tail_fades_for(120.0) == (TAIL_FADE_SEC, TAIL_FADE_SEC)
    assert tail_fades_for(41.0) == (TAIL_FADE_SEC, TAIL_FADE_SEC)
    assert tail_fades_for(0.0) == (0.0, 0.0)
```

The adjacent adapter-level test (lines ~625-630) asserting `tl.output.fade_out_sec == 2.0` / `tl.audio.fade_out_sec == 2.0` must now assert the split values for whatever duration its fixture produces (a ≤40s fixture ⇒ `output.fade_out_sec == 0.0`, `audio.fade_out_sec == SHORT_REEL_AUDIO_FADE_SEC`).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/prototyping/edit/synthesis/test_adapter.py -v -k fade`
Expected: FAIL with `ImportError: cannot import name 'tail_fades_for'`

- [ ] **Step 3: Implement the helper**

In `timeline_schema.py`, replacing `tail_fade_for`:

```python
TAIL_FADE_SEC = 2.5
# Reels at or under this length are loop-optimized: replays count as views,
# and a visible fade-to-black breaks the loop illusion. Matches the agent's
# SHORT_EDIT_MAX_SEC threshold.
SHORT_REEL_MAX_SEC = 40.0
SHORT_REEL_AUDIO_FADE_SEC = 0.3


def tail_fades_for(duration_sec: float) -> tuple[float, float]:
    """(audio_fade_sec, video_fade_sec) for the end of the reel.

    Short reels get a click-prevention audio fade only — the picture hard-ends
    so the reel loops back into its opening. Long form keeps the classic
    audio+video tail fade, clamped to a third of the piece.
    """
    if duration_sec <= 0:
        return 0.0, 0.0
    if duration_sec <= SHORT_REEL_MAX_SEC:
        return SHORT_REEL_AUDIO_FADE_SEC, 0.0
    fade = round(min(TAIL_FADE_SEC, duration_sec / 3.0), 3)
    return fade, fade
```

In `adapter.py` (line 282), replace the single-fade wiring:

```python
    audio_fade, video_fade = tail_fades_for(round(last_end, 3))
```

and use `fade_out_sec=video_fade` in `OutputSpec`, `fade_out_sec=audio_fade` in `AudioSpec`. Update the `tail_fade_for` import (adapter.py:21) to `tail_fades_for`.

- [ ] **Step 4: Run adapter + render suites**

Run: `.venv/bin/python -m pytest api/prototyping/edit/synthesis -v && .venv/bin/python -m pytest api/prototyping/edit/render -v`
Expected: PASS (both renderers already skip `fade <= 0`: `ffmpeg_filtergraph.py:284-301` guards, `fades.py` returns the clip unchanged)

- [ ] **Step 5: Commit**

```bash
git add api/prototyping/edit/synthesis/timeline_schema.py api/prototyping/edit/synthesis/adapter.py api/prototyping/edit/synthesis/test_adapter.py
git commit -m "feat(edit): short reels hard-end for loops - audio-only 0.3s tail fade"
```

---

### Task 4: Niche-register captions, ≤5 fandom hashtags

**Files:**
- Modify: `api/publishing.py:351-375` (`_fallback_caption_draft`), `api/publishing.py:378-454` (`_openai_caption_draft`)
- Test: `api/test_publishing.py:176-260` (caption tests)

- [ ] **Step 1: Write/adjust the failing tests**

Update `test_fallback_hashtags_are_derived_from_names` (test_publishing.py:190) and add two tests:

```python
def test_fallback_caption_uses_credit_line_and_capped_fandom_hashtags():
    draft = _fallback_caption_draft(
        collection_slug="shonen", source_name="Attack on Titan", song_name="Believer"
    )
    lines = draft.caption.splitlines()
    assert lines[0] == "Attack on Titan edit"
    assert lines[1] == "anime: attack on titan · song: believer"
    assert len(draft.hashtags) <= 5
    assert "#fyp" not in draft.hashtags
    assert "#edit" not in draft.hashtags
    assert "#attackontitan" in draft.hashtags
    assert "#animeedit" in draft.hashtags


def test_openai_caption_prompt_bans_generic_tags_and_caps_hashtags():
    client = _FakeResponsesClient(
        {"caption": "ok this one ate", "hashtags": ["#gojo", "#JJK", "#fyp", "#animeedit", "#viral", "#jujutsukaisen", "#amv"], "notes": ""}
    )
    draft = generate_caption_draft(
        source_name="Jujutsu Kaisen", song_name="Tek It", openai_client=client
    )
    instructions = client.captured_kwargs["instructions"]
    assert "#fyp" in instructions  # named in the ban list
    assert "3-5" in instructions or "at most 5" in instructions
    assert len(draft.hashtags) <= 5
    assert "#fyp" not in draft.hashtags
    assert "#viral" not in draft.hashtags
```

(Reuse the module's existing fake-OpenAI pattern from `test_openai_caption_generation_uses_responses_api_and_records_provenance` — the fake must expose `captured_kwargs`; extend it if it doesn't.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k caption`
Expected: new tests FAIL (old template `"... edit fr 🔥"`, `#fyp` present, >5 tags)

- [ ] **Step 3: Implement**

Add a module-level banned-tag set + filter next to `_dedupe_hashtags`:

```python
GENERIC_HASHTAG_BANS = {"#fyp", "#foryou", "#foryoupage", "#viral", "#trending", "#edit", "#anime", "#explore", "#explorepage"}
MAX_HASHTAGS = 5


def _finalize_hashtags(values: list[str]) -> list[str]:
    cleaned = [tag for tag in _dedupe_hashtags(values) if tag not in GENERIC_HASHTAG_BANS]
    return cleaned[:MAX_HASHTAGS]
```

Rewrite `_fallback_caption_draft`:

```python
def _fallback_caption_draft(
    *,
    collection_slug: str = "",
    source_name: str = "",
    song_name: str = "",
) -> CaptionDraft:
    label = source_name or _humanize(collection_slug)
    hook = f"{label} edit" if label else "new edit"
    credit_parts = []
    if source_name:
        credit_parts.append(f"anime: {source_name.lower()}")
    if song_name:
        credit_parts.append(f"song: {song_name.lower()}")
    caption = hook if not credit_parts else f"{hook}\n{' · '.join(credit_parts)}"
    hashtags = _finalize_hashtags(
        [
            "#animeedit",
            "#amv",
            _hashtag(source_name) if source_name else "",
            _hashtag(song_name) if song_name else "",
            _hashtag(collection_slug) if collection_slug else "",
        ]
    )
    return CaptionDraft(caption=caption[:2200], hashtags=hashtags, caption_source="fallback")
```

Rewrite `_openai_caption_draft`'s `instructions` (keep the Responses-API mechanics, JSON schema `hashtags.maxItems` 12 → 5, and the final `_dedupe_hashtags(...)[:30]` → `_finalize_hashtags(...)`):

```python
        instructions=(
            "You write Instagram Reels captions for anime/movie edits (AMVs) the way a "
            "real Gen-Z creator posts them — NOT like a brand, marketer, or AI. "
            "Return only valid JSON with keys caption, hashtags, and notes.\n"
            "STRUCTURE — up to three short lines, in this order:\n"
            "1. Hook: one casual, mostly-lowercase line, at most 1-2 emojis, a real "
            "reaction to THIS edit. When it reads naturally, work the source or song "
            "name into it — people find reels by searching those exact words.\n"
            "2. Credit line, exactly this shape: 'anime: <source> · song: <song>' "
            "(lowercase; use 'film:' for live-action; drop a part if unknown).\n"
            "3. OPTIONAL: either ONE genuine fandom question about the source, or a "
            "natural nudge to send this to a friend who loves it. Never both; skip "
            "when forced. NEVER formulaic bait: no 'comment YES', 'like if', "
            "'tag 3 friends', 'follow for more'.\n"
            "HARD BANS (these scream AI): listing pacing/transitions/energy; the "
            "phrases 'hits different', 'quick thoughts', 'if you're into', 'worth the "
            "watch', 'drop a rating', 'the vibe', 'let that sink in'; em dashes; any "
            "corporate/marketing tone; claiming rights or official status.\n"
            "Vary the hook every time. Vibe examples (DO NOT copy, just match the "
            "energy): 'ok this one ate'; 'no bc why did this go so hard'; 'they "
            "really said cinema'; 'this is my roman empire fr'.\n"
            "hashtags = 3-5 lowercase tags, at most 5, ALL specific to this reel: "
            "the source (e.g. #jujutsukaisen), the song or artist, a main character "
            "or the fandom's own tag, plus #animeedit or #amv. NEVER generic "
            "discovery tags — no #fyp, #foryou, #viral, #trending, #edit, #anime "
            "alone. No spaces or punctuation.\n"
            "notes = a brief internal note for the editor."
        ),
```

- [ ] **Step 4: Run the publishing suite**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v`
Expected: PASS (fix any other test asserting the old template/tags)

- [ ] **Step 5: Commit**

```bash
git add api/publishing.py api/test_publishing.py
git commit -m "feat(publishing): niche-register captions with credit line, cap hashtags at 5 fandom tags"
```

---

### Task 5: Strip release junk from media-derived names

**Files:**
- Modify: `api/publishing.py:486-503` (`_display_name_for_file` + new `_clean_media_name`)
- Test: `api/test_publishing.py`

- [ ] **Step 1: Write the failing test**

```python
def test_media_names_lose_scene_release_junk():
    assert _clean_media_name("Your.Name.2016.1080p.BluRay.x265-GROUP") == "Your Name 2016"
    assert _clean_media_name("Attack_on_Titan_S4_[Dual-Audio]_HEVC") == "Attack on Titan S4"
    assert _clean_media_name("Believer (Official Audio) 320kbps") == "Believer"
    assert _clean_media_name("plain name") == "plain name"
    assert _clean_media_name("1080p.x265") == "1080p.x265"  # all-junk falls back to input
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v -k junk`
Expected: FAIL with `NameError`/import error

- [ ] **Step 3: Implement**

```python
_MEDIA_NAME_JUNK = {
    "480p", "720p", "1080p", "2160p", "4k", "8k",
    "x264", "x265", "h264", "h265", "hevc", "av1", "10bit", "8bit",
    "hdr", "hdr10", "sdr", "bluray", "bdrip", "brrip", "webrip", "webdl",
    "web-dl", "hdtv", "dvdrip", "remux", "amzn", "nf",
    "aac", "ac3", "eac3", "dts", "truehd", "atmos", "flac", "opus",
    "320kbps", "128kbps", "dual-audio", "multi", "subbed", "dubbed",
    "proper", "repack", "remastered", "official", "audio", "video", "lyrics",
}


def _clean_media_name(name: str) -> str:
    """Upload filenames leak scene-release junk (1080p, x265, [group]) into
    captions and hashtags; strip it, falling back to the input when stripping
    would leave nothing."""
    base = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", name)
    base = re.sub(r"[._]+", " ", base)
    tokens = [t for t in base.split() if t.lower().strip("-") not in _MEDIA_NAME_JUNK]
    cleaned = " ".join(tokens).strip(" -")
    return cleaned or name.strip()
```

(Add `import re` to the module imports if absent.) Wire it into `_display_name_for_file`:

```python
    return _clean_media_name(_strip_media_extension(manifest.display_name))
```

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest api/test_publishing.py -v`
Expected: PASS (`test_caption_input_includes_source_and_song` and `test_regenerate_caption_passes_persisted_names` must still pass — their fixtures use clean names)

- [ ] **Step 5: Commit**

```bash
git add api/publishing.py api/test_publishing.py
git commit -m "fix(publishing): strip scene-release junk from source/song display names"
```

---

### Task 6: Overlap-aware trim-window dedupe

**Files:**
- Modify: `api/storage/models.py` (`AutopilotState`), `api/autopilot.py` (pure helper + `start_trimmed_edit` + recycle-clear + state threading)
- Test: `api/storage/test_models.py`, `api/test_autopilot.py`

**Interfaces:** `AutopilotState.used_windows: dict[str, list[list[float]]]` (pair_key → `[start, end]` list); pure `window_overlap_frac(a, b) -> float`; `MAX_WINDOW_OVERLAP_FRAC = 0.4`.

- [ ] **Step 1: Write the failing tests**

`api/storage/test_models.py`:

```python
def test_autopilot_state_used_windows_defaults_and_round_trips():
    state = AutopilotState(owner_user_id="u1")
    assert state.used_windows == {}
    stamped = state.model_copy(update={"used_windows": {"f1::s1": [[10.0, 35.0]]}})
    reloaded = AutopilotState.model_validate(stamped.model_dump(mode="json"))
    assert reloaded.used_windows == {"f1::s1": [[10.0, 35.0]]}
```

`api/test_autopilot.py`:

```python
def test_window_overlap_frac_measures_against_shorter_window():
    assert window_overlap_frac((10.0, 35.0), (15.0, 40.0)) == pytest.approx(0.8)
    assert window_overlap_frac((10.0, 35.0), (40.0, 65.0)) == 0.0
    assert window_overlap_frac((10.0, 35.0), (30.0, 70.0)) == pytest.approx(0.2)


def test_tick_rejects_window_overlapping_a_used_one():
    # Arrange the existing trim-window tick fixture so the top-ranked window
    # overlaps a previously used window by >40% (used_windows on the state);
    # the tick must start the edit on the next non-overlapping candidate and
    # append the chosen window to used_windows for the pair.
    ...
```

(Build the second test on `test_tick_skips_already_used_combo_without_counting_failure` (line 389) — same fakes, but pre-populate `used_windows` instead of `used_combos` and assert both the chosen `audio_start_sec` and the new `used_windows` entry.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/storage/test_models.py -k used_windows -v && .venv/bin/python -m pytest api/test_autopilot.py -k overlap -v`
Expected: FAIL (missing field / missing function)

- [ ] **Step 3: Implement**

`api/storage/models.py`, on `AutopilotState` after `used_combos`:

```python
    # pair_key -> [start_sec, end_sec] windows already rendered for that pair.
    # Complements used_combos (exact 5s-bucket identity): a candidate window
    # overlapping any listed window by >40% is treated as already used.
    used_windows: dict[str, list[list[float]]] = Field(default_factory=dict)
```

`api/autopilot.py`, next to `combo_key`:

```python
# A candidate trim window overlapping a used window of the same pair by more
# than this fraction (of the shorter window) is a near-duplicate reel: same
# song section, ~same footage. Near-dupes are an enforcement risk, not just
# waste.
MAX_WINDOW_OVERLAP_FRAC = 0.4


def window_overlap_frac(a: tuple[float, float], b: tuple[float, float]) -> float:
    overlap = min(a[1], b[1]) - max(a[0], b[0])
    shorter = min(a[1] - a[0], b[1] - b[0])
    if overlap <= 0 or shorter <= 0:
        return 0.0
    return overlap / shorter
```

In `_run_tick_locked`: pull `used_windows = dict(state.used_windows)` alongside `used_combos`, save it back on the state write. In `start_trimmed_edit` replace the window selection:

```python
        key = pair_key(item.source_video_file_id, item.song_file_id)
        pair_windows = [tuple(w) for w in used_windows.get(key, [])]
        window = next(
            (
                candidate
                for candidate in windows
                if combo_key(item.source_video_file_id, item.song_file_id, candidate)
                not in used_combos
                and all(
                    window_overlap_frac(candidate, used) <= MAX_WINDOW_OVERLAP_FRAC
                    for used in pair_windows
                )
            ),
            None,
        )
```

and after a successful `start_edit`, alongside the `used_combos.append(...)`:

```python
        used_windows.setdefault(key, []).append([window[0], window[1]])
```

In the recycle branch (autopilot.py:562-566), clear the pair's windows too:

```python
                    used_windows.pop(key, None)
```

(the `key = pair_key(...)` local already exists there).

- [ ] **Step 4: Run the suites**

Run: `.venv/bin/python -m pytest api/test_autopilot.py api/storage/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/storage/models.py api/autopilot.py api/test_autopilot.py api/storage/test_models.py
git commit -m "feat(autopilot): reject trim windows overlapping used ones >40% - no near-duplicate reels"
```

---

### Task 7: `edit_focus` — moment-focused edits for autopilot

**Files:**
- Modify: `api/prototyping/edit/synthesis/agent.py` (new `_format_moment_context`, `run_synthesis_loop` param + block selection at lines 478-479)
- Modify: `api/prototyping/edit/synthesis/system_prompt.py` (span bullet escape clause)
- Modify: `api/workflows.py` (`run_edit_pipeline` ~142, `_run_edit_timeline` ~509-575, `_run_agent_timeline_plan` ~1078-1082, `_run_agent_synthesis` ~1765)
- Modify: `api/app.py` (`EditJobRequest`, `TimelineRequest`, edits/timelines/redo routes, autopilot `start_edit` closure ~783-801)
- Modify: `api/autopilot.py` (`StartEdit` protocol + `start_trimmed_edit` call)
- Modify: `web/src/services/eclypteApi.ts` (`EditJobRequest` type)
- Test: `api/prototyping/edit/synthesis/test_agent.py`, `api/test_autopilot.py`, `api/test_workflows.py`

- [ ] **Step 1: Write the failing agent test**

In `test_agent.py` (follow its existing pattern of asserting on the assembled user content via a fake client/loop — mirror how the span-guidance/source-context tests are written):

```python
def test_moment_focus_swaps_source_context():
    content = build_user_content_for_test(  # use the module's existing helper/fake pattern
        source_duration_sec=5400.0, edit_focus="moment"
    )
    assert "FOCUSED MOMENT EDIT" in content
    assert "Span the FULL content" not in content
    assert "first cut within ~1.5s" in content


def test_default_focus_keeps_span_guidance():
    content = build_user_content_for_test(source_duration_sec=5400.0)
    assert "Span the FULL content" in content
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/prototyping/edit/synthesis/test_agent.py -v -k focus`
Expected: FAIL (`run_synthesis_loop` has no `edit_focus` param)

- [ ] **Step 3: Implement the agent side**

`agent.py` — add below `_format_source_context`:

```python
def _format_moment_context(source_duration_sec: float) -> str:
    d = float(source_duration_sec)
    return (
        f"Source video: {d:.0f} seconds long.\n"
        f"FOCUSED MOMENT EDIT — this run overrides any instruction (including in "
        f"the system prompt) to span the full source: build the entire reel around "
        f"ONE sequence, scene, or character arc instead of covering the film. Query "
        f"for the source's single most iconic, high-impact stretch (a fight, a "
        f"transformation, an entrance, an emotional peak), then draw every shot "
        f"from that stretch and its immediate surroundings, in order. Dwelling is "
        f"the point: stay with the moment, let consecutive shots continue each "
        f"other, and make the reel feel like the best scene in the film rather "
        f"than a trailer.\n"
        f"The hook still rules: open on the single hardest frame of the chosen "
        f"stretch, first cut within ~1.5s.\n"
        f"IMPORTANT: the source's first minutes (logos, title cards, opening "
        f"credits) and final stretch (end credits, often over a COLORED background) "
        f"remain OFF-LIMITS. Every source_timestamp must come from a query_clips "
        f"result (a 1-2s nudge is fine) — never invented, and never near either "
        f"end of the source unless the query result there is unmistakably story "
        f"content."
    )
```

`run_synthesis_loop(...)` gains `edit_focus: str = "full_source"`; the source-context block (lines 478-479) becomes:

```python
    if source_duration_sec is not None and float(source_duration_sec) > 0:
        if edit_focus == "moment":
            context_blocks.append(_format_moment_context(source_duration_sec))
        else:
            context_blocks.append(_format_source_context(source_duration_sec))
```

`system_prompt.py` — extend the span bullet's first sentence:

```
- Span the full source from beginning to end regardless of song length (unless the run context declares a FOCUSED MOMENT EDIT — then concentrate on that one scene instead): ...
```

- [ ] **Step 4: Thread it through workflows, app, autopilot**

- `_run_agent_synthesis` (workflows.py:1765): add `edit_focus: str = "full_source"` and pass to `run_synthesis_loop`.
- `_run_agent_timeline_plan` (~1078): `edit_focus = str(kwargs.get("edit_focus") or "full_source")`, pass into `_run_agent_synthesis`.
- `run_edit_pipeline` (~142): `edit_focus = str(kwargs.get("edit_focus") or "full_source")`; pass into `_run_edit_timeline`, which adds `"edit_focus": edit_focus` to the child timeline run's inputs and schedule kwargs.
- `app.py`: `EditJobRequest` and `TimelineRequest` gain `edit_focus: Literal["full_source", "moment"] = "full_source"`; the edits route records it in the parent run inputs (~729) and schedules with `edit_focus=request.edit_focus` (~740); the timelines route passes it (~1696); the redo route rebuilds with `edit_focus=run.inputs.get("edit_focus", "full_source")` (~1849).
- Autopilot `StartEdit` protocol (autopilot.py:81-91) gains `edit_focus: str`; the app.py closure (~783) accepts and forwards it into `EditJobRequest`; `start_trimmed_edit` passes `edit_focus="moment"`.
- `web/src/services/eclypteApi.ts`: add `edit_focus?: "full_source" | "moment"` to the `EditJobRequest` type (~line 273) and pass it through in the client method that posts `/v1/edits`.

- [ ] **Step 5: Extend the autopilot + workflows tests**

In `api/test_autopilot.py`, the fake `start_edit` in the trim-window test captures kwargs — assert `captured["edit_focus"] == "moment"`. In `api/test_workflows.py`, extend an edit-pipeline test to send `edit_focus="moment"` and assert the child timeline run's inputs carry it.

- [ ] **Step 6: Run everything backend + frontend**

Run: `.venv/bin/python -m pytest api/prototyping/edit/synthesis api/test_autopilot.py api/test_workflows.py api/test_api_v1.py -v`
Expected: PASS
Run: `cd web && npm run lint && npm run build`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add api/prototyping/edit/synthesis/agent.py api/prototyping/edit/synthesis/system_prompt.py api/workflows.py api/app.py api/autopilot.py web/src/services/eclypteApi.ts api/prototyping/edit/synthesis/test_agent.py api/test_autopilot.py api/test_workflows.py
git commit -m "feat(edit): edit_focus=moment - autopilot reels edit one scene, not the whole film"
```

---

### Task 8: First-shot hook telemetry

**Files:**
- Modify: `api/prototyping/edit/synthesis/adapter.py` (report_sink block ~304)
- Test: `api/prototyping/edit/synthesis/test_adapter.py`

- [ ] **Step 1: Write the failing test**

Using the existing `adapt(..., report_sink=...)` test pattern:

```python
def test_sync_report_records_first_shot_hook():
    report: dict = {}
    adapt(  # reuse an existing fixture whose video analysis has impact frames
        ..., report_sink=report
    )
    first = report["first_shot"]
    assert first["source_start_sec"] >= 0
    assert first["duration_sec"] > 0
    assert isinstance(first["impact_backed"], bool)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest api/prototyping/edit/synthesis/test_adapter.py -v -k first_shot`
Expected: FAIL with `KeyError: 'first_shot'`

- [ ] **Step 3: Implement**

In `adapter.py` where `report_sink` is populated (~304), add (importing `_impact_frames` from `.rhythm`):

```python
        if shots:
            first = shots[0]
            impacts = _impact_frames(video)
            report_sink["first_shot"] = {
                "source_start_sec": round(first.source.start_sec, 3),
                "duration_sec": round(first.duration_sec, 3),
                # A weak opener is the #1 retention failure; QA reads this
                # instead of scrubbing the render.
                "impact_backed": any(
                    first.source.start_sec <= ts <= first.source.end_sec
                    for ts, _ in impacts
                ),
            }
```

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest api/prototyping/edit/synthesis -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/prototyping/edit/synthesis/adapter.py api/prototyping/edit/synthesis/test_adapter.py
git commit -m "feat(edit): record first-shot hook telemetry in timeline_sync_report"
```

---

### Task 9: Docs, full suite, deploy checklist

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `api/COMMANDS.md`

- [ ] **Step 1: Reconcile docs**

Update every mention of: autopilot's default format (`reels_cinematic` → `reels_9_16`; `reels_cinematic` remains available for manual composes), the ≈5s chorus lead-in (now 1.5s), the audio+video tail fade (short reels: 0.3s audio-only, hard video end for loops), caption/hashtag behavior (≤5 fandom tags, credit line, no `#fyp`), the new `edit_focus` field and autopilot's moment default, `used_windows` dedupe, and the `first_shot` sync-report entry. Record the Phase 0 operator-diagnosis results here if available.

- [ ] **Step 2: Full verification**

Run: `.venv/bin/python -m pytest api -v`
Expected: PASS
Run: `cd web && npm run lint && npm run build`
Expected: clean

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md AGENTS.md ARCHITECTURE.md api/COMMANDS.md
git commit -m "docs: reconcile reach-hygiene changes (fill format, loop ending, captions, edit_focus)"
```

- [ ] **Step 4: Deploy checklist (operator)**

- Redeploy `eclypte-render-r2` — policy: `timeline_schema.py` (a bundled file) changed. Behavior rides existing `fade_out_sec` fields, so the old image renders new timelines correctly, but keep image and repo in lockstep.
- No reindex, no other Modal app changes.
- QA the first post-change reel: full-frame (no bars), hard video ending that cuts back cleanly, ≤5 fandom hashtags with the credit line, one scene (not a whole-film montage), and check `timeline_sync_report.first_shot.impact_backed`.
