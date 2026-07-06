# Edit Quality Phases 2–4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port visual polish onto the fast native ffmpeg render path (Phase 2), ship the polish catalog — grades, impact shake, real speed ramp (Phase 3), and parameterize the rhythm engine from reference metrics (Phase 4).

**Architecture:** The skills registry generalizes from "moviepy overlays" to kinds (`overlay`/`grade`/`moment`) with an optional per-skill ffmpeg filter fragment; `build_command` in the pure filtergraph builder gains per-shot effect chains (freeze/punch_in/flash) and a post-assembly skill-fragment hook; `can_render_with_ffmpeg` becomes capability-driven so polished reels stay fast-path. New skills ride the existing `overlays` channel (a grade is a full-reel overlay). Phase 4 derives a style profile from completed synthesis-reference metrics at plan time (no persistence changes) and threads overrides into the rhythm engine + agent pacing guidance.

**Tech Stack:** Python 3.13, Pydantic v2, ffmpeg filter expressions, MoviePy v2 (fallback path only), pytest.

## Global Constraints

- TDD every task: failing test → minimal implementation → green → commit.
- Skill module-level code stays moviepy-free (control plane imports metadata on Railway).
- `build_command`/`ffmpeg_filtergraph.py` stays pure — no subprocess, no filesystem, no moviepy.
- Encode flags are immutable: CRF 18 / `-tune animation` / yuv420p / +faststart / AAC 192k.
- `can_render_with_ffmpeg` may return True for a feature ONLY in the same commit that implements the native port (never break live renders).
- Existing suites must stay green: `python -m pytest api -q` after each task.
- `eclypte-render-r2` must be redeployed after Phase 2 and Phase 3 land (flag to user; do not deploy from this session without confirmation).

---

## Phase 2 — ffmpeg polish foundation

### Task 1: Registry generalization (`kind`, `ffmpeg_supported`, `ffmpeg_filter`)

**Files:**
- Modify: `api/prototyping/edit/skills/base.py`
- Modify: `api/prototyping/edit/skills/registry.py` (agent_catalog gains `kind`)
- Test: `api/prototyping/edit/skills/test_registry.py`

**Interfaces:**
- Produces: `OverlaySkill.kind: str = "overlay"`, `OverlaySkill.ffmpeg_supported: bool = False`, `OverlaySkill.ffmpeg_filter(overlay: ResolvedOverlay, ctx: RenderContext) -> str` (raises NotImplementedError unless overridden; returns a label-free filter fragment such as `vignette=a=0.74:enable='between(t,0.000,6.000)'`). `agent_catalog()` entries gain `"kind"`.

- [ ] Failing tests: default kind/ffmpeg_supported on a bare skill; catalog includes kind; ffmpeg_filter raises by default.
- [ ] Implement attributes + catalog change. Run skills suite. Commit `feat(edit): skill kinds + ffmpeg capability declaration`.

### Task 2: freeze + punch_in per-shot chains in the filtergraph

**Files:**
- Modify: `api/prototyping/edit/render/ffmpeg_filtergraph.py`
- Test: `api/prototyping/edit/render/test_ffmpeg_filtergraph.py`

**Interfaces:**
- Produces: `_shot_window(shot)` returns a reduced input window for freeze shots; `_video_chain` emits `trim=end_frame=1,tpad=stop_mode=clone:stop_duration={dur+0.5}` at chain start for freeze and a trailing `trim=duration={dur},setpts=PTS-STARTPTS`; punch_in appends `crop=w='iw/(1+0.06*t/{dur})':h='ih/(1+0.06*t/{dur})':x='(iw-ow)/2':y='(ih-oh)/2',scale={w}:{h}` after the fit chain (constant `PUNCH_IN_END_SCALE = 1.06` mirrors effects.py).
- Gate stays OFF for these effects in this task (`can_render_with_ffmpeg` unchanged).

- [ ] Failing tests: argv for a freeze shot contains tpad+trim chain and reads a short input window; punch_in shot chain contains the dynamic crop+scale; a plain shot's chain is unchanged.
- [ ] Implement. Full render suite green. Commit `feat(render): native ffmpeg freeze + punch_in chains`.

### Task 3: flash transition as stepped eq bloom

**Files:**
- Modify: `api/prototyping/edit/render/ffmpeg_filtergraph.py`
- Test: `api/prototyping/edit/render/test_ffmpeg_filtergraph.py`

**Interfaces:**
- Produces: `_flash_steps(duration_sec) -> list[str]` — three `eq=brightness=...:enable='between(t,...)'` fragments approximating transitions.py's sine bloom (peak +0.09 luma at the middle third, half that on the outer thirds, default duration 0.12s); `_video_chain` appends them for `transition_in.type == "flash"` (shot-local time, pre-concat).

- [ ] Failing tests: flash shot chain contains three eq steps with the right windows/amplitudes; flash duration honors `transition_in.duration_sec`.
- [ ] Implement. Commit `feat(render): native ffmpeg flash bloom`.

### Task 4: skill fragments — vignette + drawtext, post-assembly hook

**Files:**
- Modify: `api/prototyping/edit/render/ffmpeg_filtergraph.py` (`build_command(..., font_path: str | None = None)`; after `_assemble_video`, wrap each overlay's `ffmpeg_filter` fragment as `{label}{frag}[ov{k}]`)
- Modify: `api/prototyping/edit/skills/text_common.py` (`drawtext_fragment(text, style, overlay, ctx) -> str` + `escape_drawtext_text`, `escape_drawtext_path` helpers)
- Modify: `api/prototyping/edit/skills/mask_vignette.py`, `text_hook.py`, `text_caption.py`, `text_lower_third.py` (each gains `ffmpeg_supported = True` + `ffmpeg_filter`)
- Modify: `api/prototyping/edit/render/ffmpeg_run.py` (pass-through `font_path`)
- Test: `api/prototyping/edit/render/test_ffmpeg_filtergraph.py`, `api/prototyping/edit/skills/test_skills.py`

**Interfaces:**
- Produces: vignette fragment `vignette=a={0.2 + 0.9*strength:.4f}:enable='between(t,{s:.3f},{e:.3f})'`; drawtext fragment with `fontfile=`, `fontsize=int(h*style.size_frac)`, white fill / black border (`borderw=max(1,int(fontsize*style.stroke_frac))`), position from `TextStyle` (center: `x=(w-text_w)/2`; left: `x={int(w*rel_x)}`; `y={int(h*rel_y)}`), and `enable='between(t,S,E)'`. `RenderContext` is reused as the ffmpeg context (font_path may be "" when no text overlays).
- Consumes: Task 1's `ffmpeg_filter` contract.

- [ ] Failing tests: escaping helpers (colon, quote, percent, backslash; Windows font path `C\:/...`); vignette fragment string; each text skill's fragment; build_command wires fragments after assembly and before the tail fade; overlays without font_path raise a clear error only when a text skill is present.
- [ ] Implement. Commit `feat(render): native ffmpeg overlay fragments (vignette + drawtext)`.

### Task 5: capability-driven dispatch + renderer wiring + docs

**Files:**
- Modify: `api/prototyping/edit/render/ffmpeg_filtergraph.py` (`can_render_with_ffmpeg` consults the registry: overlays need `skills.get(id).ffmpeg_supported`; `FFMPEG_TRANSITIONS = {cut, crossfade, whip, flash}`; `FFMPEG_EFFECTS = {freeze, punch_in}`)
- Modify: `api/prototyping/edit/render/renderer.py` (fast path passes `font_path=_resolve_font_path() if timeline.overlays else None`)
- Test: `api/prototyping/edit/render/test_ffmpeg_filtergraph.py`
- Docs: `CLAUDE.md`, `AGENTS.md` (fast path now covers flash/freeze/punch_in + all current overlays; MoviePy is legacy fallback)

- [ ] Failing tests: timeline with flash+freeze+vignette+text → `can_render_with_ffmpeg` True; unknown skill id → False; effect outside set → False.
- [ ] Implement, update docs, full `python -m pytest api -q` green. Commit `feat(render): polished reels stay on the native ffmpeg path`.

---

## Phase 3 — polish catalog

### Task 6: grade skills + finish_edit `grade` field

**Files:**
- Create: `api/prototyping/edit/skills/grade_presets.py` (three skills, `kind="grade"`, `ffmpeg_supported=True`, `params_model=EmptyParams`, `build_layers` returns `[]` with a log — grades are ffmpeg-native)
  - `grade.cinematic`: `eq=contrast=1.05:saturation=1.08,colorbalance=bs=0.06:rh=0.03:bh=-0.03`
  - `grade.vibrant`: `eq=contrast=1.04:saturation=1.22:brightness=0.01`
  - `grade.moody`: `eq=contrast=1.08:saturation=0.85:brightness=-0.02,colorbalance=bs=0.05:bm=0.02`
  (fragments carry `enable='between(t,S,E)'` like any overlay; the adapter gives grades the full reel window)
- Modify: `api/prototyping/edit/skills/__init__.py` (import line)
- Modify: `api/prototyping/edit/synthesis/agent.py` (TOOLS finish_edit gains optional `"grade"` string enum of grade ids; return dict gains `"grade"`; `_format_overlay_skills` groups catalog by kind and adds usage guidance)
- Modify: `api/prototyping/edit/synthesis/adapter.py` (`adapt(..., grade: str | None = None)` appends a full-reel `Overlay(skill_id=grade, params={})` when the id is a known grade; unknown → log + drop)
- Modify: `api/workflows.py` (pass `agent_output.get("grade")` into adapt)
- Tests: `api/prototyping/edit/skills/test_skills.py`, `synthesis/test_adapter.py`, `synthesis/test_agent.py`, `api/test_workflows.py`

- [ ] Failing tests: grade fragments; adapter maps grade → full-reel overlay (and drops unknown); agent returns grade; workflows threads it.
- [ ] Implement. Commit `feat(edit): agent-selectable color grade presets`.

### Task 7: impact.shake moment skill + adapter auto-accents

**Files:**
- Create: `api/prototyping/edit/skills/impact_shake.py` (`kind="moment"`, `ShakeParams.intensity` 0–1 default 0.5, fragment: `pad=w=iw+32:h=ih+32:x=16:y=16,crop=w=iw-32:h=ih-32:x='if(between(t,S,E),16+{A:.1f}*sin(t*73),16)':y='if(between(t,S,E),16+{B:.1f}*cos(t*61),16)'` with A=(4+10*intensity)*h/1080, B=0.8*A; `build_layers` returns `[]` with a log)
- Modify: `api/prototyping/edit/skills/__init__.py`
- Modify: `api/prototyping/edit/synthesis/rhythm.py` (`auto_accent_overlays(registrations, duration_sec, max_accents=2) -> list[dict]` — shake windows `[downbeat-0.05, downbeat+0.40]` for the strongest registrations)
- Modify: `api/prototyping/edit/synthesis/adapter.py` (after impact registration: if the agent placed no `moment` skills, extend overlays with auto accents)
- Tests: `skills/test_skills.py`, `synthesis/test_rhythm.py`, `synthesis/test_adapter.py`

- [ ] Failing tests: shake fragment math; auto_accent windows/clamping; adapter adds accents only when the agent placed none.
- [ ] Implement. Commit `feat(edit): impact.shake + deterministic downbeat accents`.

### Task 8: real speed_ramp (both paths + adapter source extension)

**Files:**
- Modify: `api/prototyping/edit/render/effects.py` (`SPEED_RAMP_END = 1.5`, `SPEED_RAMP_SOURCE_FACTOR = 1.25`, `apply_speed_ramp(clip, shot)` time-warp: `t < d/2 → t`, else `d/2 + (t-d/2)*1.5`)
- Modify: `api/prototyping/edit/render/renderer.py` (`_build_shot_clips` applies the ramp before `with_duration`)
- Modify: `api/prototyping/edit/render/ffmpeg_filtergraph.py` (ramp shot = two input windows `(start, d/2)` + `(start+d/2, d*0.75)`; second chain prepends `setpts=PTS/1.5`; both fitted then `concat=n=2` into `[v{i}]`; input indexing refactored to per-shot window lists; `FFMPEG_EFFECTS` gains `speed_ramp`)
- Modify: `api/prototyping/edit/synthesis/adapter.py` (`AGENT_EFFECTS` gains `speed_ramp`; a ramp shot's source window extends to `start + 1.25*dur` — bounds/uniqueness permitting, else the effect is dropped with a log)
- Modify: `api/prototyping/edit/synthesis/agent.py` (effect enum + description gains speed_ramp)
- Tests: `render/test_ffmpeg_filtergraph.py`, `render/test_effects_transitions.py`, `synthesis/test_adapter.py`
- Docs: `CLAUDE.md`, `AGENTS.md` (speed_ramp no longer a stub; whip remains a cut)

- [ ] Failing tests: warp math; argv two-window structure + audio input index shift; adapter extension + drop-on-bounds; validator passes (source ≥ duration is `>=`).
- [ ] Implement. Full suite green. Commit `feat(edit): real speed_ramp on both render paths`.

---

## Phase 4 — reference-derived style profiles

### Task 9: derive_style_profile

**Files:**
- Create: `api/prototyping/edit/synthesis/style_profile.py`
- Test: `api/prototyping/edit/synthesis/test_style_profile.py`

**Interfaces:**
- Produces: `derive_style_profile(metrics_list: list[dict]) -> dict` → `{"cut_lead_sec": float, "pacing_bands_beats": {label: (lo, hi)}, "reference_count": int}` (keys omitted when underived). Lead = clamp(−median(per-ref `cut_offsets_to_downbeats.median`), 0.0, 0.08). Bands: per-label median of `4.0 / cuts_per_downbeat` → `(max(1.0, 0.6·m), min(16.0, 1.4·m))`.

- [ ] Failing tests: lead from negative offsets; band derivation; empty/malformed metrics → `{}`/partial; clamping.
- [ ] Implement. Commit `feat(edit): style profiles derived from reference metrics`.

### Task 10: thread overrides through rhythm, adapter, agent

**Files:**
- Modify: `api/prototyping/edit/synthesis/rhythm.py` (`pacing_bands_for(tempo, overrides_beats=None)`)
- Modify: `api/prototyping/edit/synthesis/adapter.py` (`adapt(..., style_profile: dict | None = None)` → lead into `snap_shots_to_beats(lead_sec=...)` → `pick_snap_beat`; bands into split + report)
- Modify: `api/prototyping/edit/synthesis/agent.py` (`run_synthesis_loop(..., style_profile=None)` → `_format_pacing_context(song, style_profile)`)
- Tests: `test_rhythm.py`, `test_adapter.py`, `test_agent.py`

- [ ] Failing tests: overrides replace matching labels only; custom lead changes snap targets; profile-aware pacing block.
- [ ] Implement. Commit `feat(edit): rhythm engine accepts style-profile overrides`.

### Task 11: plan-time wiring + docs

**Files:**
- Modify: `api/workflows.py` (`_run_agent_timeline_plan`: completed references → `derive_style_profile` → pass to `_run_agent_synthesis` and `adapt`; profile summary into the sync-report payload + log)
- Test: `api/test_workflows.py`
- Docs: `CLAUDE.md`, `AGENTS.md`, spec update (Phase 4 wired; the old dead-code note about the weight loop is superseded)

- [ ] Failing test: a completed reference with metrics changes the profile passed to adapt (capture via monkeypatched adapt or the sync-report payload).
- [ ] Implement. Full suite green. Commit `feat(edit): reference-derived style profiles drive planning`.

---

## Verification (end of each phase)

1. `python -m pytest api -q` — all green.
2. Phase 2: extend the scratchpad `verify_rhythm.py`-style script — build a timeline with flash+freeze+punch_in+vignette+text, assert `can_render_with_ffmpeg` is True, and (ffmpeg present locally) run `render_with_ffmpeg` on tiny synthetic media to confirm the argv executes.
3. Phase 3: same script gains a grade + shake + speed_ramp; assert fragments present in argv and the MoviePy fallback ignores grades gracefully.
4. Phase 4: unit-level; plus one `run_timeline_plan` fake-runner test asserting the profile reaches adapt.
5. Remind user: redeploy `eclypte-render-r2` (Phases 2–3) — render package changed; no redeploy needed for Phase 4.
