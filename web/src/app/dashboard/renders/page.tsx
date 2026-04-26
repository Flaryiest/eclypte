"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Download, RefreshCw, Trash2 } from "lucide-react"
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

type RenderPreview = { asset: AssetSummary; url: string }

export default function RendersPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [outputs, setOutputs] = useState<AssetSummary[]>([])
    const [runs, setRuns] = useState<RunSummary[]>([])
    const [preview, setPreview] = useState<RenderPreview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)
    const [deletingId, setDeletingId] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const hasActiveRuns = runs.some(isRunActive)

    const loadRenders = useCallback(async () => {
        if (!api) {
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            const [nextOutputs, nextRuns] = await Promise.all([
                api.listAssets("render_output"),
                api.listRuns({ workflowType: "render" }),
            ])
            setOutputs(nextOutputs)
            setRuns(nextRuns)
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsLoading(false)
        }
    }, [api])

    useEffect(() => {
        void loadRenders()
    }, [loadRenders])

    useEffect(() => {
        if (!api || !hasActiveRuns) {
            return
        }
        const controller = new AbortController()
        let stopped = false
        let fallbackInterval: number | undefined
        let refreshTimeout: number | undefined
        const refresh = () => {
            void loadRenders()
        }
        const scheduleRefresh = () => {
            if (refreshTimeout !== undefined) {
                return
            }
            refreshTimeout = window.setTimeout(() => {
                refreshTimeout = undefined
                refresh()
            }, 150)
        }
        void api.streamRunUpdates({
            signal: controller.signal,
            onMessage: (message) => {
                if (message.type === "run_manifest" && message.run.workflow_type === "render") {
                    scheduleRefresh()
                }
            },
        }).catch((caught) => {
            if (stopped || isAbortError(caught)) {
                return
            }
            fallbackInterval = window.setInterval(refresh, 1000)
        })
        return () => {
            stopped = true
            controller.abort()
            if (fallbackInterval !== undefined) {
                window.clearInterval(fallbackInterval)
            }
            if (refreshTimeout !== undefined) {
                window.clearTimeout(refreshTimeout)
            }
        }
    }, [api, hasActiveRuns, loadRenders])

    const openPreview = useCallback(async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Render output has no current version.")
            return
        }
        setError(null)
        try {
            const download = await api.getDownloadUrl(ref)
            setPreview({ asset, url: download.download_url })
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }, [api])

    useEffect(() => {
        if (!preview && outputs.length > 0) {
            void openPreview(outputs[0])
        }
    }, [outputs, preview, openPreview])

    const downloadAsset = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Render output has no current version.")
            return
        }
        setDownloadingId(asset.file_id)
        setError(null)
        try {
            const downloadUrl = (await api.getDownloadUrl(ref)).download_url
            await downloadSignedUrl({
                url: downloadUrl,
                filename: safeDownloadFilename(asset.current_version?.original_filename || asset.display_name, "eclypte-render.mp4"),
            })
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDownloadingId(null)
        }
    }

    const deleteRender = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        setDeletingId(asset.file_id)
        setError(null)
        try {
            await api.deleteAsset(asset.file_id)
            if (preview?.asset.file_id === asset.file_id) {
                setPreview(null)
            }
            await loadRenders()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDeletingId(null)
        }
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="Renders" title="Loading renders"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Renders" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to view renders.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Renders"
            title="Render library"
            subtitle="Review completed MP4 outputs and recent render runs."
            action={
                <button className={styles.secondaryButton} type="button" onClick={loadRenders} disabled={isLoading}>
                    <RefreshCw size={16} /> Refresh
                </button>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}

            {outputs.length === 0 ? (
                <div className={styles.emptyState}>No renders yet. Create one from New Edit.</div>
            ) : (
                <>
                    {preview && (
                        <div className={styles.heroPlayer}>
                            <video className={styles.previewMedia} controls src={preview.url} />
                            <div className={styles.heroCaption}>
                                <div>
                                    <h2 className={styles.heroCaptionTitle}>{preview.asset.display_name}</h2>
                                    <p className={styles.heroCaptionMeta}>
                                        {formatBytes(preview.asset.current_version?.size_bytes)} · {formatDate(preview.asset.updated_at)}
                                    </p>
                                </div>
                                <button
                                    className={styles.primaryButton}
                                    type="button"
                                    onClick={() => downloadAsset(preview.asset)}
                                    disabled={downloadingId === preview.asset.file_id}
                                >
                                    <Download size={16} /> {downloadingId === preview.asset.file_id ? "Downloading" : "Download MP4"}
                                </button>
                                <button
                                    className={styles.dangerButton}
                                    type="button"
                                    onClick={() => deleteRender(preview.asset)}
                                    disabled={deletingId === preview.asset.file_id}
                                >
                                    <Trash2 size={16} /> {deletingId === preview.asset.file_id ? "Deleting" : "Delete"}
                                </button>
                            </div>
                        </div>
                    )}

                    <section className={styles.grid}>
                        <div className={`${styles.panel} ${styles.wide}`}>
                            <div className={styles.panelHeader}>
                                <div>
                                    <h2>All renders</h2>
                                    <p>{outputs.length} rendered MP4{outputs.length === 1 ? "" : "s"}</p>
                                </div>
                            </div>
                            <div className={styles.filmstrip}>
                                {outputs.map((asset) => {
                                    const isActive = preview?.asset.file_id === asset.file_id
                                    return (
                                        <button
                                            type="button"
                                            key={asset.file_id}
                                            className={`${styles.filmstripCard} ${isActive ? styles.filmstripActive : ""}`}
                                            onClick={() => openPreview(asset)}
                                            aria-pressed={isActive}
                                        >
                                            <div className={styles.filmstripFrame}>{asset.display_name}</div>
                                            <span className={styles.assetRowMeta}>{formatDate(asset.updated_at)}</span>
                                            <span className={styles.assetRowCellNumeral}>{formatBytes(asset.current_version?.size_bytes)}</span>
                                        </button>
                                    )
                                })}
                            </div>
                        </div>

                        <div className={`${styles.panel} ${styles.side}`}>
                            <div className={styles.panelHeader}>
                                <div>
                                    <h2>Render runs</h2>
                                    <p>{runs.length} tracked run{runs.length === 1 ? "" : "s"}</p>
                                </div>
                            </div>
                            {runs.length === 0 ? (
                                <div className={styles.emptyState}>No render runs found.</div>
                            ) : (
                                <ul className={styles.runList}>
                                    {runs.map((run) => (
                                        <li className={styles.listCard} key={run.run_id}>
                                            <div className={styles.cardTop}>
                                                <div>
                                                    <h3 style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.86rem" }}>{run.run_id}</h3>
                                                    <p className={styles.smallText}>{run.current_step || "render"} · {formatDate(run.updated_at)}</p>
                                                </div>
                                                <StatusBadge label={run.status} tone={run.status} />
                                            </div>
                                            {run.last_error && <div className={styles.errorBanner}>{run.last_error}</div>}
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </section>
                </>
            )}
        </DashboardPage>
    )
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}

function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}
