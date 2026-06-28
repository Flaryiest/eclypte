"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Download, Eye, Play, RefreshCw, RotateCcw, Trash2, WandSparkles, XCircle } from "lucide-react"
import { DashboardPage, Pager, SkeletonList, StatusBadge, errorMessage, formatBytes, formatDate, isAbortError, kindLabel, usePagination, versionRef } from "../dashboardCommon"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import {
    AssetSummary,
    EclypteApiClient,
    EditJobStage,
    EditJobStatus,
    ExportFormat,
    PlanningMode,
    RunStreamMessage,
} from "@/services/eclypteApi"
import { useAssets, useEditJobs } from "@/stores/dashboardResources"
import { useRunStream } from "../useRunStream"

const MIN_TRIM_DURATION_SEC = 1

// Mirror of EDIT_STAGE_WEIGHTS in api/app.py — keep in sync. Approximate share of
// wall-clock per edit stage; used here only as a prior/ratio for the time-left
// estimate (the bar itself is weighted server-side).
const EDIT_STAGE_WEIGHTS: Record<string, number> = {
    assets: 0.02,
    music: 0.15,
    video: 0.22,
    timeline: 0.2,
    render: 0.39,
    result: 0.02,
}
const ETA_DEFAULT_TOTAL_SEC = 150 // prior before any stage has produced a real timing
const ETA_MIN_CALIBRATION_SEC = 2 // ignore reused/instant stages when calibrating the run total
const ETA_LOCAL_RATE_MIN_PCT = 8 // below this, use the stage's expected duration, not its local rate
const ETA_SMOOTHING = 0.3 // EMA factor applied when a real progress update arrives

export default function NewEditPage() {
    const { isLoaded, isSignedIn, user } = useUser()
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
    const [isCreating, setIsCreating] = useState(false)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)
    const [cancelingId, setCancelingId] = useState<string | null>(null)
    const [deletingId, setDeletingId] = useState<string | null>(null)
    const [redoingId, setRedoingId] = useState<string | null>(null)
    const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({})
    const [posterUrls, setPosterUrls] = useState<Record<string, string>>({})
    const posterRequested = useRef<Set<string>>(new Set())
    const [sourcePreviewUrl, setSourcePreviewUrl] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    // Shares the cached library with /dashboard/assets (same includeArchived key); the
    // computed song/video lists below already drop archived assets.
    const assetsResource = useAssets(api, { includeArchived: true })
    const assets = useMemo(() => assetsResource.data ?? [], [assetsResource.data])
    const jobsResource = useEditJobs(api)
    const jobs = useMemo(() => jobsResource.data ?? [], [jobsResource.data])
    const jobsPager = usePagination(jobs, 10)
    const setJobs = jobsResource.set
    const isLoading = assetsResource.isLoading || jobsResource.isLoading
    const loadError = assetsResource.error ?? jobsResource.error
    const refreshDashboard = () => {
        assetsResource.revalidate()
        jobsResource.revalidate()
    }
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

    // Default the song/video pickers to the first available asset once the cached
    // library loads, without clobbering an explicit user choice.
    const firstSongId = songs[0]?.file_id ?? ""
    const firstVideoId = videos[0]?.file_id ?? ""
    useEffect(() => {
        if (firstSongId) {
            setAudioId((current) => current || firstSongId)
        }
    }, [firstSongId])
    useEffect(() => {
        if (firstVideoId) {
            setVideoId((current) => current || firstVideoId)
        }
    }, [firstVideoId])

    // Eagerly fetch the cheap poster image for completed jobs so the card shows an
    // instant "mock" of the render; the heavy MP4 only loads when the user hits play.
    useEffect(() => {
        if (!api) {
            return
        }
        const controller = new AbortController()
        for (const job of jobs) {
            const posterRef = job.render_poster
            if (job.status !== "completed" || !posterRef) {
                continue
            }
            if (posterRequested.current.has(job.run_id)) {
                continue
            }
            posterRequested.current.add(job.run_id)
            void api
                .getDownloadUrl(posterRef, controller.signal)
                .then((res) => setPosterUrls((cur) => ({ ...cur, [job.run_id]: res.download_url })))
                .catch(() => posterRequested.current.delete(job.run_id))
        }
        return () => controller.abort()
    }, [api, jobs])

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

    useRunStream({
        api,
        enabled: hasActiveJobs,
        shouldRefresh: isEditPipelineUpdate,
        refresh: jobsResource.revalidate,
    })

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
            setJobs((current = []) => [job, ...current.filter((item) => item.run_id !== job.run_id)])
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
            setJobs((current = []) => current.map((item) => item.run_id === next.run_id ? next : item))
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
            setJobs((current = []) => current.filter((item) => item.run_id !== job.run_id))
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
            setJobs((current = []) => [next, ...current])
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
                    <button className={styles.secondaryButton} type="button" onClick={refreshDashboard} disabled={isLoading || isCreating}>
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
                    {(error || loadError) && <div className={styles.errorBanner}>{error || loadError}</div>}
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
                                <span>{exportFormat === "youtube_16_9" ? "1920 x 1080" : "1080 x 1920"}</span>
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
                                    className={exportFormat === "reels_cinematic" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setExportFormat("reels_cinematic")}
                                    disabled={isCreating}
                                >
                                    Reels Cinematic
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
                            <div className={`${styles.cropPreview} ${exportFormat === "youtube_16_9" ? styles.cropPreviewWide : styles.cropPreviewVertical}`}>
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
                    {isLoading && jobs.length === 0 ? (
                        <SkeletonList count={2} />
                    ) : jobs.length === 0 ? (
                        <div className={styles.emptyState}>No edit jobs yet.</div>
                    ) : (
                        <div className={styles.jobList}>
                            {jobsPager.pageItems.map((job) => (
                                <EditJobCard
                                    key={job.run_id}
                                    job={job}
                                    previewUrl={previewUrls[job.run_id]}
                                    posterUrl={posterUrls[job.run_id]}
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
                            <Pager
                                page={jobsPager.page}
                                pageCount={jobsPager.pageCount}
                                onPrev={jobsPager.prev}
                                onNext={jobsPager.next}
                            />
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
    posterUrl,
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
    posterUrl?: string
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
    const now = useTick(isActive)
    const startedMs = Date.parse(job.created_at)
    const elapsedSec =
        isActive && Number.isFinite(startedMs) ? Math.max(0, (now - startedMs) / 1000) : null
    const etaSec = useRenderEta(job, isActive, now)
    const canRedo = job.status === "failed" || job.status === "canceled"
    const canDelete = job.status === "failed" || job.status === "canceled" || job.status === "completed"
    return (
        <article className={styles.jobCard}>
            <div className={styles.cardTop}>
                <div>
                    <h3>{job.title}</h3>
                    <p className={styles.smallText}>{formatDate(job.updated_at)}</p>
                </div>
                <StatusBadge label={job.status} tone={job.status} />
            </div>
            <div className={styles.progressHeader}>
                <span>{job.progress_percent}%</span>
                {isActive && elapsedSec !== null ? (
                    <span>
                        {formatElapsed(elapsedSec)} elapsed
                        {etaSec !== null ? ` · ~${formatElapsed(etaSec)} left` : ""}
                    </span>
                ) : (
                    <span>{job.status}</span>
                )}
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
            {previewUrl ? (
                <video
                    className={styles.previewMedia}
                    controls
                    autoPlay
                    preload="auto"
                    poster={posterUrl}
                    src={previewUrl}
                />
            ) : posterUrl && isComplete ? (
                <button
                    type="button"
                    className={styles.posterButton}
                    onClick={onPreview}
                    aria-label={`Play ${job.title}`}
                >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img className={styles.previewMedia} src={posterUrl} alt={`${job.title} preview`} />
                    <span className={styles.posterPlayIcon}>
                        <Play size={28} />
                    </span>
                </button>
            ) : null}
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

function useTick(active: boolean) {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        if (!active) {
            return
        }
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [active])
    return now
}

type StageTiming = {
    id: string
    status: EditJobStage["status"]
    percent: number
    startMs: number | null
    durationSec: number | null
}

// Pure: remaining seconds = time left in the running stage + expected time for
// not-yet-started stages. Stage-local rate keeps it accurate within a stage (e.g.
// render's frame encode), so it never inherits the inflated cross-stage average.
function estimateRemainingSec(stages: StageTiming[], nowMs: number): number | null {
    // Calibrate the run total from stages that actually ran (skip reused/instant ones).
    let calibratedSec = 0
    let calibratedWeight = 0
    for (const stage of stages) {
        const weight = EDIT_STAGE_WEIGHTS[stage.id] ?? 0
        if (stage.durationSec !== null && stage.durationSec >= ETA_MIN_CALIBRATION_SEC && weight > 0) {
            calibratedSec += stage.durationSec
            calibratedWeight += weight
        }
    }
    const totalSec = calibratedWeight > 0 ? calibratedSec / calibratedWeight : ETA_DEFAULT_TOTAL_SEC

    let remaining = 0
    let hasOutstanding = false
    for (const stage of stages) {
        if (stage.status === "completed" || stage.status === "failed" || stage.status === "canceled") {
            continue
        }
        hasOutstanding = true
        const weight = EDIT_STAGE_WEIGHTS[stage.id] ?? 0
        if (stage.status === "running") {
            const elapsedInStage = stage.startMs !== null ? Math.max(0, (nowMs - stage.startMs) / 1000) : 0
            if (stage.percent >= ETA_LOCAL_RATE_MIN_PCT && stage.startMs !== null) {
                remaining += (elapsedInStage * (100 - stage.percent)) / stage.percent
            } else {
                remaining += Math.max(0, weight * totalSec - elapsedInStage)
            }
        } else {
            // pending — not started yet
            remaining += weight * totalSec
        }
    }
    return hasOutstanding ? remaining : null
}

type EtaState = {
    sig: string
    starts: Record<string, number>
    durations: Record<string, number>
    anchorEtaSec: number | null
    anchorNowMs: number
}

function emptyEtaState(nowMs: number): EtaState {
    return { sig: "inactive", starts: {}, durations: {}, anchorEtaSec: null, anchorNowMs: nowMs }
}

function stageSignature(job: EditJobStatus): string {
    return job.stages.map((stage) => `${stage.id}:${stage.status}:${stage.percent}`).join("|")
}

// Re-anchor when real progress arrives: record each stage's first-seen start and
// completion duration, recompute the estimate, and ease the anchor toward it (EMA).
// Between updates the displayed value just counts down from the anchor (see useRenderEta),
// so it never rises on a bare clock tick.
function nextEtaState(prev: EtaState, job: EditJobStatus, nowMs: number, sig: string): EtaState {
    const starts = { ...prev.starts }
    const durations = { ...prev.durations }
    const stages: StageTiming[] = job.stages.map((stage) => {
        if ((stage.status === "running" || stage.percent > 0) && starts[stage.id] === undefined) {
            starts[stage.id] = nowMs
        }
        if (stage.status === "completed" && durations[stage.id] === undefined) {
            durations[stage.id] =
                starts[stage.id] !== undefined ? Math.max(0, (nowMs - starts[stage.id]) / 1000) : 0
        }
        return {
            id: stage.id,
            status: stage.status,
            percent: stage.percent,
            startMs: starts[stage.id] ?? null,
            durationSec: durations[stage.id] ?? null,
        }
    })

    const raw = estimateRemainingSec(stages, nowMs)
    let anchorEtaSec = prev.anchorEtaSec
    if (raw !== null) {
        const shownNow =
            prev.anchorEtaSec === null
                ? null
                : Math.max(0, prev.anchorEtaSec - (nowMs - prev.anchorNowMs) / 1000)
        anchorEtaSec = shownNow === null ? raw : shownNow + ETA_SMOOTHING * (raw - shownNow)
    }
    return { sig, starts, durations, anchorEtaSec, anchorNowMs: nowMs }
}

// Phase-aware "time left". Stages carry no timestamps, so timing is tracked locally;
// state is adjusted during render only when the stage signature changes (the
// React-endorsed "store info from previous renders" pattern), and the shown value is
// derived purely from the anchor + elapsed so it counts down smoothly between updates.
function useRenderEta(job: EditJobStatus, isActive: boolean, nowMs: number): number | null {
    const [state, setState] = useState<EtaState>(() => emptyEtaState(nowMs))

    const sig = isActive ? stageSignature(job) : "inactive"
    if (sig !== state.sig) {
        setState((prev) => (isActive ? nextEtaState(prev, job, nowMs, sig) : emptyEtaState(nowMs)))
    }

    if (!isActive || state.anchorEtaSec === null) {
        return null
    }
    return Math.max(0, state.anchorEtaSec - (nowMs - state.anchorNowMs) / 1000)
}

function formatElapsed(totalSec: number) {
    const seconds = Math.max(0, Math.round(totalSec))
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    return `${minutes}m ${seconds % 60}s`
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

function isEditPipelineUpdate(message: RunStreamMessage) {
    if (message.type === "run_manifest") {
        return message.run.workflow_type === "edit_pipeline"
    }
    return message.type === "run_event" && message.event.event_type === "progress"
}
