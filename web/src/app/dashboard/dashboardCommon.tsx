import { useCallback, useEffect, useRef, type ReactNode } from "react"
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
            {label}
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

export function kindLabel(kind: string) {
    return kind.replaceAll("_", " ")
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
