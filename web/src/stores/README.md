# Dashboard resource cache (`web/src/stores/`)

A small [zustand](https://github.com/pmndrs/zustand) **stale-while-revalidate** cache shared
across every dashboard page. It exists to fix two problems the old per-page `useAbortableLoad`
pattern had:

1. **Re-query on every navigation.** `useAbortableLoad` is no-cache, so each route mount re-fetched
   cold and discarded the data on unmount — every page switch paid full backend latency again.
2. **No cross-page sharing.** The assets library was fetched separately by `/assets`, `/new-edit`,
   and `/autopilot`.

With the cache, the **second** visit to a page paints instantly from cache and revalidates in the
background, and pages that request the same data share a single fetch.

> This cache holds **structural records only** (`AssetSummary`, `RunSummary`, `PublishingPost`, …).
> It must **never** cache signed download/preview URLs — those come from separate `getDownloadUrl`
> calls and expire.

## Files

| File | Responsibility |
|------|----------------|
| `dashboardStore.ts` | The zustand store: a `Record<key, ResourceEntry>` cache plus three actions (`ensureFresh`, `revalidate`, `patch`). Framework-agnostic; knows nothing about specific resources. |
| `useResource.ts` | The generic React hook. Subscribes a component to one cache entry and triggers stale-while-revalidate on mount. Returns `{ data, status, error, isLoading, isValidating, revalidate, set }`. |
| `dashboardResources.ts` | Typed, user-scoped wrappers — `useAssets`, `useEditJobs`, `usePublishingPosts`, `useSynthesisReferences`, `useSynthesisPrompt`, `useAutopilot`. Each builds a cache key and delegates to `useResource`. **This is the layer pages import.** |

## How it works

### Cache entry

```ts
type ResourceEntry<T> = {
    data: T | undefined
    status: "idle" | "loading" | "success" | "error"
    error: string | null
    lastFetchedMs: number
    inFlight: Promise<void> | null   // dedup handle
    controller: AbortController | null // latest-wins handle
}
```

Entries are replaced immutably on every write (`withEntry`), so a zustand selector reading
`state.entries[key]` only re-renders the components subscribed to **that** key — a write to another
key leaves this key's object reference untouched.

### Stale-while-revalidate

`useResource` calls `ensureFresh(key, fetcher, ttlMs)` in a mount effect:

- **Dedup** — if an `inFlight` promise exists for the key, do nothing.
- **Freshness** — if the entry is `success` and younger than `ttlMs` (default **30 s**), serve cache
  and skip the network.
- Otherwise `revalidate` runs the fetcher in the background. `data` from the previous fetch stays
  visible while the new one is in flight (`isValidating === true`).

### Latest-wins

`revalidate` aborts the previous fetch's `AbortController` before starting a new one, and a resolved
fetch is dropped if `entries[key].controller` no longer points at its own controller. So a slow
earlier response can never overwrite a newer one.

### Errors

A failed (non-abort) fetch sets `status: "error"` and `error`, but **keeps the stale `data`** so the
UI doesn't blank out. Pages surface it via `error ?? loadError`.

### Mutations (`set`)

`set(value)` or `set(prev => next)` patches the cached collection in place (mirrors React's
`setState`), and bumps `lastFetchedMs` so an in-flight background revalidate won't immediately
clobber the optimistic edit. Use it for archive/restore/delete/cancel/etc. instead of re-pulling the
whole list.

## Using it in a page

```tsx
const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])

// Read-only list:
const { data: jobs = [], error: loadError, isLoading } = useEditJobs(api)

// List you also mutate:
const assetsResource = useAssets(api, { includeArchived: true })
const assets = assetsResource.data ?? []
const setAssets = assetsResource.set       // setAssets(prev => …) in delete/archive handlers
const refresh = assetsResource.revalidate  // pass to useRunStream / a Refresh button
```

## Adding a new cached resource

1. Add a client method on `EclypteApiClient` (`web/src/services/eclypteApi.ts`) if one doesn't exist.
2. Add a typed wrapper in `dashboardResources.ts`:
   ```ts
   export function useThing(api: EclypteApiClient | null, opts: {…} = {}): UseResourceResult<Thing[]> {
       const key = api ? `thing:${api.userId}:${serializeOpts(opts)}` : null
       return useResource<Thing[]>(key, (signal) => api!.listThings(opts, signal), { enabled: api !== null })
   }
   ```
   The key **must** include `api.userId` (per-user scoping) and any params that change the result.
3. Use it in the page, replacing `useState + useAbortableLoad + useEffect`.

## Gotchas (read before editing a migrated page)

- **The resource object is recreated every render.** Its `data`/`error` are stable when unchanged,
  but the wrapper object is new each render. So when you put `revalidate`/`set` into a `useCallback`
  or `useEffect` dependency array, **extract the stable member first** — depending on the object
  re-subscribes/re-runs every render:
  ```ts
  const revalidate = resource.revalidate           // stable
  const reload = useCallback(() => revalidate(), [revalidate])  // ✅
  // useCallback(() => resource.revalidate(), [resource])       // ❌ churns
  ```
- **Memoize `data ?? []` when it feeds a `useEffect` dependency.** `?? []` makes a fresh array each
  render; wrap it in `useMemo(() => data ?? [], [data])` (see `new-edit`'s `jobs`, the Library's
  `reels`, Home's `posts`). Where the list is only read in render, plain `data ?? []` is fine.
- **No abort on unmount (intentional).** A fetch is allowed to finish after the component unmounts
  and populate the shared cache — that's the whole point. Correctness comes from latest-wins + dedup,
  and writing to an external store after unmount is safe (no React state-on-unmounted warning).
- **User-owned inputs need a dirty-guard.** When a textarea/field is seeded from cached data and the
  user can edit it, a background revalidate must not clobber unsaved edits. `synthesis` seeds the
  prompt textarea only when it still equals the last value we wrote (`lastSeededRef`).
- **Don't re-seed editors on every poll.** The Home feed polls Buffer every ~25 s and patches
  `posts`; it guards the caption editor and `<video>` with `syncedPostIdRef`/`previewKeyRef` so a
  replaced post object (same `post_id`) doesn't reset them.

## Page → resource map

| Page | Resources |
|------|-----------|
| `/dashboard` (Home) | `useAutopilot`, `usePublishingPosts({ status: "all" })`, `useEditJobs`, `useAssets({ includeArchived: true })` (videos/songs filtered client-side — shares the library cache) |
| `/assets` (Library) | `useAssets({ includeArchived: true })`, `useAssets({ kind: "render_output" })` (Reels tab), `usePublishingPosts({ status: "all" })` |
| `/new-edit` | `useAssets({ includeArchived: true })`, `useEditJobs` |
| `/synthesis` | `useSynthesisReferences`, `useSynthesisPrompt` |
| `/settings` | not migrated — still uses `useAbortableLoad` directly |
| `/autopilot`, `/publish`, `/renders` | redirect stubs — no resources of their own |

## Deferred

`persist` (localStorage, keyed by `user.id`) for instant paint across **hard refreshes** was
considered and intentionally left out.
