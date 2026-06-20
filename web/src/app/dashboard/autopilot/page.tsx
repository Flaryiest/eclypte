"use client"

import { useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Bot, Pause, Play, Plus, RefreshCw, Trash2, Zap } from "lucide-react"
import { DashboardPage, StatusBadge, errorMessage, formatDate, isAbortError, useAbortableLoad } from "../dashboardCommon"
import styles from "../studio.module.css"
import { useRunStream } from "../useRunStream"
import {
    AssetSummary,
    AutopilotItem,
    AutopilotItemStatus,
    AutopilotStatus,
    EclypteApiClient,
    RunStreamMessage,
} from "@/services/eclypteApi"

type SongMode = "asset" | "youtube"

export default function AutopilotPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [autopilot, setAutopilot] = useState<AutopilotStatus | null>(null)
    const [videos, setVideos] = useState<AssetSummary[]>([])
    const [songs, setSongs] = useState<AssetSummary[]>([])
    const [selectedVideoId, setSelectedVideoId] = useState("")
    const [songMode, setSongMode] = useState<SongMode>("asset")
    const [selectedSongId, setSelectedSongId] = useState("")
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [brief, setBrief] = useState("")
    const [status, setStatus] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isAdding, setIsAdding] = useState(false)
    const [isTicking, setIsTicking] = useState(false)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])

    const loadAutopilot = useAbortableLoad(async (signal) => {
        if (!api) {
            return
        }
        setError(null)
        try {
            const [nextStatus, nextVideos, nextSongs] = await Promise.all([
                api.getAutopilot(signal),
                api.listAssets("source_video", signal),
                api.listAssets("song_audio", signal),
            ])
            setAutopilot(nextStatus)
            setVideos(nextVideos)
            setSongs(nextSongs)
        } catch (caught) {
            if (isAbortError(caught)) {
                return
            }
            setError(errorMessage(caught))
        }
    })

    useEffect(() => {
        loadAutopilot()
    }, [api, loadAutopilot])

    const hasInFlight = (autopilot?.in_flight ?? 0) > 0
    useRunStream({
        api,
        enabled: hasInFlight,
        shouldRefresh: isAutopilotRunUpdate,
        refresh: loadAutopilot,
    })

    const updateAutopilot = async (input: { enabled?: boolean; dailyTarget?: number; clearHalt?: boolean }) => {
        if (!api) {
            return
        }
        setError(null)
        try {
            setAutopilot(await api.updateAutopilot(input))
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }

    const addItem = async () => {
        if (!api || !selectedVideoId) {
            setError("Pick a source video first.")
            return
        }
        const video = videos.find((asset) => asset.file_id === selectedVideoId)
        if (!video?.current_version_id) {
            setError("Selected video has no current version.")
            return
        }
        const song = songMode === "asset" ? songs.find((asset) => asset.file_id === selectedSongId) : null
        if (songMode === "asset" && !song?.current_version_id) {
            setError("Pick a song asset, or switch to a YouTube link.")
            return
        }
        if (songMode === "youtube" && !youtubeUrl.trim()) {
            setError("Paste a YouTube song link, or switch to a song asset.")
            return
        }
        setIsAdding(true)
        setError(null)
        try {
            const next = await api.addAutopilotItems([
                {
                    source_video: { file_id: video.file_id, version_id: video.current_version_id },
                    song: song?.current_version_id
                        ? { file_id: song.file_id, version_id: song.current_version_id }
                        : null,
                    song_youtube_url: songMode === "youtube" ? youtubeUrl.trim() : null,
                    creative_brief: brief.trim(),
                },
            ])
            setAutopilot(next)
            setYoutubeUrl("")
            setBrief("")
            setStatus("Added to the autopilot queue")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsAdding(false)
        }
    }

    const removeItem = async (itemId: string) => {
        if (!api) {
            return
        }
        setError(null)
        try {
            setAutopilot(await api.removeAutopilotItem(itemId))
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }

    const runTick = async () => {
        if (!api) {
            return
        }
        setIsTicking(true)
        setError(null)
        setStatus("Running autopilot tick")
        try {
            setAutopilot(await api.triggerAutopilotTick())
            setStatus("Tick complete")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsTicking(false)
        }
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="Autopilot" title="Loading autopilot"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Autopilot" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to manage autopilot.</div>
            </DashboardPage>
        )
    }

    const assetName = (fileId: string | null, assets: AssetSummary[]) =>
        assets.find((asset) => asset.file_id === fileId)?.display_name ?? fileId ?? "—"

    return (
        <DashboardPage
            eyebrow="Autopilot"
            title="Content autopilot"
            subtitle="Stock the backlog; autopilot imports, edits, and packages reels for your approval on the publish page."
            action={
                <>
                    <button className={styles.ghostButton} type="button" onClick={loadAutopilot}>
                        <RefreshCw size={16} /> Refresh
                    </button>
                    <button className={styles.secondaryButton} type="button" onClick={runTick} disabled={isTicking}>
                        <Zap size={16} /> {isTicking ? "Ticking" : "Run tick now"}
                    </button>
                </>
            }
        >
            {(error || status) && (
                <div className={styles.fieldStack}>
                    {status && !error && <div className={styles.successBanner}>{status}</div>}
                    {error && <div className={styles.errorBanner}>{error}</div>}
                </div>
            )}

            {autopilot?.halted_reason && (
                <div className={styles.fieldStack}>
                    <div className={styles.errorBanner}>
                        {autopilot.halted_reason}
                        <button
                            className={`${styles.secondaryButton} ${styles.haltClearButton}`}
                            type="button"
                            onClick={() => updateAutopilot({ clearHalt: true })}
                        >
                            Clear halt
                        </button>
                    </div>
                </div>
            )}

            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Status</h2>
                            <p>Last tick: {autopilot?.last_tick_at ? formatDate(autopilot.last_tick_at) : "never"}</p>
                        </div>
                        <StatusBadge
                            label={autopilot?.enabled ? "enabled" : "paused"}
                            tone={autopilot?.enabled ? "completed" : undefined}
                        />
                    </div>
                    <div className={styles.fieldStack}>
                        <p className={styles.smallText}>
                            Packaged today: {autopilot?.packaged_today ?? 0} / {autopilot?.daily_target ?? 3}
                            {" · "}In flight: {autopilot?.in_flight ?? 0}
                            {" · "}Pending: {autopilot?.pending ?? 0}
                        </p>
                        <label className={styles.fieldLabel}>
                            Daily target
                            <select
                                className={styles.input}
                                value={autopilot?.daily_target ?? 3}
                                onChange={(event) => updateAutopilot({ dailyTarget: Number(event.target.value) })}
                            >
                                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((value) => (
                                    <option key={value} value={value}>{value} per day</option>
                                ))}
                            </select>
                        </label>
                        <button
                            className={autopilot?.enabled ? styles.secondaryButton : styles.primaryButton}
                            type="button"
                            onClick={() => updateAutopilot({ enabled: !autopilot?.enabled })}
                        >
                            {autopilot?.enabled ? <Pause size={16} /> : <Play size={16} />}
                            {autopilot?.enabled ? "Pause autopilot" : "Enable autopilot"}
                        </button>
                        {!autopilot?.loop_configured && (
                            <p className={styles.smallText}>
                                The API is not running the background loop (set ECLYPTE_AUTOPILOT=1 on the server).
                                Until then, use Run tick now to advance the queue.
                            </p>
                        )}
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Add to backlog</h2>
                            <p>Pair a saved video with a song asset or a YouTube link.</p>
                        </div>
                    </div>
                    <div className={styles.fieldStack}>
                        <label className={styles.fieldLabel}>
                            Source video
                            <select
                                className={styles.input}
                                value={selectedVideoId}
                                onChange={(event) => setSelectedVideoId(event.target.value)}
                            >
                                <option value="">Select a video…</option>
                                {videos.map((asset) => (
                                    <option key={asset.file_id} value={asset.file_id}>{asset.display_name}</option>
                                ))}
                            </select>
                        </label>
                        <label className={styles.fieldLabel}>
                            Song source
                            <select
                                className={styles.input}
                                value={songMode}
                                onChange={(event) => setSongMode(event.target.value as SongMode)}
                            >
                                <option value="asset">Use a saved song asset</option>
                                <option value="youtube">Import from YouTube</option>
                            </select>
                        </label>
                        {songMode === "asset" ? (
                            <label className={styles.fieldLabel}>
                                Song asset
                                <select
                                    className={styles.input}
                                    value={selectedSongId}
                                    onChange={(event) => setSelectedSongId(event.target.value)}
                                >
                                    <option value="">Select a song…</option>
                                    {songs.map((asset) => (
                                        <option key={asset.file_id} value={asset.file_id}>{asset.display_name}</option>
                                    ))}
                                </select>
                            </label>
                        ) : (
                            <label className={styles.fieldLabel}>
                                YouTube song link
                                <input
                                    className={styles.input}
                                    placeholder="https://youtu.be/…"
                                    value={youtubeUrl}
                                    onChange={(event) => setYoutubeUrl(event.target.value)}
                                />
                            </label>
                        )}
                        <label className={styles.fieldLabel}>
                            Creative brief (optional)
                            <textarea
                                className={styles.textarea}
                                placeholder="Open on the most impactful shot, lean into the chorus…"
                                value={brief}
                                onChange={(event) => setBrief(event.target.value)}
                            />
                        </label>
                        <button className={styles.primaryButton} type="button" onClick={addItem} disabled={isAdding}>
                            <Plus size={16} /> {isAdding ? "Adding" : "Add to queue"}
                        </button>
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.full}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Queue &amp; activity</h2>
                            <p>{autopilot?.items.length ?? 0} items</p>
                        </div>
                        <Bot size={18} aria-hidden />
                    </div>
                    {!autopilot || autopilot.items.length === 0 ? (
                        <div className={styles.emptyState}>
                            The backlog is empty. Add a video + song pair above to give autopilot something to make.
                        </div>
                    ) : (
                        <ul className={styles.referenceList}>
                            {autopilot.items.map((item) => (
                                <li className={styles.listCard} key={item.item_id}>
                                    <div className={styles.cardTop}>
                                        <div>
                                            <h3>
                                                {assetName(item.source_video_file_id, videos)}
                                                {" × "}
                                                {item.song_file_id
                                                    ? assetName(item.song_file_id, songs)
                                                    : item.song_youtube_url || "song"}
                                            </h3>
                                            <p className={styles.smallText}>
                                                {itemDetail(item)} · {formatDate(item.updated_at)}
                                            </p>
                                        </div>
                                        <StatusBadge label={item.status} tone={itemTone(item.status)} />
                                    </div>
                                    {item.last_error && <div className={styles.errorBanner}>{item.last_error}</div>}
                                    <div className={styles.cardActions}>
                                        {item.status === "packaged" && (
                                            <a className={styles.secondaryButton} href="/dashboard/publish">
                                                Review on publish page
                                            </a>
                                        )}
                                        {(item.status === "pending" || item.status === "failed") && (
                                            <button
                                                className={styles.ghostButton}
                                                type="button"
                                                onClick={() => removeItem(item.item_id)}
                                            >
                                                <Trash2 size={16} /> Remove
                                            </button>
                                        )}
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </section>
        </DashboardPage>
    )
}

function isAutopilotRunUpdate(message: RunStreamMessage) {
    return (
        message.type === "run_manifest"
        && (message.run.workflow_type === "edit_pipeline" || message.run.workflow_type === "youtube_song_import")
    )
}

function itemTone(status: AutopilotItemStatus) {
    if (status === "importing" || status === "analyzing" || status === "editing") {
        return "running" as const
    }
    if (status === "packaged") {
        return "completed" as const
    }
    if (status === "failed") {
        return "failed" as const
    }
    return undefined
}

function itemDetail(item: AutopilotItem) {
    if (item.status === "editing" && item.audio_start_sec !== null && item.audio_end_sec !== null) {
        return `editing ${item.audio_start_sec.toFixed(0)}s–${item.audio_end_sec.toFixed(0)}s window`
    }
    if (item.status === "packaged") {
        return "package ready for review"
    }
    if (item.status === "importing") {
        return "importing song from YouTube"
    }
    if (item.status === "analyzing") {
        return "analyzing song audio"
    }
    if (item.creative_brief) {
        return item.creative_brief
    }
    return item.status
}
