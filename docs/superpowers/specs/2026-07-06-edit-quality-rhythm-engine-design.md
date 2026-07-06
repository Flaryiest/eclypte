# Edit-quality push — design (Phase 1: the rhythm engine)

Brainstormed 2026-07-06. Goal: push Eclypte's reel quality as high as possible.

## User decisions

- **Pain points:** rhythm/sync feel (cuts land on beats but don't *feel* musical) and visual
  polish (raw cuts look plain). Shot selection and run-to-run consistency are not the priority.
- **"Skills" means the edit skills registry** (`api/prototyping/edit/skills/`) — expand that
  system — plus whatever supporting mechanisms serve quality.
- **Approach: deterministic core + agent creativity.** A rhythm engine in the adapter guarantees
  musicality every run; the agent keeps creative freedom on top of that floor.
- **Render path: port polish to ffmpeg.** New polish features must land in the native
  filtergraph so reels keep rendering in seconds; MoviePy stays the exotic-case fallback.
- **Scope: Phase 1 only** (the rhythm engine), with 2–4 as the approved roadmap.

## Roadmap

1. **Rhythm engine** (implemented 2026-07-06) — pure module
   `api/prototyping/edit/synthesis/rhythm.py` + adapter/agent/workflows wiring:
   - Downbeat-preferred beat snapping with a `CUT_LEAD_SEC = 0.04s` early-cut lead (human
     editors cut ~1 frame before the beat; the ingested reference reel shows a negative-median
     cut offset).
   - Impact→downbeat registration: shift a shot's source window (≤0.75s) so its strongest
     video-analysis impact frame lands on a musical downbeat. Timeline positions never move,
     so boundaries stay beat-snapped.
   - Tempo-scaled per-section pacing bands (chorus/drop 2–4 beats per shot, verse/bridge 4–8):
     given to the agent as per-run guidance, enforced as a deterministic backstop that splits
     a fast-section shot overrunning its band 2× at downbeats (later pieces jump their source
     window so splits read as real cuts).
   - `query_clips` results enriched with scene `motion`/`camera`/`impact_near` metadata
     (`_enrich_clip_results`, control-plane side — no Modal redeploy).
   - `sync_report` telemetry persisted as a `timeline_sync_report` run event (on-beat %,
     on-downbeat %, impact registrations, pacing splits, per-section duration conformity).
   - Stays entirely on the fast native ffmpeg render path.
2. **ffmpeg polish foundation** (implemented 2026-07-06) — skills registry generalized to kinds
   (`overlay` / `grade` / `moment`) with per-skill `ffmpeg_supported` + `ffmpeg_filter`
   fragments; flash (stepped eq bloom), freeze (1-frame + tpad clone), punch_in (zoompan),
   vignette, and drawtext (double-escaped) ported to `render/ffmpeg_filtergraph.py`;
   `can_render_with_ffmpeg` is capability-driven; every chain normalizes `settb=AVTB` so
   xfade accepts mixed effect chains. Requires an `eclypte-render-r2` redeploy.
3. **Polish catalog** (implemented 2026-07-06) — `grade.cinematic`/`vibrant`/`moody` presets
   (finish_edit's optional `grade` field → full-reel overlay under the others), `impact.shake`
   moment skill + adapter auto-accents on the strongest impact registrations, and a real
   `speed_ramp` (1x → 1.5x into the next cut; adapter extends the source window to 1.25×,
   beat-snap and impact registration skip ramp shots).
4. **Reference-derived style profiles** (implemented 2026-07-06) —
   `synthesis/style_profile.py::derive_style_profile` turns completed reference metrics into
   `cut_lead_sec` + per-section pacing-band overrides, computed fresh at plan time and threaded
   into the agent's pacing context, `adapt`, and the `timeline_sync_report` payload.

## Phase 1 design notes

- `rhythm.py` follows the repo's pure-decision pattern (`credits.py`, `poster.py`): no Modal,
  moviepy, or numpy imports; fully unit-tested (`test_rhythm.py`).
- Adapter pipeline order: build → dedupe → contiguous re-time → song-trim →
  `split_overlong_section_shots` → `snap_shots_to_beats` (downbeat-preferred + lead) →
  `register_impacts_to_downbeats` → Timeline → validate. Splits happen before snapping (their
  cuts land on downbeats by construction); registration runs last because it only moves source
  windows.
- Telemetry travels via `adapt(..., report_sink=)` — a side-channel dict, never part of the
  timeline render contract. `markers.beats_used_sec` records musical anchors, not the
  lead-adjusted boundary positions.
- Guardrails: every rhythm feature no-ops gracefully when its data is missing (older analyses
  without impacts/downbeats), and all source-window moves respect bounds and the 1.0s
  source-start uniqueness rule.

Implementation plan and verification live in the session plan file; behavior documentation in
`CLAUDE.md` (edit pipeline + current focus) and `AGENTS.md`.
