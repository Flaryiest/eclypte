"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Download, Eye, RefreshCw, WandSparkles } from "lucide-react"
import { DashboardPage, StatusBadge, formatBytes, formatDate, kindLabel, versionRef } from "../dashboardCommon"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import {
    AssetSummary,
    EclypteApiClient,
    EditJobStage,
    EditJobStatus,
    PlanningMode,
} from "@/services/eclypteApi"

const POLL_INTERVAL_MS = 3000

export default function NewEditPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [assets, setAssets] = useState<AssetSummary[]>([])
    const [jobs, setJobs] = useState<EditJobStatus[]>([])
    const [audioId, setAudioId] = useState("")
    const [videoId, setVideoId] = useState("")
    const [planningMode, setPlanningMode] = useState<PlanningMode>("agent")
    const [creativeBrief, setCreativeBrief] = useState("")
    const [title, setTitle] = useState("")
    const [error, setError] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [isCreating, setIsCreating] = useState(false)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)
    const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({})

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const songs = assets.filter((asset) => asset.kind === "song_audio")
    const videos = assets.filter((asset) => asset.kind === "source_video")
    const selectedSong = songs.find((asset) => asset.file_id === audioId) ?? null
    const selectedVideo = videos.find((asset) => asset.file_id === videoId) ?? null
    const selectedAssets = [selectedSong, selectedVideo].filter(
        (asset): asset is AssetSummary => Boolean(asset),
    )
    const hasActiveJobs = jobs.some(isJobActive)
    const canStart = Boolean(api && selectedSong && selectedVideo && !isCreating)

    const loadJobs = useCallback(async () => {
        if (!api) {
            return
        }
        setJobs(await api.listEditJobs())
    }, [api])

    const loadDashboard = useCallback(async () => {
        if (!api) {
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            const [nextAssets, nextJobs] = await Promise.all([
                api.listAssets(),
                api.listEditJobs(),
            ])
            setAssets(nextAssets)
            setJobs(nextJobs)
            setAudioId((current) => current || nextAssets.find((asset) => asset.kind === "song_audio")?.file_id || "")
            setVideoId((current) => current || nextAssets.find((asset) => asset.kind === "source_video")?.file_id || "")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsLoading(false)
        }
    }, [api])

    useEffect(() => {
        void loadDashboard()
    }, [loadDashboard])

    useEffect(() => {
        if (!api || !hasActiveJobs) {
            return
        }
        const interval = window.setInterval(() => {
            void loadJobs().catch((caught) => setError(errorMessage(caught)))
        }, POLL_INTERVAL_MS)
        return () => window.clearInterval(interval)
    }, [api, hasActiveJobs, loadJobs])

    const startEdit = async () => {
        if (!api || !selectedSong || !selectedVideo || !canStart) {
            return
        }
        const audio = versionRef(selectedSong)
        const sourceVideo = versionRef(selectedVideo)
        if (!audio || !sourceVideo) {
            setError("Selected assets do not have current versions.")
            return
        }
        setIsCreating(true)
        setError(null)
        try {
            const job = await api.createEditJob({
                audio,
                sourceVideo,
                planningMode,
                creativeBrief: creativeBrief.trim(),
                title: title.trim() || `${selectedSong.display_name} x ${selectedVideo.display_name}`,
            })
            setJobs((current) => [job, ...current.filter((item) => item.run_id !== job.run_id)])
            setTitle("")
            setCreativeBrief("")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsCreating(false)
        }
    }

    const openPreview = async (job: EditJobStatus) => {
        if (!api || !job.render_output) {
            return
        }
        setError(null)
        try {
            const download = await api.getDownloadUrl(job.render_output)
            setPreviewUrls((current) => ({ ...current, [job.run_id]: download.download_url }))
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }

    const downloadRender = async (job: EditJobStatus) => {
        if (!api || !job.render_output) {
            return
        }
        setDownloadingId(job.run_id)
        setError(null)
        try {
            const download = await api.getDownloadUrl(job.render_output)
            await downloadSignedUrl({
                url: download.download_url,
                filename: safeDownloadFilename(`${job.title || job.run_id}.mp4`, "eclypte-amv.mp4"),
            })
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDownloadingId(null)
        }
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="New edit" title="Preparing studio"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="New edit" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to create an AMV.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="New edit"
            title="Create from assets"
            subtitle="Launch durable edit jobs from saved assets. Active jobs keep updating after refresh."
            action={
                <>
                    <button className={styles.secondaryButton} type="button" onClick={loadDashboard} disabled={isLoading || isCreating}>
                        <RefreshCw size={16} /> Refresh
                    </button>
                    <button className={styles.primaryButton} type="button" onClick={startEdit} disabled={!canStart}>
                        <WandSparkles size={16} /> {isCreating ? "Starting" : "Create AMV"}
                    </button>
                </>
            }
        >
            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Compose</h2>
                            <p>Use analyzed or uploaded songs and source videos.</p>
                        </div>
                    </div>
                    {error && <div className={styles.errorBanner}>{error}</div>}
                    <div className={styles.fieldStack}>
                        <label className={styles.fieldLabel}>
                            Edit title
                            <input
                                className={styles.input}
                                value={title}
                                onChange={(event) => setTitle(event.target.value)}
                                placeholder="Weekend hook edit"
                                disabled={isCreating}
                            />
                        </label>
                        <label className={styles.fieldLabel}>
                            Song
                            <select className={styles.select} value={audioId} onChange={(event) => setAudioId(event.target.value)} disabled={isCreating}>
                                <option value="">Choose a WAV song</option>
                                {songs.map((asset) => (
                                    <option key={asset.file_id} value={asset.file_id}>
                                        {asset.display_name} - {formatBytes(asset.current_version?.size_bytes)}
                                    </option>
                                ))}
                            </select>
                            {selectedSong && (
                                <span className={`${styles.assetCaption} ${selectedSong.analysis ? styles.assetCaptionOk : ""}`}>
                                    {selectedSong.analysis ? "✓ analyzed" : "○ awaiting analysis"} · {kindLabel(selectedSong.kind)} · {formatBytes(selectedSong.current_version?.size_bytes)}
                                </span>
                            )}
                        </label>
                        <label className={styles.fieldLabel}>
                            Source video
                            <select className={styles.select} value={videoId} onChange={(event) => setVideoId(event.target.value)} disabled={isCreating}>
                                <option value="">Choose an MP4 video</option>
                                {videos.map((asset) => (
                                    <option key={asset.file_id} value={asset.file_id}>
                                        {asset.display_name} - {formatBytes(asset.current_version?.size_bytes)}
                                    </option>
                                ))}
                            </select>
                            {selectedVideo && (
                                <span className={`${styles.assetCaption} ${selectedVideo.analysis ? styles.assetCaptionOk : ""}`}>
                                    {selectedVideo.analysis ? "✓ analyzed" : "○ awaiting analysis"} · {kindLabel(selectedVideo.kind)} · {formatBytes(selectedVideo.current_version?.size_bytes)}
                                </span>
                            )}
                        </label>
                        <div className={styles.fieldLabel}>
                            Planning mode
                            <div className={styles.segmentedControl} role="group" aria-label="Planning mode">
                                <button
                                    className={planningMode === "agent" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setPlanningMode("agent")}
                                    disabled={isCreating}
                                >
                                    AI agent
                                </button>
                                <button
                                    className={planningMode === "deterministic" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setPlanningMode("deterministic")}
                                    disabled={isCreating}
                                >
                                    Deterministic
                                </button>
                            </div>
                        </div>
                        {planningMode === "agent" && (
                            <label className={styles.fieldLabel}>
                                Creative brief
                                <textarea
                                    className={`${styles.textarea} ${styles.compactTextarea}`}
                                    value={creativeBrief}
                                    onChange={(event) => setCreativeBrief(event.target.value)}
                                    placeholder="Fast hook, cinematic pacing, follow the character arc."
                                    disabled={isCreating}
                                />
                            </label>
                        )}
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Queue</h2>
                            <p>{jobs.length} job{jobs.length === 1 ? "" : "s"} · {selectedAssets.length}/2 ready</p>
                        </div>
                    </div>
                    {jobs.length === 0 ? (
                        <div className={styles.emptyState}>No edit jobs yet.</div>
                    ) : (
                        <div className={styles.jobList}>
                            {jobs.map((job) => (
                                <EditJobCard
                                    key={job.run_id}
                                    job={job}
                                    previewUrl={previewUrls[job.run_id]}
                                    isDownloading={downloadingId === job.run_id}
                                    onPreview={() => openPreview(job)}
                                    onDownload={() => downloadRender(job)}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </section>
        </DashboardPage>
    )
}

function EditJobCard({
    job,
    previewUrl,
    isDownloading,
    onPreview,
    onDownload,
}: {
    job: EditJobStatus
    previewUrl?: string
    isDownloading: boolean
    onPreview: () => void
    onDownload: () => void
}) {
    const isComplete = job.status === "completed" && job.render_output
    return (
        <article className={styles.jobCard}>
            <div className={styles.cardTop}>
                <div>
                    <h3>{job.title}</h3>
                    <p className={styles.smallText}>{job.run_id} - {formatDate(job.updated_at)}</p>
                </div>
                <StatusBadge label={job.status} tone={job.status} />
            </div>
            <div className={styles.progressHeader}>
                <span>{job.progress_percent}%</span>
                <span>{job.status}</span>
            </div>
            <div className={styles.progressTrack} aria-label={`${job.title} progress`}>
                <div className={styles.progressFill} style={{ width: `${clampPercent(job.progress_percent)}%` }} />
            </div>
            <div className={styles.stageProgressList}>
                {job.stages.map((stage) => (
                    <StageProgress key={stage.id} stage={stage} />
                ))}
            </div>
            {job.last_error && <div className={styles.errorBanner}>{job.last_error}</div>}
            {isComplete && (
                <div className={styles.cardActions}>
                    <button className={styles.secondaryButton} type="button" onClick={onPreview}>
                        <Eye size={16} /> Preview
                    </button>
                    <button className={styles.primaryButton} type="button" onClick={onDownload} disabled={isDownloading}>
                        <Download size={16} /> {isDownloading ? "Downloading" : "Download MP4"}
                    </button>
                </div>
            )}
            {previewUrl && <video className={styles.previewMedia} controls src={previewUrl} />}
        </article>
    )
}

function StageProgress({ stage }: { stage: EditJobStage }) {
    return (
        <div className={`${styles.stageProgressRow} ${stageClass(stage.status)}`}>
            <div className={styles.stageProgressMeta}>
                <span>{stage.label}</span>
                <span>{clampPercent(stage.percent)}%</span>
            </div>
            <div className={styles.progressTrack}>
                <div className={styles.progressFill} style={{ width: `${clampPercent(stage.percent)}%` }} />
            </div>
            <span className={styles.stageDetail}>{stage.detail}</span>
        </div>
    )
}

function isJobActive(job: EditJobStatus) {
    return job.status === "created" || job.status === "running" || job.status === "blocked"
}

function stageClass(status: EditJobStage["status"]) {
    if (status === "running") return styles.activeStage
    if (status === "completed") return styles.completeStage
    if (status === "failed") return styles.failedStage
    return ""
}

function clampPercent(value: number) {
    return Math.max(0, Math.min(100, Math.round(value)))
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
