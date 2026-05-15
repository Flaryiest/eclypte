"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Download, Eye, RefreshCw } from "lucide-react"
import {
    DashboardPage,
    StatusBadge,
    formatBytes,
    formatDate,
    versionRef,
} from "../dashboardCommon"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import { AssetSummary, EclypteApiClient, RunSummary, isRunActive } from "@/services/eclypteApi"

type Preview = { asset: AssetSummary; url: string }

export default function AutomationPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [imports, setImports] = useState<RunSummary[]>([])
    const [drafts, setDrafts] = useState<RunSummary[]>([])
    const [renders, setRenders] = useState<AssetSummary[]>([])
    const [collection, setCollection] = useState("all")
    const [preview, setPreview] = useState<Preview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const hasActiveRuns = imports.some(isRunActive) || drafts.some(isRunActive)
    const autoDraftRenders = renders.filter((asset) => asset.tags.includes("auto_draft"))
    const collections = useMemo(() => {
        const values = new Set<string>()
        for (const run of [...imports, ...drafts]) {
            const value = run.inputs.collection_slug
            if (value) {
                values.add(value)
            }
        }
        for (const asset of autoDraftRenders) {
            const value = collectionFromTags(asset.tags)
            if (value) {
                values.add(value)
            }
        }
        return Array.from(values).sort()
    }, [autoDraftRenders, drafts, imports])
    const filteredImports = filterRunsByCollection(imports, collection)
    const filteredDrafts = filterRunsByCollection(drafts, collection)
    const filteredRenders = autoDraftRenders.filter((asset) => {
        return collection === "all" || collectionFromTags(asset.tags) === collection
    })

    const loadAutomation = useCallback(async () => {
        if (!api) {
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            const [nextImports, nextDrafts, nextRenders] = await Promise.all([
                api.listRuns({ workflowType: "bucket_import" }),
                api.listRuns({ workflowType: "auto_draft" }),
                api.listAssets("render_output"),
            ])
            setImports(nextImports)
            setDrafts(nextDrafts)
            setRenders(nextRenders)
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsLoading(false)
        }
    }, [api])

    useEffect(() => {
        void loadAutomation()
    }, [loadAutomation])

    useEffect(() => {
        if (!api || !hasActiveRuns) {
            return
        }
        const controller = new AbortController()
        let stopped = false
        let fallbackInterval: number | undefined
        const refresh = () => void loadAutomation()
        void api.streamRunUpdates({
            signal: controller.signal,
            onMessage: (message) => {
                if (
                    message.type === "run_manifest"
                    && ["bucket_import", "auto_draft"].includes(message.run.workflow_type)
                ) {
                    refresh()
                }
            },
        }).catch((caught) => {
            if (stopped || isAbortError(caught)) {
                return
            }
            fallbackInterval = window.setInterval(refresh, 1500)
        })
        return () => {
            stopped = true
            controller.abort()
            if (fallbackInterval !== undefined) {
                window.clearInterval(fallbackInterval)
            }
        }
    }, [api, hasActiveRuns, loadAutomation])

    const openPreview = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Draft render has no current version.")
            return
        }
        setError(null)
        try {
            const download = await api.getDownloadUrl(ref)
            setPreview({ asset, url: download.download_url })
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }

    const downloadAsset = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Draft render has no current version.")
            return
        }
        setDownloadingId(asset.file_id)
        setError(null)
        try {
            const downloadUrl = (await api.getDownloadUrl(ref)).download_url
            await downloadSignedUrl({
                url: downloadUrl,
                filename: safeDownloadFilename(asset.current_version?.original_filename || asset.display_name, "eclypte-auto-draft.mp4"),
            })
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDownloadingId(null)
        }
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="Automation" title="Loading automation"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Automation" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to review automation.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Automation"
            title="Auto-draft factory"
            subtitle="Review bucket imports, active private draft jobs, and completed auto-draft renders."
            action={
                <button className={styles.secondaryButton} type="button" onClick={loadAutomation} disabled={isLoading}>
                    <RefreshCw size={16} /> Refresh
                </button>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}

            <div className={styles.segmentedControl} role="tablist" aria-label="Collection filter">
                <button
                    className={collection === "all" ? styles.segmentActive : styles.segmentButton}
                    type="button"
                    onClick={() => setCollection("all")}
                >
                    All
                </button>
                {collections.map((item) => (
                    <button
                        className={collection === item ? styles.segmentActive : styles.segmentButton}
                        type="button"
                        key={item}
                        onClick={() => setCollection(item)}
                    >
                        {item}
                    </button>
                ))}
            </div>

            {preview && (
                <div className={styles.heroPlayer}>
                    <video className={styles.previewMedia} controls src={preview.url} />
                    <div className={styles.heroCaption}>
                        <div>
                            <h2 className={styles.heroCaptionTitle}>{preview.asset.display_name}</h2>
                            <p className={styles.heroCaptionMeta}>
                                {formatBytes(preview.asset.current_version?.size_bytes)} - {formatDate(preview.asset.updated_at)}
                            </p>
                        </div>
                        <button
                            className={styles.primaryButton}
                            type="button"
                            onClick={() => downloadAsset(preview.asset)}
                            disabled={downloadingId === preview.asset.file_id}
                        >
                            <Download size={16} /> {downloadingId === preview.asset.file_id ? "Downloading" : "Download"}
                        </button>
                    </div>
                </div>
            )}

            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Auto-drafts</h2>
                            <p>{filteredRenders.length} completed render{filteredRenders.length === 1 ? "" : "s"}</p>
                        </div>
                    </div>
                    {filteredRenders.length === 0 ? (
                        <div className={styles.emptyState}>No auto-draft renders yet.</div>
                    ) : (
                        <div className={styles.assetTable}>
                            {filteredRenders.map((asset) => (
                                <button
                                    type="button"
                                    className={styles.assetRow}
                                    key={asset.file_id}
                                    onClick={() => openPreview(asset)}
                                >
                                    <span className={styles.assetRowName}>
                                        <span className={styles.assetRowTitle}>{asset.display_name}</span>
                                        <span className={styles.assetRowMeta}>{collectionFromTags(asset.tags) || "uncategorized"}</span>
                                    </span>
                                    <span className={styles.assetRowCellNumeral}>{formatBytes(asset.current_version?.size_bytes)}</span>
                                    <span className={styles.assetRowCell}>{formatDate(asset.updated_at)}</span>
                                    <span className={styles.assetRowCell}>
                                        <Eye size={16} aria-hidden />
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Draft jobs</h2>
                            <p>{filteredDrafts.length} tracked run{filteredDrafts.length === 1 ? "" : "s"}</p>
                        </div>
                    </div>
                    <RunList runs={filteredDrafts} empty="No auto-draft jobs found." />
                </div>

                <div className={`${styles.panel} ${styles.full}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Imports</h2>
                            <p>{filteredImports.length} bucket import{filteredImports.length === 1 ? "" : "s"}</p>
                        </div>
                    </div>
                    <RunList runs={filteredImports} empty="No bucket imports found." />
                </div>
            </section>
        </DashboardPage>
    )
}

function RunList({ runs, empty }: { runs: RunSummary[]; empty: string }) {
    if (runs.length === 0) {
        return <div className={styles.emptyState}>{empty}</div>
    }
    return (
        <ul className={styles.runList}>
            {runs.map((run) => (
                <li className={styles.listCard} key={run.run_id}>
                    <div className={styles.cardTop}>
                        <div>
                            <h3 style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.86rem" }}>{run.run_id}</h3>
                            <p className={styles.smallText}>
                                {run.inputs.collection_slug || "uncategorized"} - {run.current_step || run.workflow_type} - {formatDate(run.updated_at)}
                            </p>
                        </div>
                        <StatusBadge label={run.status} tone={run.status} />
                    </div>
                    {run.last_error && <div className={styles.errorBanner}>{run.last_error}</div>}
                </li>
            ))}
        </ul>
    )
}

function filterRunsByCollection(runs: RunSummary[], collection: string) {
    if (collection === "all") {
        return runs
    }
    return runs.filter((run) => run.inputs.collection_slug === collection)
}

function collectionFromTags(tags: string[]) {
    return tags.find((tag) => tag.startsWith("collection:"))?.slice("collection:".length) || ""
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}

function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}
