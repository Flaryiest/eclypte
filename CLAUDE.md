# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Eclypte is an AMV (Anime Music Video) creator application with a monorepo structure:

- **`web/`** — Next.js 16 frontend (React 19, TypeScript)
- **`api/`** — Python backend (currently empty scaffold)

## Development Commands

All web commands run from the `web/` directory:

```bash
cd web
npm run dev      # Start Next.js dev server
npm run build    # Production build
npm run start    # Start production server
npm run lint     # Run ESLint (flat config with core-web-vitals + typescript)
```

## Architecture

- **Next.js 16 with App Router** — pages live in `web/src/app/`. Uses the `@/*` path alias mapping to `web/src/`.
- **Fonts**: Inter and Inter Tight loaded via `next/font/google`, exposed as CSS variables `--font-inter` and `--font-inter-tight`.
- **Next.js 16 breaking changes**: This project uses Next.js 16 which has API differences from earlier versions. Read `node_modules/next/dist/docs/` before making assumptions about Next.js APIs or conventions.
