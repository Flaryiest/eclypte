"use client"

import { useMemo, useRef, useState } from "react"
import type { ChangeEvent, ReactNode } from "react"
import { useUser } from "@clerk/nextjs"
import styles from "./page.module.css"
import {
    EclypteApiClient,
    FileVersionInput,
    RunManifest,
    sha256File,
    uploadToPresignedUrl,
} from "@/services/eclypteApi"

type StageId =
    | "uploadAudio"
    | "uploadVideo"
    | "musicAnalysis"
    | "videoAnalysis"
    | "timeline"
    | "render"
    | "result"

type StageStatus = "pending" | "active" | "complete" | "failed"

type StageState = {
    label: string
    status: StageStatus
    detail: string
}

type UploadedVersion = {
    file_id: string
    version_id: string
}

const STAGE_ORDER: StageId[] = [
    "uploadAudio",
    "uploadVideo",
    "musicAnalysis",
    "videoAnalysis",
    "timeline",
    "render",
    "result",
]

const STAGE_LABELS: Record<StageId, string> = {
    uploadAudio: "Song upload",
    uploadVideo: "Source upload",
    musicAnalysis: "Music analysis",
    videoAnalysis: "Video analysis",
    timeline: "Timeline plan",
    render: "Render",
    result: "Output",
}

const POLL_INTERVAL_MS = 3000

export default function Dashboard() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [audioFile, setAudioFile] = useState<File | null>(null)
    const [videoFile, setVideoFile] = useState<File | null>(null)
    const [audioError, setAudioError] = useState<string | null>(null)
    const [videoError, setVideoError] = useState<string | null>(null)
    const [stages, setStages] = useState<Record<StageId, StageState>>(createInitialStages)
    const [isRunning, setIsRunning] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
    const [renderRef, setRenderRef] = useState<FileVersionInput | null>(null)
    const abortRef = useRef<AbortController | null>(null)

    const api = useMemo(() => {
        if (!user?.id) {
            return null
        }
        return new EclypteApiClient({ userId: user.id })
    }, [user?.id])

    const canStart =
        Boolean(api && audioFile && videoFile && !audioError && !videoError) && !isRunning

    const onAudioChange = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0] ?? null
        setAudioFile(file)
        setAudioError(validateFile(file, "audio"))
        setDownloadUrl(null)
        setRenderRef(null)
        setError(null)
    }

    const onVideoChange = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0] ?? null
        setVideoFile(file)
        setVideoError(validateFile(file, "video"))
        setDownloadUrl(null)
        setRenderRef(null)
        setError(null)
    }

    const resetSession = () => {
        abortRef.current?.abort()
        abortRef.current = null
        setIsRunning(false)
        setError(null)
        setDownloadUrl(null)
        setRenderRef(null)
        setStages(createInitialStages())
    }

    const startPipeline = async () => {
        if (!api || !audioFile || !videoFile || !canStart) {
            return
        }

        const controller = new AbortController()
        abortRef.current = controller
        setIsRunning(true)
        setError(null)
        setDownloadUrl(null)
        setRenderRef(null)
        setStages(createInitialStages())

        try {
            const [audio, sourceVideo] = await Promise.all([
                uploadFile({
                    api,
                    file: audioFile,
                    kind: "song_audio",
                    contentType: "audio/wav",
                    stageId: "uploadAudio",
                    signal: controller.signal,
                    setStage,
                }),
                uploadFile({
                    api,
                    file: videoFile,
                    kind: "source_video",
                    contentType: "video/mp4",
                    stageId: "uploadVideo",
                    signal: controller.signal,
                    setStage,
                }),
            ])

            setStage("musicAnalysis", "active", "Starting Modal music analysis")
            setStage("videoAnalysis", "active", "Starting Modal video analysis")
            const [musicStarted, videoStarted] = await Promise.all([
                api.createMusicAnalysis(audio, controller.signal),
                api.createVideoAnalysis(sourceVideo, controller.signal),
            ])
            const [musicRun, videoRun] = await Promise.all([
                waitForRun(
                    api,
                    musicStarted,
                    "musicAnalysis",
                    controller.signal,
                    setStage,
                ),
                waitForRun(
                    api,
                    videoStarted,
                    "videoAnalysis",
                    controller.signal,
                    setStage,
                ),
            ])

            const musicAnalysis = outputRef(
                musicRun,
                "music_analysis_file_id",
                "music_analysis_version_id",
                "music analysis",
            )
            const videoAnalysis = outputRef(
                videoRun,
                "video_analysis_file_id",
                "video_analysis_version_id",
                "video analysis",
            )

            setStage("timeline", "active", "Planning beat-aligned edit")
            const timelineRun = await waitForRun(
                api,
                await api.createTimelinePlan(
                    { audio, sourceVideo, musicAnalysis, videoAnalysis },
                    controller.signal,
                ),
                "timeline",
                controller.signal,
                setStage,
            )
            const timeline = outputRef(
                timelineRun,
                "timeline_file_id",
                "timeline_version_id",
                "timeline",
            )

            setStage("render", "active", "Rendering MP4")
            const renderRun = await waitForRun(
                api,
                await api.createRender({ timeline, audio, sourceVideo }, controller.signal),
                "render",
                controller.signal,
                setStage,
            )
            const rendered = outputRef(
                renderRun,
                "render_output_file_id",
                "render_output_version_id",
                "render output",
            )
            const result = await api.getDownloadUrl(rendered, controller.signal)
            setRenderRef(rendered)
            setDownloadUrl(result.download_url)
            setStage("result", "complete", "Rendered AMV is ready")
        } catch (caught) {
            if (isAbortError(caught)) {
                return
            }
            const message = errorMessage(caught)
            setError(message)
            failActiveStage(message)
            controller.abort()
        } finally {
            if (abortRef.current === controller) {
                abortRef.current = null
            }
            setIsRunning(false)
        }
    }

    const setStage = (stageId: StageId, status: StageStatus, detail: string) => {
        setStages((current) => ({
            ...current,
            [stageId]: {
                ...current[stageId],
                status,
                detail,
            },
        }))
    }

    const failActiveStage = (detail: string) => {
        setStages((current) => {
            const active = STAGE_ORDER.find((stageId) => current[stageId].status === "active")
            if (!active) {
                return current
            }
            return {
                ...current,
                [active]: {
                    ...current[active],
                    status: "failed",
                    detail,
                },
            }
        })
    }

    if (!isLoaded) {
        return <DashboardShell title="Preparing dashboard" />
    }

    if (!isSignedIn || !user) {
        return (
            <DashboardShell title="Sign in required">
                <p className={styles.muted}>Sign in from the homepage to create a new AMV.</p>
            </DashboardShell>
        )
    }

    return (
        <DashboardShell
            title="New edit"
            eyebrow="Upload-to-render pipeline"
            action={
                <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canStart}
                    onClick={startPipeline}
                >
                    {isRunning ? "Creating AMV" : "Create AMV"}
                </button>
            }
        >
            <section className={styles.workspace}>
                <div className={styles.uploadPanel}>
                    <FilePicker
                        id="song-upload"
                        title="Song"
                        accept="audio/wav,.wav"
                        helper="WAV audio"
                        file={audioFile}
                        error={audioError}
                        disabled={isRunning}
                        onChange={onAudioChange}
                    />
                    <FilePicker
                        id="video-upload"
                        title="Source video"
                        accept="video/mp4,.mp4"
                        helper="MP4 video"
                        file={videoFile}
                        error={videoError}
                        disabled={isRunning}
                        onChange={onVideoChange}
                    />
                </div>

                <div className={styles.progressPanel}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Pipeline</h2>
                            <p>{isRunning ? "Running" : downloadUrl ? "Complete" : "Ready"}</p>
                        </div>
                        {(error || downloadUrl || isRunning) && (
                            <button
                                type="button"
                                className={styles.secondaryButton}
                                onClick={resetSession}
                            >
                                Start over
                            </button>
                        )}
                    </div>

                    {error && (
                        <div className={styles.errorBanner} role="alert">
                            {error}
                        </div>
                    )}

                    <ol className={styles.stageList}>
                        {STAGE_ORDER.map((stageId) => (
                            <li
                                key={stageId}
                                className={`${styles.stageItem} ${styles[stages[stageId].status]}`}
                            >
                                <span className={styles.stageDot} aria-hidden />
                                <div>
                                    <span className={styles.stageLabel}>{stages[stageId].label}</span>
                                    <span className={styles.stageDetail}>{stages[stageId].detail}</span>
                                </div>
                            </li>
                        ))}
                    </ol>
                </div>
            </section>

            {downloadUrl && (
                <section className={styles.resultPanel}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Rendered output</h2>
                            <p>{renderRef ? `${renderRef.file_id} / ${renderRef.version_id}` : "Ready"}</p>
                        </div>
                        <a className={styles.primaryLink} href={downloadUrl}>
                            Download MP4
                        </a>
                    </div>
                    <video className={styles.previewVideo} controls src={downloadUrl} />
                </section>
            )}
        </DashboardShell>
    )
}

function DashboardShell({
    title,
    eyebrow,
    action,
    children,
}: {
    title: string
    eyebrow?: string
    action?: ReactNode
    children?: ReactNode
}) {
    return (
        <main className={styles.page}>
            <header className={styles.header}>
                <div>
                    {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
                    <h1>{title}</h1>
                </div>
                {action}
            </header>
            {children}
        </main>
    )
}

function FilePicker({
    id,
    title,
    accept,
    helper,
    file,
    error,
    disabled,
    onChange,
}: {
    id: string
    title: string
    accept: string
    helper: string
    file: File | null
    error: string | null
    disabled: boolean
    onChange: (event: ChangeEvent<HTMLInputElement>) => void
}) {
    return (
        <label className={`${styles.filePicker} ${error ? styles.filePickerError : ""}`} htmlFor={id}>
            <span className={styles.fileTitle}>{title}</span>
            <span className={styles.fileHelper}>{helper}</span>
            <span className={styles.fileName}>{file ? file.name : "Choose file"}</span>
            {file && <span className={styles.fileMeta}>{formatBytes(file.size)}</span>}
            {error && <span className={styles.fileError}>{error}</span>}
            <input
                id={id}
                type="file"
                accept={accept}
                disabled={disabled}
                onChange={onChange}
            />
        </label>
    )
}

async function uploadFile({
    api,
    file,
    kind,
    contentType,
    stageId,
    signal,
    setStage,
}: {
    api: EclypteApiClient
    file: File
    kind: "song_audio" | "source_video"
    contentType: "audio/wav" | "video/mp4"
    stageId: StageId
    signal: AbortSignal
    setStage: (stageId: StageId, status: StageStatus, detail: string) => void
}): Promise<UploadedVersion> {
    setStage(stageId, "active", "Preparing upload")
    const [reservation, sha256] = await Promise.all([
        api.createUpload(
            {
                kind,
                filename: file.name,
                content_type: contentType,
                size_bytes: file.size,
            },
            signal,
        ),
        sha256File(file),
    ])

    setStage(stageId, "active", "Uploading to storage")
    await uploadToPresignedUrl(reservation.upload_url, file, reservation.required_headers, signal)

    setStage(stageId, "active", "Completing upload")
    const completed = await api.completeUpload(reservation.upload_id, sha256, signal)
    setStage(stageId, "complete", `${completed.original_filename} uploaded`)
    return {
        file_id: reservation.file_id,
        version_id: reservation.version_id,
    }
}

async function waitForRun(
    api: EclypteApiClient,
    initialRun: RunManifest,
    stageId: StageId,
    signal: AbortSignal,
    setStage: (stageId: StageId, status: StageStatus, detail: string) => void,
): Promise<RunManifest> {
    let run = initialRun
    setStage(stageId, "active", runDetail(run))

    while (run.status === "created" || run.status === "running" || run.status === "blocked") {
        await delay(POLL_INTERVAL_MS, signal)
        run = await api.getRun(run.run_id, signal)
        setStage(stageId, "active", runDetail(run))
    }

    if (run.status === "failed") {
        throw new Error(run.last_error || `${STAGE_LABELS[stageId]} failed`)
    }

    setStage(stageId, "complete", `${STAGE_LABELS[stageId]} complete`)
    return run
}

function outputRef(
    run: RunManifest,
    fileKey: string,
    versionKey: string,
    label: string,
): FileVersionInput {
    const fileId = run.outputs[fileKey]
    const versionId = run.outputs[versionKey]
    if (!fileId || !versionId) {
        throw new Error(`Completed ${label} run did not return an output file`)
    }
    return {
        file_id: fileId,
        version_id: versionId,
    }
}

function createInitialStages(): Record<StageId, StageState> {
    return STAGE_ORDER.reduce((acc, stageId) => {
        acc[stageId] = {
            label: STAGE_LABELS[stageId],
            status: "pending",
            detail: "Waiting",
        }
        return acc
    }, {} as Record<StageId, StageState>)
}

function validateFile(file: File | null, kind: "audio" | "video") {
    if (!file) {
        return null
    }

    const extension = file.name.toLowerCase().split(".").pop()
    if (kind === "audio" && file.type !== "audio/wav" && extension !== "wav") {
        return "Use a WAV file."
    }
    if (kind === "video" && file.type !== "video/mp4" && extension !== "mp4") {
        return "Use an MP4 file."
    }
    return null
}

function runDetail(run: RunManifest) {
    if (run.current_step) {
        return `${run.run_id} - ${run.current_step}`
    }
    return run.run_id
}

function delay(ms: number, signal: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(resolve, ms)
        signal.addEventListener(
            "abort",
            () => {
                window.clearTimeout(timeout)
                reject(new DOMException("Aborted", "AbortError"))
            },
            { once: true },
        )
    })
}

function isAbortError(value: unknown) {
    return value instanceof DOMException && value.name === "AbortError"
}

function errorMessage(value: unknown) {
    if (value instanceof Error) {
        return value.message
    }
    return "Something went wrong while creating the AMV."
}

function formatBytes(bytes: number) {
    if (bytes < 1024) {
        return `${bytes} B`
    }
    const units = ["KB", "MB", "GB"]
    let value = bytes / 1024
    let unitIndex = 0
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024
        unitIndex += 1
    }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`
}
