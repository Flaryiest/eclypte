import type { ReactNode } from "react"
import styles from "./studio.module.css"
import type { AssetState, AssetSummary, ContentCandidateStatus, RunManifest, SynthesisReference } from "@/services/eclypteApi"

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
    tone?: AssetState | ContentCandidateStatus | RunManifest["status"] | SynthesisReference["status"]
}) {
    const className = tone ? `${styles.badge} ${styles[tone]}` : styles.badge
    return (
        <span className={className}>
            <span className={styles.badgeDot} aria-hidden />
            {label}
        </span>
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
