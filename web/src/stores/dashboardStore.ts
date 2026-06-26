import { create } from "zustand"

// A tiny stale-while-revalidate cache shared across dashboard pages, so navigating
// between routes paints instantly from cache and revalidates in the background
// instead of re-fetching cold every mount. Entries are keyed by a caller-supplied
// string (resource + user + params). Only structural records are cached here —
// never signed download/preview URLs, which expire.

export type ResourceStatus = "idle" | "loading" | "success" | "error"

export type ResourceEntry<T = unknown> = {
    data: T | undefined
    status: ResourceStatus
    error: string | null
    lastFetchedMs: number
    inFlight: Promise<void> | null
    controller: AbortController | null
}

export type ResourceFetcher = (signal: AbortSignal) => Promise<unknown>
export type ResourceUpdater = unknown | ((prev: unknown) => unknown)

type DashboardStoreState = {
    entries: Record<string, ResourceEntry>
    ensureFresh: (key: string, fetcher: ResourceFetcher, ttlMs: number) => void
    revalidate: (key: string, fetcher: ResourceFetcher) => Promise<void>
    patch: (key: string, updater: ResourceUpdater) => void
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError"
}

function messageOf(error: unknown): string {
    return error instanceof Error ? error.message : "Something went wrong"
}

export const useDashboardStore = create<DashboardStoreState>((set, get) => ({
    entries: {},

    ensureFresh: (key, fetcher, ttlMs) => {
        const entry = get().entries[key]
        // Dedup: a fetch is already running for this key.
        if (entry?.inFlight) {
            return
        }
        // Fresh enough: serve from cache without a network round-trip.
        if (entry && entry.status === "success" && Date.now() - entry.lastFetchedMs < ttlMs) {
            return
        }
        void get().revalidate(key, fetcher)
    },

    revalidate: (key, fetcher) => {
        // Latest-wins: abort any prior in-flight fetch for this key.
        get().entries[key]?.controller?.abort()
        const controller = new AbortController()

        const run = (async () => {
            try {
                const data = await fetcher(controller.signal)
                // Drop the result if a newer fetch superseded this one.
                if (get().entries[key]?.controller !== controller) {
                    return
                }
                set((state) => ({
                    entries: {
                        ...state.entries,
                        [key]: {
                            data,
                            status: "success",
                            error: null,
                            lastFetchedMs: Date.now(),
                            inFlight: null,
                            controller: null,
                        },
                    },
                }))
            } catch (error) {
                if (isAbortError(error) || get().entries[key]?.controller !== controller) {
                    return
                }
                set((state) => {
                    const current = state.entries[key]
                    return {
                        entries: {
                            ...state.entries,
                            [key]: {
                                data: current?.data,
                                status: "error",
                                error: messageOf(error),
                                lastFetchedMs: current?.lastFetchedMs ?? 0,
                                inFlight: null,
                                controller: null,
                            },
                        },
                    }
                })
            }
        })()

        set((state) => {
            const current = state.entries[key]
            return {
                entries: {
                    ...state.entries,
                    [key]: {
                        data: current?.data,
                        status: "loading",
                        error: current?.error ?? null,
                        lastFetchedMs: current?.lastFetchedMs ?? 0,
                        inFlight: run,
                        controller,
                    },
                },
            }
        })

        return run
    },

    patch: (key, updater) => {
        set((state) => {
            const current = state.entries[key]
            const nextData =
                typeof updater === "function"
                    ? (updater as (prev: unknown) => unknown)(current?.data)
                    : updater
            return {
                entries: {
                    ...state.entries,
                    [key]: {
                        data: nextData,
                        status: "success",
                        error: null,
                        // Mark fresh so an in-flight background revalidate won't
                        // immediately clobber this optimistic mutation.
                        lastFetchedMs: Date.now(),
                        inFlight: current?.inFlight ?? null,
                        controller: current?.controller ?? null,
                    },
                },
            }
        })
    },
}))
