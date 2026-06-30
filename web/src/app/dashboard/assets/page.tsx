"use client"

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Activity, Download, Link2, RefreshCw, RotateCcw, Trash2, Upload } from "lucide-react"
import {
    DashboardPage,
    Pager,
    SkeletonList,
    StatusBadge,
    errorMessage,
    formatBytes,
    formatDate,
    isAbortError,
    kindLabel,
    usePagination,
    versionRef,
} from "../dashboardCommon"
import { useAssets } from "@/stores/dashboardResources"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
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
type Disclosure = "upload" | "youtube" | null
type LibraryTab = "source" | "derived" | "hidden"
type KindFilter = "all" | "song" | "source"

const LIBRARY_PAGE_SIZE = 24

export default function AssetsPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [activeTab, setActiveTab] = useState<LibraryTab>("source")
    const [kindFilter, setKindFilter] = useState<KindFilter>("all")
    const [file, setFile] = useState<File | null>(null)
    const [slot, setSlot] = useState<UploadSlot>("audio")
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [status, setStatus] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [preview, setPreview] = useState<PreviewState | null>(null)
    const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
    const [openDisclosure, setOpenDisclosure] = useState<Disclosure>(null)
    const [isUploading, setIsUploading] = useState(false)
    const [isImporting, setIsImporting] = useState(false)
    const [busyAssetId, setBusyAssetId] = useState<string | null>(null)
    const [downloadingId, setDownloadingId] = useState<string | null>(null)
    const [deletingId, setDeletingId] = useState<string | null>(null)
    const [restoringId, setRestoringId] = useState<string | null>(null)
    const abortRef = useRef<AbortController | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const assetsResource = useAssets(api, { includeArchived: true })
    const assets = assetsResource.data ?? []
    const setAssets = assetsResource.set
    const loadAssets = assetsResource.revalidate
    const loadError = assetsResource.error
    const sourceAssets = assets.filter((asset) => !asset.archived_at && isSourceKind(asset.kind))
    const derivedAssets = assets.filter((asset) => !asset.archived_at && !isSourceKind(asset.kind) && asset.kind !== "render_output")
    const hiddenAssets = assets.filter((asset) => Boolean(asset.archived_at))
    const tabAssets = activeTab === "source" ? sourceAssets : activeTab === "derived" ? derivedAssets : hiddenAssets
    // The Songs/Sources kind filter only applies to the Sources tab (where the two
    // primary kinds live); Derived/Hidden ignore it.
    const visibleAssets =
        activeTab === "source" && kindFilter !== "all"
            ? tabAssets.filter((asset) => asset.kind === (kindFilter === "song" ? "song_audio" : "source_video"))
            : tabAssets
    const assetPager = usePagination(visibleAssets, LIBRARY_PAGE_SIZE, `${activeTab}:${kindFilter}`)
    const isWorking = isUploading || isImporting
    const selectedAsset = selectedFileId ? visibleAssets.find((asset) => asset.file_id === selectedFileId) ?? null : null

    useEffect(() => {
        return () => abortRef.current?.abort()
    }, [])

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
            const isAudio = slot === "audio"
            const extension = file.name.toLowerCase().split(".").pop() ?? ""
            const isWav = file.type === "audio/wav" || extension === "wav"
            const contentType = isAudio ? file.type || "application/octet-stream" : "video/mp4"
            const uploaded = await uploadAsset(api, {
                file,
                kind: isAudio ? "song_audio" : "source_video",
                contentType,
                signal: controller.signal,
                onStatus: setStatus,
            })
            if (isAudio && !isWav) {
                // Non-WAV audio is converted server-side into a WAV song_audio asset.
                setStatus("Converting to WAV")
                const run = await api.createAudioConversion(uploaded, controller.signal)
                await waitForRunCompletion(api, run, {
                    signal: controller.signal,
                    onUpdate: (next) =>
                        setStatus(next.status === "failed" ? "Conversion failed" : "Converting to WAV"),
                })
                setStatus("Converted to WAV")
            } else {
                setStatus("Upload complete")
            }
            setFile(null)
            loadAssets()
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
            setActiveTab("source")
            loadAssets()
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
            loadAssets()
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

    const selectAsset = (asset: AssetSummary) => {
        setSelectedFileId(asset.file_id)
        if (preview && preview.asset.file_id !== asset.file_id) {
            setPreview(null)
        }
    }

    const downloadAsset = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        const ref = versionRef(asset)
        if (!ref) {
            setError("Asset has no current version.")
            return
        }
        setDownloadingId(asset.file_id)
        setError(null)
        try {
            const downloadUrl = (await api.getDownloadUrl(ref)).download_url
            await downloadSignedUrl({
                url: downloadUrl,
                filename: safeDownloadFilename(asset.current_version?.original_filename || asset.display_name, "eclypte-asset"),
            })
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDownloadingId(null)
        }
    }

    const deleteAsset = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        setDeletingId(asset.file_id)
        setError(null)
        try {
            await api.deleteAsset(asset.file_id)
            setStatus(`${asset.display_name} removed from the library`)
            if (selectedFileId === asset.file_id) {
                setSelectedFileId(null)
                setPreview(null)
            }
            // Soft delete (archive): move it to the Hidden lane in place instead of
            // re-pulling the whole library.
            setAssets((current = []) =>
                current.map((item) =>
                    item.file_id === asset.file_id
                        ? {
                              ...item,
                              archived_at: new Date().toISOString(),
                              archived_reason: item.archived_reason ?? "archived",
                          }
                        : item,
                ),
            )
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setDeletingId(null)
        }
    }

    const restoreAsset = async (asset: AssetSummary) => {
        if (!api) {
            return
        }
        setRestoringId(asset.file_id)
        setError(null)
        try {
            const restored = await api.restoreAsset(asset.file_id)
            setStatus(`${asset.display_name} restored`)
            setActiveTab(isSourceKind(asset.kind) ? "source" : "derived")
            setAssets((current = []) =>
                current.map((item) => (item.file_id === restored.file_id ? restored : item)),
            )
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setRestoringId(null)
        }
    }

    const toggleDisclosure = (next: Disclosure) => {
        setOpenDisclosure((current) => (current === next ? null : next))
    }

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Library" title="Loading assets">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Library" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to manage assets.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Library"
            title="Your library"
            subtitle="Upload songs and source videos once, then reuse them across every edit."
            action={
                <>
                    <button
                        className={openDisclosure === "upload" ? styles.primaryButton : styles.secondaryButton}
                        type="button"
                        onClick={() => toggleDisclosure("upload")}
                        aria-expanded={openDisclosure === "upload"}
                    >
                        <Upload size={16} /> Upload
                    </button>
                    <button
                        className={openDisclosure === "youtube" ? styles.primaryButton : styles.secondaryButton}
                        type="button"
                        onClick={() => toggleDisclosure("youtube")}
                        aria-expanded={openDisclosure === "youtube"}
                    >
                        <Link2 size={16} /> YouTube
                    </button>
                    <button className={styles.ghostButton} type="button" onClick={loadAssets}>
                        <RefreshCw size={16} /> Refresh
                    </button>
                </>
            }
        >
            {(error || loadError || status) && (
                <div className={styles.fieldStack}>
                    {status && <div className={styles.successBanner}>{status}</div>}
                    {(error || loadError) && <div className={styles.errorBanner}>{error || loadError}</div>}
                </div>
            )}

            {openDisclosure === "upload" && (
                <div className={`${styles.panel} ${styles.full}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Upload</h2>
                            <p>Your uploads are saved to your library for reuse.</p>
                        </div>
                    </div>
                    <div className={styles.fieldStack}>
                        <label className={styles.fieldLabel}>
                            Asset type
                            <select className={styles.select} value={slot} onChange={(event) => onSlotChange(event.target.value as UploadSlot)}>
                                <option value="audio">Song</option>
                                <option value="video">Source video</option>
                            </select>
                        </label>
                        <label className={styles.filePicker}>
                            <span className={styles.fileName}>{file ? file.name : "Choose a file"}</span>
                            <span className={styles.muted}>{slot === "audio" ? "Any common audio file works (WAV, MP3, M4A, FLAC…)" : "MP4 video"}</span>
                            {file && <span className={styles.smallText}>{formatBytes(file.size)}</span>}
                            <input type="file" accept={slot === "audio" ? AUDIO_UPLOAD_ACCEPT : "video/mp4,.mp4"} onChange={onFileChange} />
                        </label>
                        <button className={styles.primaryButton} type="button" onClick={uploadSelected} disabled={!file || Boolean(validateUpload(file, slot)) || isWorking}>
                            <Upload size={16} /> {isUploading ? "Uploading" : "Upload asset"}
                        </button>
                    </div>
                </div>
            )}

            {openDisclosure === "youtube" && (
                <div className={`${styles.panel} ${styles.full}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Import from YouTube</h2>
                            <p>We&apos;ll grab the audio and analyze it for you automatically.</p>
                        </div>
                    </div>
                    <div className={styles.fieldStack}>
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
                            className={styles.primaryButton}
                            type="button"
                            onClick={importYouTubeSong}
                            disabled={!youtubeUrl.trim() || isWorking}
                        >
                            <Link2 size={16} /> {isImporting ? "Importing" : "Import and analyze"}
                        </button>
                    </div>
                </div>
            )}

            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Library</h2>
                            <p>{visibleAssets.length} asset{visibleAssets.length === 1 ? "" : "s"}</p>
                        </div>
                        <div className={styles.segmentedControl} role="tablist" aria-label="Library">
                            <button
                                className={activeTab === "source" ? styles.segmentActive : styles.segmentButton}
                                type="button"
                                onClick={() => {
                                    setActiveTab("source")
                                    setSelectedFileId(null)
                                }}
                            >
                                Sources ({sourceAssets.length})
                            </button>
                            <button
                                className={activeTab === "derived" ? styles.segmentActive : styles.segmentButton}
                                type="button"
                                onClick={() => {
                                    setActiveTab("derived")
                                    setSelectedFileId(null)
                                }}
                            >
                                Generated ({derivedAssets.length})
                            </button>
                            <button
                                className={activeTab === "hidden" ? styles.segmentActive : styles.segmentButton}
                                type="button"
                                onClick={() => {
                                    setActiveTab("hidden")
                                    setSelectedFileId(null)
                                }}
                            >
                                Hidden ({hiddenAssets.length})
                            </button>
                        </div>
                    </div>
                    {activeTab === "source" && (
                        <div className={styles.libraryFilters}>
                            <span className={styles.libraryFilterLabel}>Kind</span>
                            <select
                                className={`${styles.select} ${styles.libraryFilterSelect}`}
                                value={kindFilter}
                                onChange={(event) => setKindFilter(event.target.value as KindFilter)}
                                aria-label="Filter by kind"
                            >
                                <option value="all">All</option>
                                <option value="song">Songs</option>
                                <option value="source">Sources</option>
                            </select>
                        </div>
                    )}
                    {visibleAssets.length === 0 ? (
                        <div className={styles.emptyState}>{emptyAssetMessage(activeTab)}</div>
                    ) : (
                        <div className={styles.assetTable}>
                            <div className={styles.assetTableHeader}>
                                <span>Name</span>
                                <span>Kind</span>
                                <span>Size</span>
                                <span>Updated</span>
                                <span>Status</span>
                            </div>
                            {assetPager.pageItems.map((asset) => {
                                const state = assetState(asset)
                                const isSelected = selectedFileId === asset.file_id
                                return (
                                    <button
                                        type="button"
                                        key={asset.file_id}
                                        className={`${styles.assetRow} ${isSelected ? styles.assetRowSelected : ""}`}
                                        onClick={() => selectAsset(asset)}
                                    >
                                        <span className={styles.assetRowName}>
                                            <span className={styles.assetRowTitle}>{asset.display_name}</span>
                                        </span>
                                        <span className={styles.assetRowCell}>{kindLabel(asset.kind)}</span>
                                        <span className={styles.assetRowCellNumeral}>{formatBytes(asset.current_version?.size_bytes)}</span>
                                        <span className={styles.assetRowCell}>{formatDate(asset.updated_at)}</span>
                                        <span><StatusBadge label={state} tone={state} /></span>
                                    </button>
                                )
                            })}
                            <Pager
                                page={assetPager.page}
                                pageCount={assetPager.pageCount}
                                onPrev={assetPager.prev}
                                onNext={assetPager.next}
                            />
                        </div>
                    )}
                </div>

                <div className={`${styles.detailPanel} ${styles.side}`}>
                    {!selectedAsset ? (
                        <div className={styles.detailEmpty}>Select an asset to preview, analyze, or download.</div>
                    ) : (
                        <AssetDetail
                            asset={selectedAsset}
                            preview={preview && preview.asset.file_id === selectedAsset.file_id ? preview : null}
                            isAnalyzing={busyAssetId === selectedAsset.file_id}
                            isDownloading={downloadingId === selectedAsset.file_id}
                            onAnalyze={() => analyzeAsset(selectedAsset)}
                            onPreview={() => openPreview(selectedAsset)}
                            onDownload={() => downloadAsset(selectedAsset)}
                            onDelete={() => deleteAsset(selectedAsset)}
                            onRestore={() => restoreAsset(selectedAsset)}
                            isDeleting={deletingId === selectedAsset.file_id}
                            isRestoring={restoringId === selectedAsset.file_id}
                        />
                    )}
                </div>
            </section>
        </DashboardPage>
    )
}

function AssetDetail({
    asset,
    preview,
    isAnalyzing,
    isDownloading,
    isDeleting,
    isRestoring,
    onAnalyze,
    onPreview,
    onDownload,
    onDelete,
    onRestore,
}: {
    asset: AssetSummary
    preview: PreviewState | null
    isAnalyzing: boolean
    isDownloading: boolean
    isDeleting: boolean
    isRestoring: boolean
    onAnalyze: () => void
    onPreview: () => void
    onDownload: () => void
    onDelete: () => void
    onRestore: () => void
}) {
    const state = assetState(asset)
    const isArchived = Boolean(asset.archived_at)
    const canAnalyze = (asset.kind === "song_audio" || asset.kind === "source_video") && !asset.analysis && !isArchived
    const contentType = asset.current_version?.content_type || ""
    const isAudio = contentType.startsWith("audio/")
    const isVideo = contentType.startsWith("video/")

    return (
        <>
            <div className={styles.cardTop}>
                <div>
                    <h3 className={styles.detailTitle}>{asset.display_name}</h3>
                    <p className={styles.smallText}>
                        {kindLabel(asset.kind)} · {formatBytes(asset.current_version?.size_bytes)} · {formatDate(asset.updated_at)}
                    </p>
                </div>
                <StatusBadge label={state} tone={state} />
            </div>

            {preview ? (
                <>
                    {isAudio && <audio className={styles.previewMedia} controls src={preview.url} />}
                    {isVideo && <video className={styles.previewMedia} controls src={preview.url} />}
                    {!isAudio && !isVideo && (
                        <div className={styles.emptyState}>No preview — download to view.</div>
                    )}
                    <p className={styles.smallText}>Presigned URLs expire; refresh preview if playback stops.</p>
                </>
            ) : (
                <p className={styles.smallText}>Preview to play this asset inline, or download to save it locally.</p>
            )}

            <div className={styles.cardActions}>
                {canAnalyze && state !== "analyzing" && state !== "ready" && (
                    <button className={styles.secondaryButton} type="button" onClick={onAnalyze} disabled={isAnalyzing}>
                        <Activity size={16} /> {isAnalyzing ? "Analyzing" : "Analyze"}
                    </button>
                )}
                {asset.current_version_id && !preview && !isArchived && (
                    <button className={styles.secondaryButton} type="button" onClick={onPreview}>
                        <Download size={16} /> Preview
                    </button>
                )}
                {asset.current_version_id && !isArchived && (
                    <button className={styles.primaryButton} type="button" onClick={onDownload} disabled={isDownloading}>
                        <Download size={16} /> {isDownloading ? "Downloading" : "Download"}
                    </button>
                )}
                {isArchived ? (
                    <button className={styles.secondaryButton} type="button" onClick={onRestore} disabled={isRestoring}>
                        <RotateCcw size={16} /> {isRestoring ? "Restoring" : "Restore"}
                    </button>
                ) : (
                    <button className={styles.dangerButton} type="button" onClick={onDelete} disabled={isDeleting}>
                        <Trash2 size={16} /> {isDeleting ? "Deleting" : "Delete"}
                    </button>
                )}
            </div>
        </>
    )
}

const AUDIO_UPLOAD_EXTENSIONS = ["wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "aiff", "wma"]
const AUDIO_UPLOAD_ACCEPT = `audio/*,${AUDIO_UPLOAD_EXTENSIONS.map((ext) => `.${ext}`).join(",")}`

function validateUpload(file: File | null, slot: UploadSlot) {
    if (!file) {
        return null
    }
    if (file.size <= 0) {
        return "Use a non-empty file."
    }
    const extension = file.name.toLowerCase().split(".").pop() ?? ""
    if (
        slot === "audio" &&
        !file.type.startsWith("audio/") &&
        !AUDIO_UPLOAD_EXTENSIONS.includes(extension)
    ) {
        return "Use an audio file (WAV, MP3, M4A, AAC, FLAC, OGG)."
    }
    if (slot === "video" && file.type !== "video/mp4" && extension !== "mp4") {
        return "Use an MP4 file."
    }
    return null
}

function isSourceKind(kind: ArtifactKind) {
    return kind === "song_audio" || kind === "source_video"
}

function emptyAssetMessage(tab: LibraryTab) {
    if (tab === "source") {
        return "No songs or videos yet — upload one to get started."
    }
    if (tab === "derived") {
        return "Nothing generated yet. Analyses and timelines show up here as you make edits."
    }
    return "Nothing hidden."
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
