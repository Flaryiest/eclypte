import { useCallback, useEffect, useRef } from "react"
import { useDashboardStore, type ResourceStatus } from "./dashboardStore"

const DEFAULT_TTL_MS = 30_000

export type ResourceFetcherFn<T> = (signal: AbortSignal) => Promise<T>
export type ResourceSetter<T> = (updater: T | ((prev: T | undefined) => T)) => void

export type UseResourceResult<T> = {
    data: T | undefined
    status: ResourceStatus
    error: string | null
    isLoading: boolean
    isValidating: boolean
    revalidate: () => void
    set: ResourceSetter<T>
}

// Subscribe a component to one cache entry, fetching on mount via stale-while-
// revalidate. `key === null` (e.g. no signed-in user yet) keeps the resource idle.
// `set` mirrors React's setState ergonomics (value or updater) for in-place cache
// mutations. We intentionally do NOT abort the fetch on unmount: letting it finish
// and populate the shared cache is the whole point; latest-wins + dedup keep it
// correct, and writing to an external store after unmount is safe.
export function useResource<T>(
    key: string | null,
    fetcher: ResourceFetcherFn<T>,
    options: { enabled?: boolean; ttlMs?: number } = {},
): UseResourceResult<T> {
    const { enabled = true, ttlMs = DEFAULT_TTL_MS } = options

    const fetcherRef = useRef(fetcher)
    useEffect(() => {
        fetcherRef.current = fetcher
    })

    const entry = useDashboardStore((state) => (key ? state.entries[key] : undefined))
    const ensureFresh = useDashboardStore((state) => state.ensureFresh)
    const revalidateAction = useDashboardStore((state) => state.revalidate)
    const patchAction = useDashboardStore((state) => state.patch)

    const active = enabled && key !== null

    useEffect(() => {
        if (!active || key === null) {
            return
        }
        ensureFresh(key, (signal) => fetcherRef.current(signal), ttlMs)
    }, [active, key, ttlMs, ensureFresh])

    const revalidate = useCallback(() => {
        if (key === null) {
            return
        }
        void revalidateAction(key, (signal) => fetcherRef.current(signal))
    }, [key, revalidateAction])

    const set = useCallback<ResourceSetter<T>>(
        (updater) => {
            if (key === null) {
                return
            }
            patchAction(key, updater as never)
        },
        [key, patchAction],
    )

    const data = entry?.data as T | undefined
    const status = entry?.status ?? "idle"

    return {
        data,
        status,
        error: entry?.error ?? null,
        isLoading: status === "loading" && data === undefined,
        isValidating: status === "loading",
        revalidate,
        set,
    }
}
