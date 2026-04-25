"use client"

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Activity, Download, Link2, RefreshCw, Upload } from "lucide-react"
import {
    DashboardPage,
    StatusBadge,
    formatBytes,
    formatDate,
    kindLabel,
    versionRef,
} from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    ArtifactKind,
    AssetSummary,
    EclypteApiClient,
    assetState,
    uploadAsset,
    waitForRunCompletion,
} from "@/services/eclypteApi"

type UploadSlot = "audio" | "video"
type PreviewState = { asset: AssetSummary; url: string }

export default function AssetsPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [assets, setAssets] = useState<AssetSummary[]>([])
    const [filter, setFilter] = useState<"all" | ArtifactKind>("all")
    const [file, setFile] = useState<File | null>(null)
    const [slot, setSlot] = useState<UploadSlot>("audio")
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [status, setStatus] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [preview, setPreview] = useState<PreviewState | null>(null)
    const [isUploading, setIsUploading] = useState(false)
    const [isImporting, setIsImporting] = useState(false)
    const [busyAssetId, setBusyAssetId] = useState<string | null>(null)
    const abortRef = useRef<AbortController | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const visibleAssets = filter === "all" ? assets : assets.filter((asset) => asset.kind === filter)
    const isWorking = isUploading || isImporting

    const loadAssets = useCallback(async () => {
        if (!api) {
            return
        }
        setError(null)
        try {
            setAssets(await api.listAssets())
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }, [api])

    useEffect(() => {
        void loadAssets()
    }, [loadAssets])

    const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
        const next = event.target.files?.[0] ?? null
        setFile(next)
        setError(validateUpload(next, slot))
        setStatus(null)
    }

    const onSlotChange = (next: UploadSlot) => {
        setSlot(next)
        setError(validateUpload(file, next))
        setStatus(null)
    }

    const uploadSelected = async () => {
        if (!api || !file) {
            return
        }
        const validation = validateUpload(file, slot)
        if (validation) {
            setError(validation)
            return
        }
        const controller = new AbortController()
        abortRef.current = controller
        setError(null)
        setIsUploading(true)
        try {
            await uploadAsset(api, {
                file,
                kind: slot === "audio" ? "song_audio" : "source_video",
                contentType: slot === "audio" ? "audio/wav" : "video/mp4",
                signal: controller.signal,
                onStatus: setStatus,
            })
            setStatus("Upload complete")
            setFile(null)
            await loadAssets()
        } catch (caught) {
            if (!isAbortError(caught)) {
                setError(errorMessage(caught))
            }
        } finally {
            abortRef.current = null
            setIsUploading(false)
        }
    }

    const importYouTubeSong = async () => {
        if (!api) {
            return
        }
        const validation = validateYouTubeUrl(youtubeUrl)
        if (validation) {
            setError(validation)
            return
        }
        const controller = new AbortController()
        abortRef.current = controller
        setError(null)
        setIsImporting(true)
        try {
            setStatus("Starting YouTube import")
            const run = await api.createYouTubeSongImport(youtubeUrl.trim(), controller.signal)
            await waitForRunCompletion(api, run, {
                signal: controller.signal,
                onUpdate: (next) => setStatus(formatYouTubeImportStatus(next.status)),
            })
            setStatus("YouTube song imported and analyzed")
            setYoutubeUrl("")
            setFilter("song_audio")
            await loadAssets()
        } catch (caught) {
            if (!isAbortError(caught)) {
                setError(errorMessage(caught))
            }
        } finally {
            abortRef.current = null
            setIsImporting(false)
        }
    }

    const analyzeAsset = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Asset has no current version.")
            return
        }
        setBusyAssetId(asset.file_id)
        setError(null)
        setStatus(null)
        try {
            const run = asset.kind === "song_audio"
                ? await api.createMusicAnalysis(ref)
                : await api.createVideoAnalysis(ref)
            await waitForRunCompletion(api, run, {
                onUpdate: (next) => setStatus(`Analysis ${next.status}`),
            })
            setStatus("Analysis complete")
            await loadAssets()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setBusyAssetId(null)
        }
    }

    const openPreview = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            return
        }
        const download = await api.getDownloadUrl(ref)
        setPreview({ asset, url: download.download_url })
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="Assets" title="Loading assets"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Assets" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to manage assets.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Assets"
            title="Asset library"
            subtitle="Upload reusable WAV songs and MP4 source videos, then analyze them once for future edits."
            action={
                <button className={styles.secondaryButton} type="button" onClick={loadAssets}>
                    <RefreshCw size={16} /> Refresh
                </button>
            }
        >
            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Upload</h2>
                            <p>Assets persist in R2 and can be reused after refresh.</p>
                        </div>
                    </div>
                    <div className={styles.fieldStack}>
                        <label className={styles.fieldLabel}>
                            Asset type
                            <select className={styles.select} value={slot} onChange={(event) => onSlotChange(event.target.value as UploadSlot)}>
                                <option value="audio">WAV song</option>
                                <option value="video">MP4 source video</option>
                            </select>
                        </label>
                        <label className={styles.filePicker}>
                            <span className={styles.fileName}>{file ? file.name : "Choose file"}</span>
                            <span className={styles.muted}>{slot === "audio" ? "audio/wav" : "video/mp4"}</span>
                            {file && <span className={styles.smallText}>{formatBytes(file.size)}</span>}
                            <input type="file" accept={slot === "audio" ? "audio/wav,.wav" : "video/mp4,.mp4"} onChange={onFileChange} />
                        </label>
                        <button className={styles.primaryButton} type="button" onClick={uploadSelected} disabled={!file || Boolean(validateUpload(file, slot)) || isWorking}>
                            <Upload size={16} /> {isUploading ? "Uploading" : "Upload asset"}
                        </button>
                        <label className={styles.fieldLabel}>
                            YouTube song URL
                            <input
                                className={styles.input}
                                type="url"
                                value={youtubeUrl}
                                placeholder="https://www.youtube.com/watch?v=..."
                                onChange={(event) => {
                                    setYoutubeUrl(event.target.value)
                                    setError(null)
                                    setStatus(null)
                                }}
                            />
                        </label>
                        <button
                            className={styles.secondaryButton}
                            type="button"
                            onClick={importYouTubeSong}
                            disabled={!youtubeUrl.trim() || isWorking}
                        >
                            <Link2 size={16} /> {isImporting ? "Importing" : "Import and analyze"}
                        </button>
                        {status && <div className={styles.successBanner}>{status}</div>}
                        {error && <div className={styles.errorBanner}>{error}</div>}
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Library</h2>
                            <p>{visibleAssets.length} asset{visibleAssets.length === 1 ? "" : "s"}</p>
                        </div>
                        <select className={styles.select} value={filter} onChange={(event) => setFilter(event.target.value as "all" | ArtifactKind)}>
                            <option value="all">All assets</option>
                            <option value="song_audio">Songs</option>
                            <option value="source_video">Videos</option>
                            <option value="music_analysis">Music analyses</option>
                            <option value="video_analysis">Video analyses</option>
                            <option value="timeline">Timelines</option>
                            <option value="render_output">Renders</option>
                        </select>
                    </div>
                    {visibleAssets.length === 0 ? (
                        <div className={styles.emptyState}>No assets yet.</div>
                    ) : (
                        <div className={styles.assetGrid}>
                            {visibleAssets.map((asset) => {
                                const state = assetState(asset)
                                const canAnalyze = (asset.kind === "song_audio" || asset.kind === "source_video") && !asset.analysis
                                return (
                                    <article className={styles.assetCard} key={asset.file_id}>
                                        <div className={styles.cardTop}>
                                            <div>
                                                <h3>{asset.display_name}</h3>
                                                <p className={styles.smallText}>
                                                    {kindLabel(asset.kind)} - {formatBytes(asset.current_version?.size_bytes)} - {formatDate(asset.updated_at)}
                                                </p>
                                            </div>
                                            <StatusBadge label={state} tone={state} />
                                        </div>
                                        <div className={styles.cardActions}>
                                            {canAnalyze && state !== "analyzing" && state !== "ready" && (
                                                <button className={styles.secondaryButton} type="button" onClick={() => analyzeAsset(asset)} disabled={busyAssetId === asset.file_id}>
                                                    <Activity size={16} /> {busyAssetId === asset.file_id ? "Analyzing" : "Analyze"}
                                                </button>
                                            )}
                                            {asset.current_version_id && (
                                                <button className={styles.ghostButton} type="button" onClick={() => openPreview(asset)}>
                                                    <Download size={16} /> Preview
                                                </button>
                                            )}
                                        </div>
                                    </article>
                                )
                            })}
                        </div>
                    )}
                </div>

                {preview && <AssetPreview preview={preview} />}
            </section>
        </DashboardPage>
    )
}

function AssetPreview({ preview }: { preview: PreviewState }) {
    const contentType = preview.asset.current_version?.content_type || ""
    const isAudio = contentType.startsWith("audio/")
    const isVideo = contentType.startsWith("video/")

    return (
        <div className={`${styles.panel} ${styles.full}`}>
            <div className={styles.panelHeader}>
                <div>
                    <h2>Preview</h2>
                    <p>Presigned URLs expire; refresh preview if playback stops.</p>
                </div>
                <a className={styles.primaryButton} href={preview.url}>Download</a>
            </div>
            {isAudio && <audio className={styles.previewMedia} controls src={preview.url} />}
            {isVideo && <video className={styles.previewMedia} controls src={preview.url} />}
            {!isAudio && !isVideo && (
                <div className={styles.emptyState}>This artifact can be downloaded, but it does not have an inline media preview.</div>
            )}
        </div>
    )
}

function validateUpload(file: File | null, slot: UploadSlot) {
    if (!file) {
        return null
    }
    const extension = file.name.toLowerCase().split(".").pop()
    if (slot === "audio" && file.type !== "audio/wav" && extension !== "wav") {
        return "Use a WAV file."
    }
    if (slot === "video" && file.type !== "video/mp4" && extension !== "mp4") {
        return "Use an MP4 file."
    }
    return null
}

function validateYouTubeUrl(value: string) {
    try {
        const url = new URL(value.trim())
        const host = url.hostname.toLowerCase()
        if (
            (url.protocol === "http:" || url.protocol === "https:") &&
            (host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com"))
        ) {
            return null
        }
    } catch {
        return "Use a valid YouTube URL."
    }
    return "Use a valid YouTube URL."
}

function formatYouTubeImportStatus(status: string) {
    if (status === "completed") {
        return "YouTube song imported and analyzed"
    }
    if (status === "failed") {
        return "YouTube import failed"
    }
    return `YouTube import ${status}`
}

function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
