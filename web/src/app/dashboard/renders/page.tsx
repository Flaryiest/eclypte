"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { useRouter } from "next/navigation"
import { Download, RefreshCw, Send, Trash2 } from "lucide-react"
import {
    DashboardPage,
    EmptyState,
    Pager,
    SkeletonList,
    StatusBadge,
    errorMessage,
    formatBytes,
    formatDate,
    humanizeStageDetail,
    usePagination,
    versionRef,
} from "../dashboardCommon"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import { AssetSummary, EclypteApiClient, RunStreamMessage, isRunActive } from "@/services/eclypteApi"
import { useAssets, useRuns } from "@/stores/dashboardResources"
import { useRunStream } from "../useRunStream"

type RenderPreview = { asset: AssetSummary; url: string }

export default function RendersPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const router = useRouter()
    const [preview, setPreview] = useState<RenderPreview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)
    const [deletingId, setDeletingId] = useState<string | null>(null)
    const [publishingId, setPublishingId] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const outputsResource = useAssets(api, { kind: "render_output" })
    const outputs = useMemo(() => outputsResource.data ?? [], [outputsResource.data])
    const setOutputs = outputsResource.set
    const runsResource = useRuns(api, { workflowType: "render" })
    const runs = runsResource.data ?? []
    const runsPager = usePagination(runs, 10)
    const isLoading = outputsResource.isLoading || runsResource.isLoading
    const loadError = outputsResource.error ?? runsResource.error
    const hasActiveRuns = runs.some(isRunActive)
    const revalidateOutputs = outputsResource.revalidate
    const revalidateRuns = runsResource.revalidate
    const loadRenders = useCallback(() => {
        revalidateOutputs()
        revalidateRuns()
    }, [revalidateOutputs, revalidateRuns])

    useRunStream({
        api,
        enabled: hasActiveRuns,
        shouldRefresh: isRenderUpdate,
        refresh: loadRenders,
    })

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
            // Archived render outputs drop out of the render_output list, so remove
            // it locally rather than re-pulling every output and run.
            setOutputs((current = []) => current.filter((item) => item.file_id !== asset.file_id))
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDeletingId(null)
        }
    }

    const preparePost = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Render output has no current version.")
            return
        }
        setPublishingId(asset.file_id)
        setError(null)
        try {
            await api.createPublishingPost({ renderOutput: ref })
            router.push("/dashboard/publish")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setPublishingId(null)
        }
    }

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Reels" title="Loading renders">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Reels" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to view renders.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Reels"
            title="Your reels"
            subtitle="Watch and download your finished edits."
            action={
                <button className={styles.secondaryButton} type="button" onClick={loadRenders} disabled={isLoading}>
                    <RefreshCw size={16} /> Refresh
                </button>
            }
        >
            {(error || loadError) && <div className={styles.errorBanner}>{error || loadError}</div>}

            {isLoading && outputs.length === 0 ? (
                <SkeletonList count={3} />
            ) : outputs.length === 0 ? (
                <EmptyState title="No reels yet" hint="Head to Compose to make your first edit." />
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
                                    className={styles.secondaryButton}
                                    type="button"
                                    onClick={() => preparePost(preview.asset)}
                                    disabled={publishingId === preview.asset.file_id}
                                >
                                    <Send size={16} /> {publishingId === preview.asset.file_id ? "Preparing" : "Prepare post"}
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
                                    <h2>Recent activity</h2>
                                    <p>{runs.length} recent</p>
                                </div>
                            </div>
                            {runs.length === 0 ? (
                                <div className={styles.emptyState}>Nothing recent.</div>
                            ) : (
                                <>
                                    <ul className={styles.runList}>
                                        {runsPager.pageItems.map((run) => (
                                            <li className={styles.listCard} key={run.run_id}>
                                                <div className={styles.cardTop}>
                                                    <div>
                                                        <h3>Reel</h3>
                                                        <p className={styles.smallText}>{humanizeStageDetail(run.current_step, run.status)} · {formatDate(run.updated_at)}</p>
                                                    </div>
                                                    <StatusBadge label={run.status} tone={run.status} />
                                                </div>
                                                {run.last_error && <div className={styles.errorBanner}>{run.last_error}</div>}
                                            </li>
                                        ))}
                                    </ul>
                                    <Pager
                                        page={runsPager.page}
                                        pageCount={runsPager.pageCount}
                                        onPrev={runsPager.prev}
                                        onNext={runsPager.next}
                                    />
                                </>
                            )}
                        </div>
                    </section>
                </>
            )}
        </DashboardPage>
    )
}

function isRenderUpdate(message: RunStreamMessage) {
    return message.type === "run_manifest" && message.run.workflow_type === "render"
}
