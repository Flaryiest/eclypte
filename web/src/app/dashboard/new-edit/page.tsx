"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Download, Eye, RefreshCw, RotateCcw, Trash2, WandSparkles, XCircle } from "lucide-react"
import { DashboardPage, StatusBadge, formatBytes, formatDate, kindLabel, versionRef } from "../dashboardCommon"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import {
    AssetSummary,
    EclypteApiClient,
    EditJobStage,
    EditJobStatus,
    ExportFormat,
    PlanningMode,
} from "@/services/eclypteApi"

const POLL_INTERVAL_MS = 1000
const MIN_TRIM_DURATION_SEC = 1

export default function NewEditPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [assets, setAssets] = useState<AssetSummary[]>([])
    const [jobs, setJobs] = useState<EditJobStatus[]>([])
    const [audioId, setAudioId] = useState("")
    const [videoId, setVideoId] = useState("")
    const [planningMode, setPlanningMode] = useState<PlanningMode>("agent")
    const [exportFormat, setExportFormat] = useState<ExportFormat>("reels_9_16")
    const [songDurationSec, setSongDurationSec] = useState<number | null>(null)
    const [audioStartSec, setAudioStartSec] = useState(0)
    const [audioEndSec, setAudioEndSec] = useState(0)
    const [cropFocusX, setCropFocusX] = useState(0.5)
    const [creativeBrief, setCreativeBrief] = useState("")
    const [title, setTitle] = useState("")
    const [error, setError] = useState<string | null>(null)
    const [mediaStatus, setMediaStatus] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [isCreating, setIsCreating] = useState(false)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)
    const [cancelingId, setCancelingId] = useState<string | null>(null)
    const [deletingId, setDeletingId] = useState<string | null>(null)
    const [redoingId, setRedoingId] = useState<string | null>(null)
    const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({})
    const [sourcePreviewUrl, setSourcePreviewUrl] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const songs = assets.filter((asset) => asset.kind === "song_audio" && asset.current_version_id && !asset.archived_at)
    const videos = assets.filter((asset) => asset.kind === "source_video" && asset.current_version_id && !asset.archived_at)
    const selectedSong = songs.find((asset) => asset.file_id === audioId) ?? null
    const selectedVideo = videos.find((asset) => asset.file_id === videoId) ?? null
    const selectedAssets = [selectedSong, selectedVideo].filter(
        (asset): asset is AssetSummary => Boolean(asset),
    )
    const hasActiveJobs = jobs.some(isJobActive)
    const selectedDurationSec = songDurationSec ? Math.max(0, audioEndSec - audioStartSec) : null
    const hasValidTrim = selectedDurationSec === null || selectedDurationSec >= MIN_TRIM_DURATION_SEC
    const canStart = Boolean(api && selectedSong && selectedVideo && !isCreating && hasValidTrim)

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
        setSongDurationSec(null)
        setAudioStartSec(0)
        setAudioEndSec(0)
        setMediaStatus(null)
        if (!api || !selectedSong) {
            return
        }
        const audioRef = versionRef(selectedSong)
        if (!audioRef) {
            return
        }
        const controller = new AbortController()
        let audio: HTMLAudioElement | null = null
        setMediaStatus("Loading song length")
        void api.getDownloadUrl(audioRef, controller.signal)
            .then((download) => {
                if (controller.signal.aborted) {
                    return
                }
                audio = new Audio()
                audio.preload = "metadata"
                audio.onloadedmetadata = () => {
                    if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) {
                        setMediaStatus("Song length unavailable")
                        return
                    }
                    const duration = roundTime(audio.duration)
                    setSongDurationSec(duration)
                    setAudioStartSec(0)
                    setAudioEndSec(duration)
                    setMediaStatus(null)
                }
                audio.onerror = () => setMediaStatus("Song length unavailable")
                audio.src = download.download_url
                audio.load()
            })
            .catch((caught) => {
                if (!isAbortError(caught)) {
                    setMediaStatus("Song length unavailable")
                }
            })
        return () => {
            controller.abort()
            if (audio) {
                audio.src = ""
            }
        }
    }, [api, selectedSong])

    useEffect(() => {
        setSourcePreviewUrl(null)
        if (!api || !selectedVideo) {
            return
        }
        const videoRef = versionRef(selectedVideo)
        if (!videoRef) {
            return
        }
        const controller = new AbortController()
        void api.getDownloadUrl(videoRef, controller.signal)
            .then((download) => {
                if (!controller.signal.aborted) {
                    setSourcePreviewUrl(download.download_url)
                }
            })
            .catch((caught) => {
                if (!isAbortError(caught)) {
                    setSourcePreviewUrl(null)
                }
            })
        return () => controller.abort()
    }, [api, selectedVideo])

    useEffect(() => {
        if (!api || !hasActiveJobs) {
            return
        }
        const controller = new AbortController()
        let stopped = false
        let fallbackInterval: number | undefined
        let refreshTimeout: number | undefined
        const refresh = () => {
            void loadJobs().catch((caught) => setError(errorMessage(caught)))
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
                if (message.type === "run_manifest" && message.run.workflow_type === "edit_pipeline") {
                    scheduleRefresh()
                }
                if (message.type === "run_event" && message.event.event_type === "progress") {
                    scheduleRefresh()
                }
            },
        }).catch((caught) => {
            if (stopped || isAbortError(caught)) {
                return
            }
            fallbackInterval = window.setInterval(refresh, POLL_INTERVAL_MS)
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
                exportOptions: {
                    format: exportFormat,
                    audioStartSec: songDurationSec === null ? 0 : audioStartSec,
                    audioEndSec: songDurationSec === null ? null : audioEndSec,
                    cropFocusX,
                },
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

    const cancelJob = async (job: EditJobStatus) => {
        if (!api) {
            return
        }
        setCancelingId(job.run_id)
        setError(null)
        try {
            const next = await api.cancelEditJob(job.run_id)
            setJobs((current) => current.map((item) => item.run_id === next.run_id ? next : item))
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setCancelingId(null)
        }
    }

    const deleteJob = async (job: EditJobStatus) => {
        if (!api) {
            return
        }
        setDeletingId(job.run_id)
        setError(null)
        try {
            await api.deleteEditJob(job.run_id)
            setJobs((current) => current.filter((item) => item.run_id !== job.run_id))
            setPreviewUrls((current) => {
                const next = { ...current }
                delete next[job.run_id]
                return next
            })
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDeletingId(null)
        }
    }

    const redoJob = async (job: EditJobStatus) => {
        if (!api) {
            return
        }
        setRedoingId(job.run_id)
        setError(null)
        try {
            const next = await api.redoEditJob(job.run_id)
            setJobs((current) => [next, ...current])
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setRedoingId(null)
        }
    }

    const updateAudioStart = (value: number) => {
        if (!songDurationSec) {
            return
        }
        const next = clampTime(value, 0, Math.max(0, audioEndSec - MIN_TRIM_DURATION_SEC))
        setAudioStartSec(roundTime(next))
    }

    const updateAudioEnd = (value: number) => {
        if (!songDurationSec) {
            return
        }
        const next = clampTime(value, Math.min(songDurationSec, audioStartSec + MIN_TRIM_DURATION_SEC), songDurationSec)
        setAudioEndSec(roundTime(next))
    }

    const updateDuration = (value: number) => {
        if (!songDurationSec) {
            return
        }
        const duration = clampTime(value, MIN_TRIM_DURATION_SEC, songDurationSec)
        const end = Math.min(songDurationSec, audioStartSec + duration)
        setAudioEndSec(roundTime(end))
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
                        <div className={styles.exportSection}>
                            <div className={styles.exportHeader}>
                                <span>Export</span>
                                <span>{exportFormat === "reels_9_16" ? "1080 x 1920" : "1920 x 1080"}</span>
                            </div>
                            <div className={styles.segmentedControl} role="group" aria-label="Export format">
                                <button
                                    className={exportFormat === "reels_9_16" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setExportFormat("reels_9_16")}
                                    disabled={isCreating}
                                >
                                    Reels 9:16
                                </button>
                                <button
                                    className={exportFormat === "youtube_16_9" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setExportFormat("youtube_16_9")}
                                    disabled={isCreating}
                                >
                                    YouTube 16:9
                                </button>
                            </div>
                            <div className={styles.trimSummary}>
                                {songDurationSec === null
                                    ? mediaStatus || "Choose a song to set timing"
                                    : `${formatTime(audioStartSec)} - ${formatTime(audioEndSec)} (${formatSeconds(selectedDurationSec || 0)})`}
                            </div>
                            <div className={styles.rangeGrid}>
                                <label className={styles.rangeLabel}>
                                    Start
                                    <input
                                        className={styles.rangeInput}
                                        type="range"
                                        min={0}
                                        max={songDurationSec || 0}
                                        step={0.1}
                                        value={audioStartSec}
                                        onChange={(event) => updateAudioStart(Number(event.target.value))}
                                        disabled={isCreating || songDurationSec === null}
                                    />
                                </label>
                                <label className={styles.rangeLabel}>
                                    End
                                    <input
                                        className={styles.rangeInput}
                                        type="range"
                                        min={0}
                                        max={songDurationSec || 0}
                                        step={0.1}
                                        value={audioEndSec}
                                        onChange={(event) => updateAudioEnd(Number(event.target.value))}
                                        disabled={isCreating || songDurationSec === null}
                                    />
                                </label>
                            </div>
                            <div className={styles.numberGrid}>
                                <label className={styles.fieldLabel}>
                                    Start sec
                                    <input
                                        className={styles.input}
                                        type="number"
                                        min={0}
                                        max={songDurationSec || undefined}
                                        step={0.1}
                                        value={audioStartSec}
                                        onChange={(event) => updateAudioStart(Number(event.target.value))}
                                        disabled={isCreating || songDurationSec === null}
                                    />
                                </label>
                                <label className={styles.fieldLabel}>
                                    End sec
                                    <input
                                        className={styles.input}
                                        type="number"
                                        min={0}
                                        max={songDurationSec || undefined}
                                        step={0.1}
                                        value={audioEndSec}
                                        onChange={(event) => updateAudioEnd(Number(event.target.value))}
                                        disabled={isCreating || songDurationSec === null}
                                    />
                                </label>
                                <label className={styles.fieldLabel}>
                                    Length sec
                                    <input
                                        className={styles.input}
                                        type="number"
                                        min={MIN_TRIM_DURATION_SEC}
                                        max={songDurationSec || undefined}
                                        step={0.1}
                                        value={selectedDurationSec === null ? 0 : roundTime(selectedDurationSec)}
                                        onChange={(event) => updateDuration(Number(event.target.value))}
                                        disabled={isCreating || songDurationSec === null}
                                    />
                                </label>
                            </div>
                            {exportFormat === "reels_9_16" && (
                                <label className={styles.rangeLabel}>
                                    Crop focus
                                    <input
                                        className={styles.rangeInput}
                                        type="range"
                                        min={0}
                                        max={1}
                                        step={0.01}
                                        value={cropFocusX}
                                        onChange={(event) => setCropFocusX(Number(event.target.value))}
                                        disabled={isCreating}
                                    />
                                </label>
                            )}
                            <div className={`${styles.cropPreview} ${exportFormat === "reels_9_16" ? styles.cropPreviewVertical : styles.cropPreviewWide}`}>
                                {sourcePreviewUrl ? (
                                    <video
                                        className={styles.cropPreviewMedia}
                                        src={sourcePreviewUrl}
                                        muted
                                        playsInline
                                        controls
                                        style={{
                                            objectFit: exportFormat === "reels_9_16" ? "cover" : "contain",
                                            objectPosition: `${Math.round(cropFocusX * 100)}% center`,
                                        }}
                                    />
                                ) : (
                                    <div className={styles.cropPreviewEmpty}>Choose a source video</div>
                                )}
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
                                    isCanceling={cancelingId === job.run_id}
                                    isDeleting={deletingId === job.run_id}
                                    isRedoing={redoingId === job.run_id}
                                    onPreview={() => openPreview(job)}
                                    onDownload={() => downloadRender(job)}
                                    onCancel={() => cancelJob(job)}
                                    onDelete={() => deleteJob(job)}
                                    onRedo={() => redoJob(job)}
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
    isCanceling,
    isDeleting,
    isRedoing,
    onPreview,
    onDownload,
    onCancel,
    onDelete,
    onRedo,
}: {
    job: EditJobStatus
    previewUrl?: string
    isDownloading: boolean
    isCanceling: boolean
    isDeleting: boolean
    isRedoing: boolean
    onPreview: () => void
    onDownload: () => void
    onCancel: () => void
    onDelete: () => void
    onRedo: () => void
}) {
    const isComplete = job.status === "completed" && job.render_output
    const isActive = isJobActive(job)
    const canRedo = job.status === "failed" || job.status === "canceled"
    const canDelete = job.status === "failed" || job.status === "canceled" || job.status === "completed"
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
            {(isComplete || isActive || canRedo || canDelete) && (
                <div className={styles.cardActions}>
                    {isActive && (
                        <button className={styles.secondaryButton} type="button" onClick={onCancel} disabled={isCanceling}>
                            <XCircle size={16} /> {isCanceling ? "Canceling" : "Cancel"}
                        </button>
                    )}
                    {canRedo && (
                        <button className={styles.secondaryButton} type="button" onClick={onRedo} disabled={isRedoing}>
                            <RotateCcw size={16} /> {isRedoing ? "Starting" : "Redo"}
                        </button>
                    )}
                    {canDelete && (
                        <button className={styles.dangerButton} type="button" onClick={onDelete} disabled={isDeleting}>
                            <Trash2 size={16} /> {isDeleting ? "Deleting" : "Delete"}
                        </button>
                    )}
                    {isComplete && (
                        <>
                            <button className={styles.secondaryButton} type="button" onClick={onPreview}>
                                <Eye size={16} /> Preview
                            </button>
                            <button className={styles.primaryButton} type="button" onClick={onDownload} disabled={isDownloading}>
                                <Download size={16} /> {isDownloading ? "Downloading" : "Download MP4"}
                            </button>
                        </>
                    )}
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
    if (status === "canceled") return styles.failedStage
    return ""
}

function clampPercent(value: number) {
    return Math.max(0, Math.min(100, Math.round(value)))
}

function clampTime(value: number, min: number, max: number) {
    if (!Number.isFinite(value)) {
        return min
    }
    return Math.max(min, Math.min(max, value))
}

function roundTime(value: number) {
    return Math.round(value * 10) / 10
}

function formatTime(value: number) {
    const safe = Math.max(0, Math.floor(value))
    const minutes = Math.floor(safe / 60)
    const seconds = safe % 60
    return `${minutes}:${seconds.toString().padStart(2, "0")}`
}

function formatSeconds(value: number) {
    return `${roundTime(value).toFixed(1)}s`
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}

function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}
