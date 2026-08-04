# Reels reach recovery — design

Date: 2026-08-04
Status: research complete (13-agent deep-research pass, ~490 web lookups);
ready for implementation planning. Plans:
`docs/superpowers/plans/2026-08-04-reach-hygiene.md` (Phase A) and
`docs/superpowers/plans/2026-08-04-graph-publishing.md` (Phase B).

## Problem

The account posts 1–2 auto-created reels/day and gets extremely minimal views
(double/low-triple digits). Since Instagram's metric unification (Aug 2024), a
"view" counts at play start — so tiny view counts mean the reels are barely
being *served*, not merely failing retention. The product must stop tripping
distribution-level penalties before per-post quality optimization can matter.

## Research grounding (August 2026)

Ranked causes for near-zero serving, from the research pass:

1. **Originality/recommendation ineligibility.** Instagram escalated
   enforcement in three dated steps (Apr 30 2024 → Jul 14 2025 → a reported
   Apr 30 2026 expansion): accounts posting content "not created or enhanced
   in a material way" 10+ times in 30 days lose ALL recommendation surfaces
   (followers-only distribution — exactly the observed symptom). "Stitching
   clips together" is explicitly named as non-transformative; kinetic lyrics,
   grading, and rhythm editing are the transformative elements we can lean
   into. Originality enforcement is separate from copyright: posts staying up
   un-muted proves nothing.
2. **Rights Manager fingerprint matches** on the burned-in commercial song
   and/or the film footage. A "Block" outcome leaves the post visible only to
   the uploader. Burned-in audio does not evade audio fingerprinting.
3. **Stacked content-side demotions**, all official or strongly evidenced:
   reels "with a border around them" are on Instagram's official
   shown-less-often list (`reels_cinematic` gives a 2.39:1 film ~24% of the
   frame); the unconditional 2.5s fade-to-black kills the loop/replay signal
   (replays count as views); whole-film montages are off-convention for the
   niche (single-moment "aura" edits dominate); hashtag walls with `#fyp`
   conflict with Instagram's official ≤5-hashtag guidance (Dec 19, 2025).
4. **NOT causes**: Buffer/API posting itself (Mosseri, Mar 2025: no reach
   effect), posting cadence, ~25s length, AI-caption labeling.

Confirmed top ranking signals (Mosseri, Jan 2025): watch time (relative +
absolute), likes per reach, **sends per reach** (strongest for non-follower
reach). "Go to the audio page" is one of four officially documented top Reels
predictions — a surface burned-in audio can never win.

**Key API finding**: Meta shipped an Instagram Audio API (~Q2 2026): `GET
/ig_audio` (licensed/trending audio search) + `audio_configuration
{audio_id, ...}` on reel container creation, confirmed in Meta's official SDK
and implemented by Postiz/bundle.social. Buffer has not wired it — nor
`trial_params` (Trial Reels, ~1k-follower gate), `collaborators` (collab
posts), or `cover_url`. Full automation with licensed audio, custom covers,
and a pre-publish `copyright_check_status` canary requires publishing via the
Graph API directly — the same "route B: direct Meta" upgrade path already
earmarked in CLAUDE.md for metrics.

Caveat: the Apr 30 2026 enforcement expansion and some official-doc quotes
were triangulated from secondary sources/mirrors (proxy limits during
research); the Phase 0 checklist below is built from in-product signals so it
does not depend on them.

## Phase 0 — operator diagnosis (manual, before/alongside Phase A)

No code. Results steer priorities and are recorded in the plan's final task.

1. Instagram app → Settings → **Account Status**: recommendation eligibility
   and "content you can't recommend"; also check notifications for
   "Content you recently shared may not be original to you".
2. Per-reel insights: **follower vs non-follower view split**. ~0%
   non-follower across all reels ⇒ recommendation-ineligible; fix
   eligibility before optimizing anything else.
3. View several posted reels **logged out / from a second account** (Rights
   Manager Block is invisible to the uploader) and check each reel's audio
   attribution in-app (muted? generic "Original audio"?).
4. Confirm the professional account type is **Creator** (not Business —
   Business accounts get a restricted music library, which matters for
   Phase B audio).
5. The native-audio A/B: manually post one rendered reel in-app with the
   song attached from IG's library; compare its views to Buffer-published
   posts.

## Decisions

### Phase A — reach hygiene (no new integrations, control-plane only)

- **A1 — Fill-frame format.** Autopilot switches from `reels_cinematic` to
  `reels_9_16` (fill crop, center focus). Both formats stay available for
  manual composes. No A/B machinery: at 2 posts/day and double-digit views an
  A/B has no statistical power, and letterbox sits on an official demotion
  list — remove the confound. (Kinetic-lyrics layout already adapts to
  full-frame footage; the bars-preference simply stops applying.)
- **A2 — Loop-friendly ending.** Reels ≤40s (`SHORT_EDIT_MAX_SEC`) get a
  0.3s audio-only fade (click prevention) and **no video fade-to-black**;
  long-form (>40s, i.e. YouTube montages) keeps the 2.5s tail fade. Both
  render paths already guard `fade <= 0`, so this is an adapter/schema-helper
  change; timeline JSON rides existing fields.
- **A3 — Niche-register captions, ≤5 hashtags.** Caption = short human hook
  line (source/song names worked in naturally — they are the search
  keywords), a `anime: X · song: Y` credit line, optionally ONE genuine
  fandom question or a send-to-a-friend nudge (never both, never formulaic
  bait — "comment YES"-style lines are officially demotable). Hashtags: 3–5,
  all specific to the reel (source, song/artist, fandom tag, #animeedit/#amv);
  `#fyp` and generic discovery tags are banned. Fallback template loses
  "fr 🔥". Filename junk (`1080p`, `x265`, release-group brackets…) is
  stripped from source/song names before they reach captions or hashtags.
- **A4 — Chorus lead-in 5s → 1.5s.** The reel's audio currently opens on 5s
  of pre-chorus build — the exact stay-or-scroll window. Keep a small lead so
  the drop still lands after the hook shot registers.
- **A5 — Overlap dedupe.** The 5s start-bucket lets two windows sharing ~80%
  of audio/footage count as different combos. Add a window-overlap check
  (reject a candidate overlapping any used window of the pair by >40%,
  measured against the shorter window) alongside the bucket key; recycling
  clears both. Near-duplicate posts are now an enforcement risk, not just
  waste.
- **A6 — Moment-focused edits.** New `edit_focus: "full_source" | "moment"`
  threaded request → run inputs → agent. `moment` swaps the injected
  span-the-full-source block for a focused-moment block (one scene/character
  arc, dwell, hook-first, head/tail hazards preserved) that explicitly
  overrides the span rule (so stale stored prompt versions can't fight it).
  Autopilot always sends `moment`; manual composes default `full_source`.
  The baseline system prompt's span bullet gains an "unless the run context
  declares a focused moment edit" escape.
- **A7 — First-shot hook telemetry.** The adapter records
  `first_shot {source_start_sec, duration_sec, impact_backed}` in the
  `timeline_sync_report` so weak openings are visible per run. No hard
  enforcement yet (relocating the opener could break musicality; revisit
  with data).
- **Deliberately unchanged**: kinetic lyrics stay default-on (differentiation
  plus a visible transformation signal for the originality classifier —
  a knowing divergence from the niche's minimal-text convention); posting
  cadence; reel length; Buffer as the Phase-A publisher; no
  detector-evasion features (ineffective and policy-branded as proof of
  unoriginality); no deleting of underperforming posts.

### Phase B — direct Graph API publishing (probe-gated)

Replace the Buffer send step with a first-party Graph API publisher behind
`ECLYPTE_PUBLISH_PROVIDER` (default `buffer`; `graph` opt-in per deploy).
Unlocks, in value order:

1. **Attached licensed audio** via `audio_configuration` (+ `GET /ig_audio`
   search) — audio-page discovery + Meta-licensed music instead of raw
   fingerprint exposure. **Open question the Task-0 probe must answer**:
   whether an offset/start-time is supported so the attached track can stay
   sample-synced with a beat-cut edit. If not, ship Phase B with burned-in
   audio retained (everything else still pays) and revisit.
2. **`copyright_check_status` canary** pre/post publish, surfaced on the post
   record — automated detection of MUTE/BLOCK outcomes.
3. **`cover_url`** — ship the poster frame the pipeline already computes;
   today no cover is sent at all and IG picks the (often black) first frame
   for the 3:4 profile grid.
4. **Graph insights metrics** for graph-published posts (Buffer can't see
   them), folded through the existing source-agnostic `apply_post_metrics`.
5. Scheduling moves in-house for the graph provider (Graph publish is
   immediate): the auto-send pass becomes slot-based
   (`86400 / daily_target` spacing), reusing existing budget caps.
6. Future (not in Phase B): `trial_params` at 1k followers, `collaborators`.

Operator prerequisite: Meta app + Facebook-Login-connected IG professional
account + long-lived token (60-day; refresh procedure documented in
`api/COMMANDS.md`).

## Non-goals

- No TikTok/YouTube cross-posting automation (separate copyright strategy per
  platform; YouTube carries channel-termination strike risk from anime
  rights holders — burner-channel decision is the operator's).
- No Trial Reels / collab automation yet (follower-gated / manual-accept).
- No adaptive steering from `performance_score` (still Phase 2 of the
  performance feedback loop).
- No engagement automation (comments/DMs from the account stay human).
- No changes to the review gate: auto-created posts still wait for human
  approval unless `auto_publish` is on.
