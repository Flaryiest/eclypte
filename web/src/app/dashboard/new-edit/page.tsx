"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { RefreshCw, WandSparkles } from "lucide-react"
import { DashboardPage, StatusBadge, formatBytes, kindLabel, versionRef } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    AssetSummary,
    EclypteApiClient,
    FileVersionInput,
    PlanningMode,
    RunManifest,
} from "@/services/eclypteApi"

type StageId = "assets" | "music" | "video" | "timeline" | "render" | "result"
type StageStatus = "pending" | "active" | "complete" | "failed"
type Stage = { label: string; status: StageStatus; detail: string }

const STAGES: StageId[] = ["assets", "music", "video", "timeline", "render", "result"]
const STAGE_LABELS: Record<StageId, string> = {
    assets: "Asset prep",
    music: "Music analysis",
    video: "Video analysis",
    timeline: "Timeline plan",
    render: "Render",
    result: "Result",
}
const POLL_INTERVAL_MS = 3000

export default function NewEditPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [assets, setAssets] = useState<AssetSummary[]>([])
    const [audioId, setAudioId] = useState("")
    const [videoId, setVideoId] = useState("")
    const [planningMode, setPlanningMode] = useState<PlanningMode>("agent")
    const [creativeBrief, setCreativeBrief] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [isRunning, setIsRunning] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
    const [stages, setStages] = useState<Record<StageId, Stage>>(initialStages)
    const abortRef = useRef<AbortController | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const songs = assets.filter((asset) => asset.kind === "song_audio")
    const videos = assets.filter((asset) => asset.kind === "source_video")
    const selectedSong = songs.find((asset) => asset.file_id === audioId) ?? null
    const selectedVideo = videos.find((asset) => asset.file_id === videoId) ?? null
    const selectedAssets = [selectedSong, selectedVideo].filter(
        (asset): asset is AssetSummary => Boolean(asset),
    )
    const canStart = Boolean(api && selectedSong && selectedVideo && !isRunning)

    const loadAssets = useCallback(async () => {
        if (!api) {
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            const next = await api.listAssets()
            setAssets(next)
            setAudioId((current) => current || next.find((asset) => asset.kind === "song_audio")?.file_id || "")
            setVideoId((current) => current || next.find((asset) => asset.kind === "source_video")?.file_id || "")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsLoading(false)
        }
    }, [api])

    useEffect(() => {
        void loadAssets()
    }, [loadAssets])

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

        const controller = new AbortController()
        abortRef.current = controller
        setIsRunning(true)
        setError(null)
        setDownloadUrl(null)
        setStages(initialStages())

        try {
            setStage("assets", "complete", "Selected saved assets")
            const [musicAnalysis, videoAnalysis] = await Promise.all([
                ensureAnalysis({
                    api,
                    asset: selectedSong,
                    source: audio,
                    kind: "music",
                    signal: controller.signal,
                    setStage,
                }),
                ensureAnalysis({
                    api,
                    asset: selectedVideo,
                    source: sourceVideo,
                    kind: "video",
                    signal: controller.signal,
                    setStage,
                }),
            ])

            setStage("timeline", "active", planningMode === "agent" ? "Planning with AI agent" : "Planning beat-aligned edit")
            const timelineRun = await waitForRun(
                api,
                await api.createTimelinePlan(
                    {
                        audio,
                        sourceVideo,
                        musicAnalysis,
                        videoAnalysis,
                        planningMode,
                        creativeBrief: creativeBrief.trim(),
                    },
                    controller.signal,
                ),
                "timeline",
                controller.signal,
                setStage,
            )
            const timeline = outputRef(timelineRun, "timeline_file_id", "timeline_version_id", "timeline")

            setStage("render", "active", "Rendering final MP4")
            const renderRun = await waitForRun(
                api,
                await api.createRender({ timeline, audio, sourceVideo }, controller.signal),
                "render",
                controller.signal,
                setStage,
            )
            const render = outputRef(renderRun, "render_output_file_id", "render_output_version_id", "render")
            const download = await api.getDownloadUrl(render, controller.signal)
            setDownloadUrl(download.download_url)
            setStage("result", "complete", "AMV is ready")
            void loadAssets()
        } catch (caught) {
            if (!isAbortError(caught)) {
                const message = errorMessage(caught)
                setError(message)
                failActiveStage(message)
            }
        } finally {
            if (abortRef.current === controller) {
                abortRef.current = null
            }
            setIsRunning(false)
        }
    }

    const reset = () => {
        abortRef.current?.abort()
        abortRef.current = null
        setIsRunning(false)
        setError(null)
        setDownloadUrl(null)
        setStages(initialStages())
    }

    const setStage = (stageId: StageId, status: StageStatus, detail: string) => {
        setStages((current) => ({
            ...current,
            [stageId]: { ...current[stageId], status, detail },
        }))
    }

    const failActiveStage = (detail: string) => {
        setStages((current) => {
            const active = STAGES.find((stageId) => current[stageId].status === "active")
            if (!active) {
                return current
            }
            return { ...current, [active]: { ...current[active], status: "failed", detail } }
        })
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
            subtitle="Choose saved song and video assets. Existing analyses are reused; missing analyses run automatically."
            action={
                <>
                    <button className={styles.secondaryButton} type="button" onClick={loadAssets} disabled={isLoading || isRunning}>
                        <RefreshCw size={16} /> Refresh
                    </button>
                    <button className={styles.primaryButton} type="button" onClick={startEdit} disabled={!canStart}>
                        <WandSparkles size={16} /> {isRunning ? "Creating" : "Create AMV"}
                    </button>
                </>
            }
        >
            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Asset selection</h2>
                            <p>Use the Assets page to upload more songs and source videos.</p>
                        </div>
                    </div>
                    {error && <div className={styles.errorBanner}>{error}</div>}
                    <div className={styles.fieldStack}>
                        <label className={styles.fieldLabel}>
                            Song asset
                            <select className={styles.select} value={audioId} onChange={(event) => setAudioId(event.target.value)} disabled={isRunning}>
                                <option value="">Choose a WAV song</option>
                                {songs.map((asset) => (
                                    <option key={asset.file_id} value={asset.file_id}>
                                        {asset.display_name} - {formatBytes(asset.current_version?.size_bytes)}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className={styles.fieldLabel}>
                            Source video asset
                            <select className={styles.select} value={videoId} onChange={(event) => setVideoId(event.target.value)} disabled={isRunning}>
                                <option value="">Choose an MP4 video</option>
                                {videos.map((asset) => (
                                    <option key={asset.file_id} value={asset.file_id}>
                                        {asset.display_name} - {formatBytes(asset.current_version?.size_bytes)}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <div className={styles.fieldLabel}>
                            Planning mode
                            <div className={styles.segmentedControl} role="group" aria-label="Planning mode">
                                <button
                                    className={planningMode === "agent" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setPlanningMode("agent")}
                                    disabled={isRunning}
                                >
                                    AI Agent
                                </button>
                                <button
                                    className={planningMode === "deterministic" ? styles.segmentActive : styles.segmentButton}
                                    type="button"
                                    onClick={() => setPlanningMode("deterministic")}
                                    disabled={isRunning}
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
                                    disabled={isRunning}
                                />
                            </label>
                        )}
                    </div>
                    <div className={styles.assetGrid}>
                        {selectedAssets.map((asset) => (
                            <article className={styles.assetCard} key={asset.file_id}>
                                <div className={styles.cardTop}>
                                    <div>
                                        <h3>{asset.display_name}</h3>
                                        <p className={styles.smallText}>{kindLabel(asset.kind)}</p>
                                    </div>
                                    <StatusBadge label={asset.analysis ? "Ready" : "Uploaded"} tone={asset.analysis ? "ready" : "uploaded"} />
                                </div>
                            </article>
                        ))}
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Pipeline</h2>
                            <p>{isRunning ? "Running" : downloadUrl ? "Complete" : "Ready"}</p>
                        </div>
                        {(isRunning || downloadUrl || error) && (
                            <button className={styles.ghostButton} type="button" onClick={reset}>
                                Start over
                            </button>
                        )}
                    </div>
                    <ol className={styles.stageList}>
                        {STAGES.map((stageId) => (
                            <li key={stageId} className={`${styles.stageItem} ${stageClass(stages[stageId].status)}`}>
                                <span className={styles.stageDot} aria-hidden />
                                <div>
                                    <span className={styles.stageLabel}>{stages[stageId].label}</span>
                                    <span className={styles.stageDetail}>{stages[stageId].detail}</span>
                                </div>
                            </li>
                        ))}
                    </ol>
                </div>

                {downloadUrl && (
                    <div className={`${styles.panel} ${styles.full}`}>
                        <div className={styles.panelHeader}>
                            <div>
                                <h2>Rendered output</h2>
                                <p>Your final MP4 is ready for preview and download.</p>
                            </div>
                            <a className={styles.primaryButton} href={downloadUrl}>Download MP4</a>
                        </div>
                        <video className={styles.previewMedia} controls src={downloadUrl} />
                    </div>
                )}
            </section>
        </DashboardPage>
    )
}

async function ensureAnalysis({
    api,
    asset,
    source,
    kind,
    signal,
    setStage,
}: {
    api: EclypteApiClient
    asset: AssetSummary
    source: FileVersionInput
    kind: "music" | "video"
    signal: AbortSignal
    setStage: (stageId: StageId, status: StageStatus, detail: string) => void
}) {
    const stageId = kind
    if (asset.analysis) {
        setStage(stageId, "complete", "Reused existing analysis")
        return asset.analysis
    }
    setStage(stageId, "active", `Starting ${kind} analysis`)
    const started = kind === "music"
        ? await api.createMusicAnalysis(source, signal)
        : await api.createVideoAnalysis(source, signal)
    const completed = await waitForRun(api, started, stageId, signal, setStage)
    return kind === "music"
        ? outputRef(completed, "music_analysis_file_id", "music_analysis_version_id", "music analysis")
        : outputRef(completed, "video_analysis_file_id", "video_analysis_version_id", "video analysis")
}

async function waitForRun(
    api: EclypteApiClient,
    initialRun: RunManifest,
    stageId: StageId,
    signal: AbortSignal,
    setStage: (stageId: StageId, status: StageStatus, detail: string) => void,
) {
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

function outputRef(run: RunManifest, fileKey: string, versionKey: string, label: string) {
    const fileId = run.outputs[fileKey]
    const versionId = run.outputs[versionKey]
    if (!fileId || !versionId) {
        throw new Error(`Completed ${label} run did not return an output file`)
    }
    return { file_id: fileId, version_id: versionId }
}

function initialStages(): Record<StageId, Stage> {
    return STAGES.reduce((acc, stageId) => {
        acc[stageId] = { label: STAGE_LABELS[stageId], status: "pending", detail: "Waiting" }
        return acc
    }, {} as Record<StageId, Stage>)
}

function stageClass(status: StageStatus) {
    if (status === "active") return styles.activeStage
    if (status === "complete") return styles.completeStage
    if (status === "failed") return styles.failedStage
    return ""
}

function runDetail(run: RunManifest) {
    return run.current_step ? `${run.status} - ${run.current_step}` : run.status
}

function delay(ms: number, signal: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(resolve, ms)
        signal.addEventListener("abort", () => {
            window.clearTimeout(timeout)
            reject(new DOMException("Aborted", "AbortError"))
        }, { once: true })
    })
}

function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
