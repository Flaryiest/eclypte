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
2. **ffmpeg polish foundation** — generalize the skills registry beyond overlays (kinds:
   `overlay` / `grade` / `moment`), port flash/freeze/punch_in/vignette/grain/grade/drawtext to
   `render/ffmpeg_filtergraph.py`, make `can_render_with_ffmpeg` registry-driven. Redeploy
   `eclypte-render-r2`.
3. **Polish catalog** — `grade.*` presets (agent picks one per reel by mood), `impact.shake`,
   upgraded punch, real `motion.speed_ramp` into downbeats; moment effects ride the existing
   overlays channel (window + skill_id); optional deterministic auto-placement at
   impact+downbeat coincidences.
4. **Reference-derived style profiles** — wire the (currently dead) reference metrics/weight
   loop into the rhythm engine's constants.

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
