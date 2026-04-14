# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Eclypte is an AMV (Anime Music Video) creator. Monorepo layout:

- **`web/`** — Next.js 16 frontend (React 19, TypeScript, App Router)
- **`api/`** — Python backend. `api/main.py` is still an empty FastAPI stub; real work lives in `api/prototyping/` (see Audio Pipeline below).

## Development Commands

Web (run from `web/`):

```bash
cd web
npm run dev      # Next.js dev server
npm run build    # Production build
npm run start    # Production server
npm run lint     # ESLint (flat config: core-web-vitals + typescript)
```

API (run from `api/`):

```bash
pip install -r requirements.txt   # first allin1 run downloads ~400MB of model weights
cd prototyping
python main.py                     # end-to-end: download → analyze → lyrics
python analysis.py                 # analyze ./content/output.wav standalone
```

No test runner is configured yet.

## Audio Pipeline (`api/prototyping/`)

MVP audio analysis lives in the prototyping sandbox. Scripts are wired together by [api/prototyping/main.py](api/prototyping/main.py):

- **[ytdownload.py](api/prototyping/ytdownload.py)** — `main(video_url) -> title`. Downloads YouTube audio via `pytubefix` to `content/output.m4a`, transcodes to `content/output.wav` via `pydub`. The URL is currently a module-level `url` constant.
- **[analysis.py](api/prototyping/analysis.py)** — `analyze(audio_path, out_path=None) -> dict`. Produces the "song map" JSON (`schema_version: 1`) with tempo, beats, downbeats, a 10Hz normalized energy curve, and structural segments. Uses `allin1` (PyTorch model) as the single source of truth for beats/downbeats/segments; `librosa` only for audio loading and RMS. All timestamps use the `_sec` suffix — no frame indices escape the module.
- **[lyrics.py](api/prototyping/lyrics.py)** — `main(query)`. Uses `syncedlyrics` to fetch an LRC, writes `content/lyrics.txt`. Intentionally separate from `song_analysis.json` (different source, optional).

Song-map consumers read `content/output.json`. Schema details and design decisions are in the approved plan at `.claude/plans/glistening-enchanting-bumblebee.md` (if present) — timestamps are seconds, `downbeats_sec` is a subset of `beats_sec`, `segments.label` passes through allin1's vocabulary unchanged.

Deferred to v2 (bump `schema_version` when adding): onsets, per-band energy (low/mid/high), key & mode.

## Next.js 16 — READ BEFORE WRITING CODE

This project uses **Next.js 16.2.3** with **React 19.2**. These versions postdate common training data and have breaking API/convention changes from Next.js 13–15. Do not assume APIs from memory.

Before writing or modifying anything touching Next.js (routing, data fetching, `headers()`/`cookies()`/`params`, caching, config, metadata, middleware, server actions, etc.), consult `web/node_modules/next/dist/docs/` and heed any deprecation notices you find there. See also [web/AGENTS.md](web/AGENTS.md).

## Architecture Notes

- **App Router** — pages live in `web/src/app/`. Components use CSS Modules (`.module.css` co-located with each component).
- **Path aliases** — `@/*` maps to `web/src/*` and `@components/*` maps to `web/src/components/*` (configured in `web/tsconfig.json`).
- **Components** — shared UI lives in `web/src/components/` (e.g. `navbar/`, `hero/`). Each component is a directory with a `.tsx` file and a co-located `.module.css` file.
- **Page layout** — the root layout (`layout.tsx`) provides fonts and the `ThemeProvider` but no shared navigation. Each page imports `<Navbar />` individually — there is no global layout-level nav.
- **Theming** — `next-themes` with `attribute="data-theme"` on `<ThemeProvider>`. Default theme is dark. CSS variables defined in `:root` and overridden via `[data-theme="dark"]` in `globals.css`:
  - `--color-background`, `--color-primary`, `--color-secondary`, `--color-subtitle`, `--color-highlight` (gold accent, #e8a838)
- **Fonts** — loaded in `web/src/app/layout.tsx` and applied to `<body>` as CSS variable classes:
  - Google fonts: `--font-inter`, `--font-inter-tight`, `--font-outfit`
  - Local fonts (from `web/public/fonts/`): `--font-neue` (PP Neue Montreal), `--font-eiko` (PP Eiko)
  - The bootstrapped `web/README.md`'s mention of Geist is stale — ignore it.
- **Global styles** — `web/src/app/globals.css` includes a CSS reset, theme variables, and base element styles. A `.page` utility class provides a centered full-width page wrapper. Do not use `#root` selectors — Next.js has no `#root` element.
- **Images** — uses native `<picture>`/`<source>` elements, not `next/image`. This is intentional; do not migrate to `<Image>`.
- **Static assets** — images live in `web/public/assets/` (e.g. `hero/` subdirectory).
- **Z-index hierarchy** — navbar sits at 50000, hero layers at 1–10000, page content at default. New components should respect this stacking order.
- **Responsive breakpoint** — 768px (`max-width`) is the standard mobile breakpoint used throughout the CSS Modules.
- **Reduced motion** — animations respect `@media (prefers-reduced-motion: reduce)`. New animations must do the same.
