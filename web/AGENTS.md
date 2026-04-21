<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Current Frontend Shape

- App Router lives in `src/app/`.
- `src/app/page.tsx` is the main marketing landing page and composes most shared homepage components.
- `src/app/pricing/page.tsx` and `src/app/dashboard/page.tsx` are present but still lightweight placeholders.
- `src/proxy.ts` contains the Clerk middleware matcher for app and API routes.
- `src/components/login/login.tsx` renders the Clerk `SignIn` modal; `src/components/navbar/navbar.tsx` controls opening it.
- Fonts are configured in `src/app/layout.tsx` with both Google fonts and local font assets from `public/fonts/`.

## Working Assumptions

- Preserve the existing visual language on the landing page rather than replacing it with generic boilerplate.
- Check whether a route is still placeholder-level before doing large refactors; some pages are intentionally skeletal right now.
