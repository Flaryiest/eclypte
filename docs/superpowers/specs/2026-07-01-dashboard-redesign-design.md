# Eclypte Dashboard Redesign — "Ivory & Ink"

Status: approved 2026-07-01 (brainstormed interactively with visual-companion mockups; each section user-approved).

## Context

The current dark "Edit Bay" dashboard reads as a generic AI-generated dashboard: 20+ CSS classes of tiny tracked-out uppercase labels, fractal-noise background, purple energy gradient, letter-labeled nav (A–G), giant thin display titles. Info density is inverted (file extensions and byte sizes everywhere; no thumbnails, durations, or real progress), async actions are bare text-swaps (zero spinners in the app), and the IA doesn't match usage — Compose (A) and Style (E) are barely used while Autopilot does all the editing.

Approved decisions:

- **Direction:** warm minimal consumer (light), Things/Family lineage
- **IA:** 3 destinations — Home (pipeline), Library, Settings
- **Home layout:** "Today feed" — one vertical feed ordered by what needs the user
- **Visual language:** "Ivory & Ink" — PP Neue Montreal (already owned/loaded), warm ivory surfaces, ink buttons, single coral accent
- **Scope:** includes one backend addition — real source-video thumbnails

Approved mockups (local, gitignored): `.superpowers/brainstorm/1592-1782947788/content/` — `home-design.html`, `library-design.html`, `system-design.html`. Use them as the visual reference during implementation.

## Design

### Design system (tokens replace the Edit Bay block in `web/src/app/globals.css`)

- Surfaces: app `#F7F5F1` ivory, cards/sheets `#FFFFFF`, sunk fills `#F1EDE4`, borders `#E9E4DB` (strong `#D8D1C4`), overlay `rgba(38,35,30,0.28)`
- Ink: text `#26231E`, body-secondary `#3D3A34`, muted `#8A8375`, faint `#B3AC9C`
- Accent: coral `#E86A4F` (progress + attention ONLY); success sage `#5E8A62`; danger clay `#C25243`
- Radius 12px (cards/sheets), 10px (buttons), 99px (pills); shadows `0 1px 3px rgba(50,42,28,0.05)` (sheets heavier)
- Type: PP Neue Montreal only (drop Space Grotesk + JetBrains Mono from the dashboard; marketing untouched). Scale: 30/500 page titles (-0.015em), 18/500 sheet titles, 15/500 sections, 14 body, 12.5 meta floor. **Sentence case everywhere; uppercase + positive letter-spacing banned.**
- Kill list: fractal noise bg, `--energy` gradient, eyebrows, uppercase badge boxes, letter nav, italic-serif empty states, page-enter animations, 3px radius
- Marketing site (`:root`/`[data-theme]`) untouched; only `[data-surface="studio"]` tokens are replaced (keep the same data-surface gate)

### Feedback rules (every async action, no exceptions)

1. **Instant** (remove, pause, target change): optimistic cache update; toast only on failure (revert)
2. **Short** (rewrite caption, post, run tick): button keeps label + inline spinner; never bare disable/text-swap
3. **Long** (uploads, imports, analysis, edits): card with progress bar + human stage sentence + real number (bytes for uploads, % + ETA for renders via run stream + existing stage weights)
- Confirmations: small dark toasts ("✓ Posted to Instagram"), not layout-shifting banners. Skeletons remain for initial loads only.

### Shell

Top bar replaces sidebar: wordmark left, Home / Library links, Settings + avatar right. No hamburger (2 links). Retire `web/src/components/dashboard/sidebar/`. Routes: `/dashboard` = Home feed (no longer a redirect); `/dashboard/autopilot` + `/dashboard/publish` redirect to `/dashboard`; `/dashboard/renders` redirects to Library Reels tab; `/dashboard/new-edit` + `/dashboard/synthesis` stay routable but unlisted.

### Home (replaces Autopilot + Publish pages)

- Header: "Today" + status line as the autopilot control (dot, "Autopilot is on · 2 of 3 reels made today", daily-goal select, on/off switch, "+ New reel"). Halt state = calm banner "Autopilot paused after 3 failed tries — Resume"
- Sections in order: **Ready for you** (review cards: render poster, "Film × Song" name, age, 2-line caption preview, ink "Review & post") → **In the works** (spinner + stage sentence + progress bar + ETA per running item) → **Up next** (queue rows with source thumbs, quiet remove) → **Posted** (poster strip, "Tue · on Instagram"/"scheduled", "See all" → Library Reels)
- **Review sheet** (right slide-over desktop / bottom sheet mobile): tap-to-play vertical preview, editable caption + "↺ Rewrite", hashtags, actions Post now / Schedule / Add to queue / Skip. Footer: "25 seconds · posts to Instagram as a Reel" — Buffer never named in UI
- **Composer sheet** ("+ New reel"): pick video (thumbnails), pick song or YouTube URL, optional creative note → lands in Up next
- Data: existing `useAutopilot`, `usePublishingPosts`, `useEditJobs`/`useRuns`, `useRunStream` — no store changes. **Preserve critical behaviors:** publish ~25s Buffer reconciliation poll + tab-refocus refresh, manual refresh surfacing Buffer errors, mark-as-posted override (in sheet overflow), caption dirty-guard (`syncedPostIdRef` pattern), autopilot manual tick when loop unconfigured

### Library (rebuilt assets page, absorbs Renders)

- Tabs: **Films / Songs / Reels** + quiet "Hidden" link (archived). The "Derived" tab dies — analysis artifacts never shown; analysis is a status on the card ("● Ready to use" / spinner + "Getting to know this film…")
- Films: 16:9 thumbnail grid (real `source_poster` frames; warm gradient placeholder until analyzed), extension-stripped titles, duration
- Songs: rows with ♪ tile, play preview, duration, status; YouTube import shows as an in-list row with live progress
- Reels: 9:16 poster grid, "Film × Song", posted/scheduled state, download
- "+ Add" sheet: smart drop zone (MP4 → film, audio → song with existing auto-convert chain) + YouTube URL field. Uploads render as in-grid cards with **real byte progress**, then conversion/analysis stages continue on the same card; inline failure + retry
- Detail sheet on click: preview, duration + file size (sizes appear here ONLY), analyze/download/hide actions

### Backend: source-video thumbnails

- New artifact kind `source_poster` in `api/storage/models.py` (mirror `render_poster`); hidden from default asset lists like render posters (`api/app.py`)
- Modal video-analysis worker (`api/prototyping/video/analysis_cuda.py` via `storage_modal.py`) picks one representative frame (bright + detailed, ~20% in — reuse brightness/detail heuristics so never black/credits) and returns JPEG bytes; `run_video_analysis` in `api/workflows.py` publishes it, adds `source_poster_file_id`/`_version_id` to run outputs (additive — existing output keys unchanged)
- `GET /v1/assets` response gains an optional poster ref per asset (resolved server-side) so Library/Home render thumbnails without N+1 requests; type added to `web/src/services/eclypteApi.ts`
- Requires `eclypte-video-r2` redeploy (PYTHONUTF8=1 on Windows); old films get posters on next analysis

## Implementation order

1. **Baseline commit** of the pre-redesign WIP (done: `902ea44`)
2. **Backend** `source_poster` end-to-end (models → workflow → assets response → tests) — independently deployable; note Modal redeploy
3. **Tokens + primitives**: rewrite `[data-surface="studio"]` block in `globals.css`; rewrite `web/src/app/dashboard/studio.module.css` to the new system; add `Spinner`, `Toast`, `ProgressRow`, `Sheet`, `StatusDot` to `dashboardCommon.tsx` (keep `statusLabel`, `humanizeStageDetail`, `formatClock`, `usePagination`, `errorMessage`; retire `StatusBadge` badge-box styling); restyle `Select.tsx` (keep its a11y logic); trim font pipeline in `web/src/app/layout.tsx`
4. **Shell**: top bar in `web/src/app/dashboard/layout.tsx` + `layout.module.css`; retire sidebar component; add redirects
5. **Home**: build feed + review sheet + composer sheet at `web/src/app/dashboard/page.tsx`
6. **Library**: rebuild `web/src/app/dashboard/assets/page.tsx`; switch `uploadAsset` in `eclypteApi.ts` from fetch to XHR for byte progress
7. **Settings** light rework; verify new-edit/synthesis still render acceptably with new tokens
8. **Cleanup + docs**: delete dead CSS/components; reconcile `CLAUDE.md`, `AGENTS.md`, `web/AGENTS.md`; update the dashboard-identity memory file

## Verification

- Backend: `python -m pytest api/storage api/test_api_v1.py api/test_workflows.py -v`, then full `python -m pytest api -v`
- Frontend: `npm run lint` + `npm run build` from `web/`
- Manual: upload a video → byte progress visible; queue an autopilot pairing → watch it move Ready-for-you → review sheet → schedule (don't live-post during QA unless intended); redirects from old routes; empty states; mobile viewport (bar + bottom sheets); `prefers-reduced-motion` honored; hidden pages (new-edit/synthesis) still usable
- Contract checks: `RunManifest.outputs` existing keys unchanged; default asset list excludes `source_poster`; marketing pages pixel-identical

## Non-goals

Marketing site, compose/synthesis rebuilds, YouTube publishing, asset renaming, song artwork, multi-part >5 GiB uploads.
