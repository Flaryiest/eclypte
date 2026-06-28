import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import styles from "./studio.module.css"
import type { AssetState, AssetSummary, PublishingPostStatus, RunManifest, SynthesisReference } from "@/services/eclypteApi"

export function DashboardPage({
    eyebrow,
    title,
    subtitle,
    action,
    children,
}: {
    eyebrow: string
    title: string
    subtitle?: string
    action?: ReactNode
    children: ReactNode
}) {
    return (
        <main className={styles.page}>
            <header className={styles.header}>
                <div>
                    <p className={styles.eyebrow}>{eyebrow}</p>
                    <h1 className={styles.title}>{title}</h1>
                    {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
                </div>
                {action && <div className={styles.toolbar}>{action}</div>}
            </header>
            {children}
        </main>
    )
}

export function StatusBadge({
    label,
    tone,
}: {
    label: string
    tone?: AssetState | PublishingPostStatus | RunManifest["status"] | SynthesisReference["status"]
}) {
    const className = tone ? `${styles.badge} ${styles[tone]}` : styles.badge
    return (
        <span className={className}>
            <span className={styles.badgeDot} aria-hidden />
            {humanizeLabel(label)}
        </span>
    )
}

export function Skeleton({ className }: { className?: string }) {
    return <span className={`${styles.skeleton} ${className ?? ""}`} aria-hidden />
}

export function SkeletonCard() {
    return (
        <div className={styles.skeletonCard} aria-hidden>
            <Skeleton className={styles.skeletonTitle} />
            <Skeleton className={styles.skeletonLine} />
            <Skeleton className={styles.skeletonLineShort} />
        </div>
    )
}

export function SkeletonList({ count = 3 }: { count?: number }) {
    return (
        <div className={styles.skeletonList} role="status" aria-label="Loading">
            {Array.from({ length: count }, (_, index) => (
                <SkeletonCard key={index} />
            ))}
        </div>
    )
}

export function formatBytes(bytes: number | null | undefined) {
    if (bytes === null || bytes === undefined) {
        return "—"
    }
    if (bytes === 0) {
        return "0 B"
    }
    const units = ["B", "KB", "MB", "GB"]
    let size = bytes
    let unitIndex = 0
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024
        unitIndex += 1
    }
    return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

export function formatDate(value: string | null | undefined) {
    if (!value || value === "system") {
        return value || "Unknown"
    }
    return new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
    }).format(new Date(value))
}

export function versionRef(asset: AssetSummary) {
    if (!asset.current_version_id) {
        return null
    }
    return {
        file_id: asset.file_id,
        version_id: asset.current_version_id,
    }
}

// Turn a raw enum/identifier (snake_case, kebab-case, or lowercase) into a
// human-readable Title Case label: "music_analysis" -> "Music Analysis",
// "queued_scheduled" -> "Queued Scheduled", "needs setup" -> "Needs Setup".
export function humanizeLabel(value: string) {
    return value
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .split(" ")
        .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
        .join(" ")
}

export function kindLabel(kind: string) {
    return humanizeLabel(kind)
}

// Client-side pagination for dashboard lists. Renders one page of `pageSize`
// items at a time; pass a `resetKey` (e.g. the active tab/filter) to jump back to
// the first page when the underlying selection changes. The current page is kept
// in range automatically when the list shrinks (delete, archive, revalidate).
export function usePagination<T>(items: readonly T[], pageSize: number, resetKey?: unknown) {
    const [page, setPage] = useState(0)
    // Reset to the first page when the filter/tab identity changes. Adjusting state
    // during render (React's recommended pattern) avoids an effect + extra paint.
    const [seenResetKey, setSeenResetKey] = useState(resetKey)
    if (seenResetKey !== resetKey) {
        setSeenResetKey(resetKey)
        setPage(0)
    }
    const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
    // Keep the shown page in range when the list shrinks, without persisting it; the
    // prev/next handlers move relative to the clamped page so they self-correct.
    const safePage = Math.min(page, pageCount - 1)
    const start = safePage * pageSize
    return {
        page: safePage,
        pageCount,
        pageItems: items.slice(start, start + pageSize),
        total: items.length,
        prev: () => setPage(Math.max(0, safePage - 1)),
        next: () => setPage(Math.min(pageCount - 1, safePage + 1)),
    }
}

export function Pager({
    page,
    pageCount,
    onPrev,
    onNext,
}: {
    page: number
    pageCount: number
    onPrev: () => void
    onNext: () => void
}) {
    if (pageCount <= 1) {
        return null
    }
    return (
        <div className={styles.pager}>
            <button
                type="button"
                className={styles.pagerButton}
                onClick={onPrev}
                disabled={page === 0}
                aria-label="Previous page"
            >
                <ChevronLeft size={15} /> Prev
            </button>
            <span className={styles.pagerStatus} aria-live="polite">
                Page {page + 1} of {pageCount}
            </span>
            <button
                type="button"
                className={styles.pagerButton}
                onClick={onNext}
                disabled={page >= pageCount - 1}
                aria-label="Next page"
            >
                Next <ChevronRight size={15} />
            </button>
        </div>
    )
}

export function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}

export function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}

// Returns a stable callback that runs `load` with a fresh AbortSignal, aborting
// any previous in-flight call first. This gives "latest wins" semantics without a
// cache: a slow earlier load can't land after a newer one and clobber fresh state,
// and the in-flight request is canceled on unmount. The loader should pass the
// signal to its API calls, skip state writes on AbortError, and guard `finally`
// cleanup with `signal.aborted` so a superseded call doesn't reset shared flags.
export function useAbortableLoad(load: (signal: AbortSignal) => Promise<void>) {
    const loadRef = useRef(load)
    const controllerRef = useRef<AbortController | null>(null)
    // Keep the ref pointed at the latest closure without writing during render.
    // This effect commits before the consumer's load effect (registered later), so
    // a trigger always sees the current `load`.
    useEffect(() => {
        loadRef.current = load
    })
    useEffect(() => () => controllerRef.current?.abort(), [])
    return useCallback(() => {
        controllerRef.current?.abort()
        const controller = new AbortController()
        controllerRef.current = controller
        void loadRef.current(controller.signal)
    }, [])
}
