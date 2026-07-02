import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { ChevronLeft, ChevronRight, Check, Copy, X } from "lucide-react"
import styles from "./studio.module.css"
import type { AssetState, AssetSummary, PublishingPostStatus, RunManifest, SynthesisReference } from "@/services/eclypteApi"

export { Select, type SelectOption } from "./Select"

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
            {statusLabel(label)}
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

const KIND_LABELS: Record<string, string> = {
    source_video: "Video",
    song_audio: "Audio",
}

export function kindLabel(kind: string) {
    return KIND_LABELS[kind] ?? humanizeLabel(kind)
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
    className,
}: {
    page: number
    pageCount: number
    onPrev: () => void
    onNext: () => void
    className?: string
}) {
    if (pageCount <= 1) {
        return null
    }
    return (
        <div className={`${styles.pager} ${className ?? ""}`}>
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

// Creator-facing names for the raw status enums that flow through every domain
// (assets, runs, edit jobs, publishing posts, autopilot items, references). The
// colored dot still comes from `tone`; this only maps the visible word. Unknown
// values fall through to Title Case via humanizeLabel, so custom labels are safe.
const STATUS_LABELS: Record<string, string> = {
    created: "Queued",
    pending: "Queued",
    queued: "Queued",
    queued_scheduled: "Scheduled",
    running: "Working",
    importing: "Importing",
    analyzing: "Analyzing",
    editing: "Editing",
    rendering: "Rendering",
    blocked: "Waiting",
    uploaded: "Uploaded",
    discovered: "Found",
    available: "Ready",
    imported: "Imported",
    completed: "Done",
    packaged: "Ready to review",
    ready: "Ready to review",
    approved: "Approved",
    draft: "Draft",
    scheduled: "Scheduled",
    published: "Posted",
    failed: "Failed",
    rejected: "Rejected",
    canceled: "Canceled",
    cancelled: "Canceled",
    archived: "Hidden",
}

export function statusLabel(value: string) {
    return STATUS_LABELS[value.trim().toLowerCase()] ?? humanizeLabel(value)
}

// Friendly per-status sentences for progress detail. `stage.detail` from the API
// can be a raw worker string or a bare status echo, so a bare token is replaced
// with a human phrase; an already-human sentence is shown as-is.
const STAGE_PHRASES: Record<string, string> = {
    created: "Queued…",
    pending: "Queued…",
    queued: "Queued…",
    running: "Working on it…",
    importing: "Importing the song…",
    analyzing: "Analyzing…",
    editing: "Cutting your edit…",
    rendering: "Rendering your edit…",
    render: "Rendering your edit…",
    encode: "Rendering your edit…",
    upload: "Finishing up…",
    poster: "Finishing up…",
    plan: "Planning the cuts…",
    timeline: "Planning the cuts…",
    blocked: "Waiting…",
    completed: "Done",
    published: "Posted",
    failed: "Something went wrong",
    canceled: "Canceled",
}

export function humanizeStageDetail(detail: string | null | undefined, status?: string) {
    const value = (detail ?? "").trim()
    // A bare enum-like token (no spaces) is a status echo, not a human message.
    const looksLikeEnum = value !== "" && /^[a-z0-9_-]+$/i.test(value)
    if (value === "" || looksLikeEnum) {
        const key = (looksLikeEnum ? value : status ?? "").trim().toLowerCase()
        return STAGE_PHRASES[key] ?? "Working…"
    }
    return value
}

// mm:ss for timeline/clip positions; e.g. 75 -> "1:15".
export function formatClock(totalSec: number | null | undefined) {
    if (totalSec === null || totalSec === undefined || !Number.isFinite(totalSec)) {
        return "—"
    }
    const s = Math.max(0, Math.round(totalSec))
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

// Spoken duration; e.g. 25 -> "25s", 95 -> "1m 35s".
export function formatDuration(totalSec: number | null | undefined) {
    if (totalSec === null || totalSec === undefined || !Number.isFinite(totalSec)) {
        return "—"
    }
    const s = Math.max(0, Math.round(totalSec))
    if (s < 60) {
        return `${s}s`
    }
    const minutes = Math.floor(s / 60)
    const rem = s % 60
    return rem ? `${minutes}m ${String(rem).padStart(2, "0")}s` : `${minutes}m`
}

// Strips a known media/asset extension off a display name for cleaner titles,
// e.g. "chorus.wav" -> "chorus". Shared by the Home feed and the asset Library.
export function stripExtension(name: string) {
    return name.replace(/\.(mp4|wav|mp3|m4a|aac|flac|ogg|opus|aiff|wma|jpg|jpeg|json)$/i, "")
}

// One consistent empty-state voice for every list, replacing the per-page ad-hoc copy.
export function EmptyState({
    title,
    hint,
    icon,
    action,
}: {
    title: string
    hint?: string
    icon?: ReactNode
    action?: ReactNode
}) {
    return (
        <div className={styles.emptyState} role="status">
            {icon && <span className={styles.emptyStateIcon} aria-hidden>{icon}</span>}
            <p className={styles.emptyStateTitle}>{title}</p>
            {hint && <p className={styles.emptyStateHint}>{hint}</p>}
            {action && <div className={styles.emptyStateAction}>{action}</div>}
        </div>
    )
}

// Structured label/value list — replaces raw JSON.stringify dumps of metrics, etc.
export function MetaList({ items }: { items: { label: string; value: ReactNode }[] }) {
    if (items.length === 0) {
        return null
    }
    return (
        <dl className={styles.metaList}>
            {items.map((item) => (
                <div key={item.label} className={styles.metaRow}>
                    <dt className={styles.metaKey}>{item.label}</dt>
                    <dd className={styles.metaValue}>{item.value}</dd>
                </div>
            ))}
        </dl>
    )
}

// Hides a raw identifier behind a copy affordance for the rare case ops needs it,
// instead of printing UUID walls into the UI.
export function CopyableId({ value, label = "Copy ID" }: { value: string; label?: string }) {
    const [copied, setCopied] = useState(false)
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
    useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
    return (
        <button
            type="button"
            className={styles.copyId}
            onClick={() => {
                void navigator.clipboard?.writeText(value)
                setCopied(true)
                if (timer.current) clearTimeout(timer.current)
                timer.current = setTimeout(() => setCopied(false), 1600)
            }}
        >
            {copied ? <Check size={13} /> : <Copy size={13} />}
            {copied ? "Copied" : label}
        </button>
    )
}

export function Spinner({ onInk = false }: { onInk?: boolean }) {
    return (
        <span
            className={`${styles.spinner} ${onInk ? styles.spinnerOnInk : ""}`}
            role="status"
            aria-label="Working"
        />
    )
}

// Long-running work: spinner + name on the left, human stage sentence + number on
// the right, a real bar underneath whenever a percentage exists (feedback tier 3).
export function ProgressRow({
    title,
    stageText,
    percent,
    error,
}: {
    title: ReactNode
    stageText: string
    percent: number | null
    error?: string | null
}) {
    return (
        <div className={styles.progressRow}>
            <div className={styles.progressRowTop}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                    {!error && <Spinner />}
                    <span className={styles.truncate}>{title}</span>
                </span>
                <span>{stageText}</span>
            </div>
            {percent !== null && !error && (
                <div className={styles.progressTrack}>
                    <div className={styles.progressFill} style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
                </div>
            )}
            {error && <p className={styles.smallText}>{error}</p>}
        </div>
    )
}

// The single modal pattern: right slide-over on desktop, bottom sheet on mobile
// (media query in studio.module.css). Escape closes; body scroll is locked.
export function Sheet({
    open,
    title,
    onClose,
    children,
    footer,
}: {
    open: boolean
    title: string
    onClose: () => void
    children: ReactNode
    footer?: ReactNode
}) {
    const panelRef = useRef<HTMLDivElement>(null)
    const onCloseRef = useRef(onClose)
    useEffect(() => {
        onCloseRef.current = onClose
    })
    useEffect(() => {
        if (!open) {
            return
        }
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                onCloseRef.current()
            }
        }
        document.addEventListener("keydown", onKey)
        const previousOverflow = document.body.style.overflow
        document.body.style.overflow = "hidden"
        panelRef.current?.focus()
        return () => {
            document.removeEventListener("keydown", onKey)
            document.body.style.overflow = previousOverflow
        }
    }, [open])
    if (!open) {
        return null
    }
    return (
        <>
            <button type="button" className={styles.sheetOverlay} aria-label="Close" onClick={onClose} />
            <div className={styles.sheet} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panelRef}>
                <div className={styles.sheetHeader}>
                    <h2 className={styles.sheetTitle}>{title}</h2>
                    <button type="button" className={styles.ghostButton} onClick={onClose}>
                        <X size={16} /> Close
                    </button>
                </div>
                <div className={styles.sheetBody}>{children}</div>
                {footer && <div className={styles.sheetFooter}>{footer}</div>}
            </div>
        </>
    )
}

// Quiet confirmations (feedback tiers 1-2). Mount ToastProvider once in the
// dashboard layout; pages call useToast()("Posted to Instagram").
type ToastItem = { id: number; text: string; tone: "ok" | "err" }

const ToastContext = createContext<(text: string, tone?: "ok" | "err") => void>(() => undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<ToastItem[]>([])
    const idRef = useRef(0)
    const push = useCallback((text: string, tone: "ok" | "err" = "ok") => {
        const id = ++idRef.current
        setToasts((current) => [...current, { id, text, tone }])
        setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 3500)
    }, [])
    return (
        <ToastContext.Provider value={push}>
            {children}
            <div className={styles.toastStack} role="status" aria-live="polite">
                {toasts.map((toast) => (
                    <div key={toast.id} className={styles.toast}>
                        <span className={toast.tone === "ok" ? styles.toastOk : styles.toastErr}>
                            {toast.tone === "ok" ? "✓" : "!"}
                        </span>
                        {toast.text}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    )
}

export function useToast() {
    return useContext(ToastContext)
}
