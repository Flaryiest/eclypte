"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Download, Film, RefreshCw } from "lucide-react"
import {
    DashboardPage,
    StatusBadge,
    formatBytes,
    formatDate,
    versionRef,
} from "../dashboardCommon"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import { AssetSummary, EclypteApiClient, RunSummary } from "@/services/eclypteApi"

type RenderPreview = { asset: AssetSummary; url: string }

export default function RendersPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [outputs, setOutputs] = useState<AssetSummary[]>([])
    const [runs, setRuns] = useState<RunSummary[]>([])
    const [preview, setPreview] = useState<RenderPreview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])

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

    const openPreview = async (asset: AssetSummary) => {
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
    }

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
            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Output assets</h2>
                            <p>{outputs.length} rendered MP4{outputs.length === 1 ? "" : "s"}</p>
                        </div>
                    </div>
                    {error && <div className={styles.errorBanner}>{error}</div>}
                    {outputs.length === 0 ? (
                        <div className={styles.emptyState}>No renders yet. Create one from New Edit.</div>
                    ) : (
                        <div className={styles.assetGrid}>
                            {outputs.map((asset) => (
                                <article className={styles.assetCard} key={asset.file_id}>
                                    <div className={styles.cardTop}>
                                        <div>
                                            <h3>{asset.display_name}</h3>
                                            <p className={styles.smallText}>
                                                {formatBytes(asset.current_version?.size_bytes)} - {formatDate(asset.updated_at)}
                                            </p>
                                        </div>
                                        <StatusBadge label="ready" tone="ready" />
                                    </div>
                                    <div className={styles.cardActions}>
                                        <button className={styles.secondaryButton} type="button" onClick={() => openPreview(asset)}>
                                            <Film size={16} /> Preview
                                        </button>
                                        {preview?.asset.file_id === asset.file_id && (
                                            <button
                                                className={styles.ghostButton}
                                                type="button"
                                                onClick={() => downloadAsset(asset)}
                                                disabled={downloadingId === asset.file_id}
                                            >
                                                <Download size={16} /> {downloadingId === asset.file_id ? "Downloading" : "Download"}
                                            </button>
                                        )}
                                    </div>
                                </article>
                            ))}
                        </div>
                    )}
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
                                            <h3>{run.run_id}</h3>
                                            <p className={styles.smallText}>{run.current_step || "render"} - {formatDate(run.updated_at)}</p>
                                        </div>
                                        <StatusBadge label={run.status} tone={run.status} />
                                    </div>
                                    {run.last_error && <div className={styles.errorBanner}>{run.last_error}</div>}
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                {preview && (
                    <div className={`${styles.panel} ${styles.full}`}>
                        <div className={styles.panelHeader}>
                            <div>
                                <h2>{preview.asset.display_name}</h2>
                                <p>Presigned preview URL for the latest render version.</p>
                            </div>
                            <button
                                className={styles.primaryButton}
                                type="button"
                                onClick={() => downloadAsset(preview.asset)}
                                disabled={downloadingId === preview.asset.file_id}
                            >
                                <Download size={16} /> {downloadingId === preview.asset.file_id ? "Downloading" : "Download MP4"}
                            </button>
                        </div>
                        <video className={styles.previewMedia} controls src={preview.url} />
                    </div>
                )}
            </section>
        </DashboardPage>
    )
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
