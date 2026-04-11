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

- **App Router** — pages live in [web/src/app/](web/src/app/). The `@/*` path alias maps to `web/src/`.
- **Components** — shared UI lives in [web/src/components/](web/src/components/) (e.g. `navbar`).
- **Fonts** — Inter and Inter Tight are loaded via `next/font/google` in [web/src/app/layout.tsx](web/src/app/layout.tsx) and exposed as CSS variables `--font-inter` and `--font-inter-tight`. The bootstrapped `web/README.md`'s mention of Geist is stale — ignore it.
