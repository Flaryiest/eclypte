# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Eclypte is an AMV (Anime Music Video) creator. Monorepo layout:

- **`web/`** — Next.js 16 frontend (React 19, TypeScript, App Router)
- **`api/`** — Python backend (scaffold; `main.py` currently empty)

## Development Commands

All web commands run from the `web/` directory:

```bash
cd web
npm run dev      # Next.js dev server
npm run build    # Production build
npm run start    # Production server
npm run lint     # ESLint (flat config: core-web-vitals + typescript)
```

No test runner is configured yet.

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
