"use client"

import { ChangeEvent, Suspense, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useUser } from "@clerk/nextjs"
import { Activity, Download, Link2, Music, Plus, RotateCcw, Send, Trash2 } from "lucide-react"
import {
    DashboardPage,
    Pager,
    Sheet,
    SkeletonList,
    Spinner,
    errorMessage,
    formatBytes,
    formatDate,
    isAbortError,
    stripExtension,
    usePagination,
    useToast,
    versionRef,
} from "../dashboardCommon"
import { assetPosterUrl, stableMediaUrl } from "../posterUrls"
import styles from "../studio.module.css"
import { downloadSignedUrl, safeDownloadFilename } from "@/services/downloadFile"
import {
    AssetSummary,
    EclypteApiClient,
    PublishingPost,
    assetState,
    uploadAsset,
    waitForRunCompletion,
} from "@/services/eclypteApi"
import { useAssets, usePublishingPosts } from "@/stores/dashboardResources"

type LibraryTab = "films" | "songs" | "reels" | "hidden"
type UploadCard = { id: number; name: string; loaded: number; total: number; stage: string; error: string | null }
type ImportCard = { url: string; stage: string; error: string | null }

const AUDIO_UPLOAD_EXTENSIONS = ["wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "aiff", "wma"]

export default function AssetsPage() {
    return (
        <Suspense fallback={<SkeletonList count={3} />}>
            <LibraryPage />
        </Suspense>
    )
}

function LibraryPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const router = useRouter()
    const searchParams = useSearchParams()
    const toast = useToast()
    const tabParam = searchParams.get("tab")
    const tab: LibraryTab = tabParam === "songs" || tabParam === "reels" || tabParam === "hidden" ? tabParam : "films"
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [addOpen, setAddOpen] = useState(false)
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [uploads, setUploads] = useState<UploadCard[]>([])
    const [imports, setImports] = useState<ImportCard[]>([])
    const [error, setError] = useState<string | null>(null)
    const uploadIdRef = useRef(0)
    const uploadControllersRef = useRef<Map<number, AbortController>>(new Map())
    const importControllersRef = useRef<Map<string, AbortController>>(new Map())

    useEffect(
        () => () => {
            uploadControllersRef.current.forEach((controller) => controller.abort())
            importControllersRef.current.forEach((controller) => controller.abort())
        },
        [],
    )

    const api = useMemo(() => (user?.id ? new EclypteApiClient({ userId: user.id }) : null), [user?.id])
    const assetsResource = useAssets(api, { includeArchived: true })
    const assets = useMemo(() => assetsResource.data ?? [], [assetsResource.data])
    const setAssets = assetsResource.set
    const reelsResource = useAssets(api, { kind: "render_output" })
    const reels = useMemo(() => reelsResource.data ?? [], [reelsResource.data])
    const postsResource = usePublishingPosts(api, { status: "all" })
    const posts = useMemo(() => postsResource.data ?? [], [postsResource.data])
    const postByRender = useMemo(() => new Map(posts.map((post) => [post.render_file_id, post])), [posts])

    const films = assets.filter((a) => a.kind === "source_video" && a.current_version_id && !a.archived_at)
    const songs = assets.filter((a) => a.kind === "song_audio" && a.current_version_id && !a.archived_at)
    const hidden = assets.filter((a) => Boolean(a.archived_at))
    const tabItems: AssetSummary[] = tab === "films" ? films : tab === "songs" ? songs : tab === "reels" ? reels : hidden
    const pager = usePagination(tabItems, tab === "songs" ? 10 : 12, tab)

    const setTab = (next: LibraryTab) => {
        setSelectedId(null)
        router.replace(next === "films" ? "/dashboard/assets" : `/dashboard/assets?tab=${next}`)
    }

    const selected = selectedId
        ? [...films, ...songs, ...reels, ...hidden].find((a) => a.file_id === selectedId) ?? null
        : null

    // --- Add flow: one smart file input (MP4 → film, audio → song), plus YouTube. ---
    const onPick = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0] ?? null
        event.target.value = ""
        if (!file || !api) {
            return
        }
        const extension = file.name.toLowerCase().split(".").pop() ?? ""
        const isVideo = file.type === "video/mp4" || extension === "mp4"
        const isAudio = file.type.startsWith("audio/") || AUDIO_UPLOAD_EXTENSIONS.includes(extension)
        if (!isVideo && !isAudio) {
            setError("Use an MP4 film or a common audio file (WAV, MP3, M4A, FLAC, OGG).")
            return
        }
        setError(null)
        setAddOpen(false)
        void runUpload(file, isVideo)
    }

    const runUpload = async (file: File, isVideo: boolean) => {
        if (!api) {
            return
        }
        const id = ++uploadIdRef.current
        const controller = new AbortController()
        uploadControllersRef.current.set(id, controller)
        const patch = (partial: Partial<UploadCard>) =>
            setUploads((current) => current.map((card) => (card.id === id ? { ...card, ...partial } : card)))
        setUploads((current) => [
            ...current,
            { id, name: stripExtension(file.name), loaded: 0, total: file.size, stage: "Checking the file", error: null },
        ])
        try {
            const extension = file.name.toLowerCase().split(".").pop() ?? ""
            const isWav = file.type === "audio/wav" || extension === "wav"
            const uploaded = await uploadAsset(api, {
                file,
                kind: isVideo ? "source_video" : "song_audio",
                contentType: isVideo ? "video/mp4" : file.type || "application/octet-stream",
                signal: controller.signal,
                onStatus: (stage) => patch({ stage }),
                onProgress: (loaded) => patch({ loaded, stage: "Uploading" }),
            })
            if (!isVideo && !isWav) {
                patch({ stage: "Converting the audio", loaded: file.size })
                const run = await api.createAudioConversion(uploaded, controller.signal)
                await waitForRunCompletion(api, run, { signal: controller.signal })
            }
            setUploads((current) => current.filter((card) => card.id !== id))
            assetsResource.revalidate()
            toast(`${stripExtension(file.name)} added to your library`)
        } catch (caught) {
            if (isAbortError(caught)) {
                setUploads((current) => current.filter((card) => card.id !== id))
                return
            }
            patch({ error: errorMessage(caught), stage: "Didn't work" })
        } finally {
            uploadControllersRef.current.delete(id)
        }
    }

    const runImport = async () => {
        if (!api || !youtubeUrl.trim()) {
            return
        }
        setError(null)
        const url = youtubeUrl.trim()
        setYoutubeUrl("")
        setAddOpen(false)
        const controller = new AbortController()
        importControllersRef.current.set(url, controller)
        const patch = (partial: Partial<ImportCard>) =>
            setImports((current) => current.map((card) => (card.url === url ? { ...card, ...partial } : card)))
        setImports((current) => [...current, { url, stage: "Getting the song", error: null }])
        try {
            const run = await api.createYouTubeSongImport(url, controller.signal)
            await waitForRunCompletion(api, run, {
                signal: controller.signal,
                onUpdate: (next) => patch({ stage: next.status === "running" ? "Getting the song" : "Finishing up" }),
            })
            setImports((current) => current.filter((card) => card.url !== url))
            if (tab !== "songs") {
                setTab("songs")
            }
            assetsResource.revalidate()
            toast("Song imported and ready")
        } catch (caught) {
            if (isAbortError(caught)) {
                setImports((current) => current.filter((card) => card.url !== url))
                return
            }
            patch({ error: errorMessage(caught), stage: "Didn't work" })
        } finally {
            importControllersRef.current.delete(url)
        }
    }

    // --- Row/card actions (archive keeps the old optimistic cache patch behavior). ---
    const [busyAction, setBusyAction] = useState<string | null>(null)
    const act = async (name: string, action: () => Promise<void>) => {
        setBusyAction(name)
        setError(null)
        try {
            await action()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setBusyAction(null)
        }
    }

    const analyze = (asset: AssetSummary) =>
        act("analyze", async () => {
            const ref = versionRef(asset)
            if (!api || !ref) {
                return
            }
            const run = asset.kind === "song_audio" ? await api.createMusicAnalysis(ref) : await api.createVideoAnalysis(ref)
            assetsResource.revalidate()
            await waitForRunCompletion(api, run)
            assetsResource.revalidate()
            toast("All set — ready to use")
        })

    const download = (asset: AssetSummary) =>
        act("download", async () => {
            const ref = versionRef(asset)
            if (!api || !ref) {
                return
            }
            const downloadUrl = (await api.getDownloadUrl(ref)).download_url
            await downloadSignedUrl({
                url: downloadUrl,
                filename: safeDownloadFilename(asset.current_version?.original_filename || asset.display_name, "eclypte-asset"),
            })
        })

    const hide = (asset: AssetSummary) =>
        act("hide", async () => {
            if (!api) {
                return
            }
            await api.deleteAsset(asset.file_id)
            setSelectedId(null)
            setAssets((current = []) =>
                current.map((item) =>
                    item.file_id === asset.file_id
                        ? { ...item, archived_at: new Date().toISOString(), archived_reason: item.archived_reason ?? "archived" }
                        : item,
                ),
            )
            toast(`${stripExtension(asset.display_name)} hidden`)
        })

    const restore = (asset: AssetSummary) =>
        act("restore", async () => {
            if (!api) {
                return
            }
            const restored = await api.restoreAsset(asset.file_id)
            setAssets((current = []) => current.map((item) => (item.file_id === restored.file_id ? restored : item)))
            toast(`${stripExtension(asset.display_name)} restored`)
        })

    const post = (asset: AssetSummary) =>
        act("post", async () => {
            const ref = versionRef(asset)
            if (!api || !ref) {
                return
            }
            const next = await api.createPublishingPost({ renderOutput: ref })
            postsResource.set((current = []) => [next, ...current])
            toast("Added to Ready for you on Home")
        })

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Library" title="Library">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Library" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to manage your library.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Everything you own"
            title="Library"
            action={
                <button className={styles.primaryButton} type="button" onClick={() => setAddOpen(true)}>
                    <Plus size={16} /> Add
                </button>
            }
        >
            {(error || assetsResource.error) && <div className={styles.errorBanner}>{error || assetsResource.error}</div>}

            <div className={styles.tabPills} role="tablist" aria-label="Library">
                {(["films", "songs", "reels"] as const).map((item) => (
                    <button
                        key={item}
                        type="button"
                        role="tab"
                        aria-selected={tab === item}
                        className={tab === item ? styles.pillActive : styles.pill}
                        onClick={() => setTab(item)}
                    >
                        {item === "films" ? `Films (${films.length})` : item === "songs" ? `Songs (${songs.length})` : `Reels (${reels.length})`}
                    </button>
                ))}
                <button type="button" className={styles.hiddenLink} onClick={() => setTab("hidden")}>
                    Hidden{hidden.length ? ` (${hidden.length})` : ""}
                </button>
            </div>

            {/* In-flight uploads/imports appear at the top of the active view. */}
            {(uploads.length > 0 || imports.length > 0) && (
                <div className={styles.feedSection}>
                    {uploads.map((card) => (
                        <div key={card.id} className={styles.progressRow}>
                            <div className={styles.progressRowTop}>
                                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                                    {!card.error && <Spinner />}
                                    <span className={styles.truncate}>{card.name}</span>
                                </span>
                                <span>
                                    {card.error
                                        ? card.error
                                        : card.stage === "Uploading"
                                            ? `Uploading · ${formatBytes(card.loaded)} of ${formatBytes(card.total)}`
                                            : `${card.stage}…`}
                                </span>
                            </div>
                            {!card.error && card.stage === "Uploading" && (
                                <div className={styles.progressTrack}>
                                    <div className={styles.progressFill} style={{ width: `${Math.min(100, (card.loaded / Math.max(1, card.total)) * 100)}%` }} />
                                </div>
                            )}
                            {!card.error && (
                                <div>
                                    <button className={styles.ghostButton} type="button" onClick={() => uploadControllersRef.current.get(card.id)?.abort()}>
                                        Cancel
                                    </button>
                                </div>
                            )}
                            {card.error && (
                                <div>
                                    <button className={styles.ghostButton} type="button" onClick={() => setUploads((current) => current.filter((item) => item.id !== card.id))}>
                                        Dismiss
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                    {imports.map((card) => (
                        <div key={card.url} className={styles.progressRow}>
                            <div className={styles.progressRowTop}>
                                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                                    {!card.error && <Spinner />}
                                    <span className={styles.truncate}>{card.url}</span>
                                </span>
                                <span>{card.error ?? `${card.stage}…`}</span>
                            </div>
                            {!card.error && (
                                <div>
                                    <button className={styles.ghostButton} type="button" onClick={() => importControllersRef.current.get(card.url)?.abort()}>
                                        Cancel
                                    </button>
                                </div>
                            )}
                            {card.error && (
                                <div>
                                    <button className={styles.ghostButton} type="button" onClick={() => setImports((current) => current.filter((item) => item.url !== card.url))}>
                                        Dismiss
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {tabItems.length === 0 && uploads.length === 0 && imports.length === 0 ? (
                <div className={styles.emptyState}>
                    <p className={styles.emptyStateTitle}>{emptyTitle(tab)}</p>
                    <p className={styles.emptyStateHint}>{emptyHint(tab)}</p>
                </div>
            ) : tab === "songs" ? (
                <div>
                    {pager.pageItems.map((asset) => (
                        <SongRow key={asset.file_id} asset={asset} onOpen={() => setSelectedId(asset.file_id)} />
                    ))}
                    <Pager page={pager.page} pageCount={pager.pageCount} onPrev={pager.prev} onNext={pager.next} />
                </div>
            ) : (
                <>
                    <div className={`${styles.mediaGrid} ${tab === "reels" ? styles.mediaGridTall : ""}`}>
                        {pager.pageItems.map((asset) => (
                            <MediaCard
                                key={asset.file_id}
                                asset={asset}
                                tall={tab === "reels"}
                                posterUrl={assetPosterUrl(asset)}
                                postedLabel={tab === "reels" ? reelPostedLabel(postByRender.get(asset.file_id)) : null}
                                onOpen={() => setSelectedId(asset.file_id)}
                            />
                        ))}
                    </div>
                    <Pager page={pager.page} pageCount={pager.pageCount} onPrev={pager.prev} onNext={pager.next} />
                </>
            )}

            {api && selected && (
                <AssetSheet
                    key={selected.file_id}
                    api={api}
                    asset={selected}
                    posterUrl={assetPosterUrl(selected)}
                    busyAction={busyAction}
                    existingPost={postByRender.get(selected.file_id)}
                    onClose={() => setSelectedId(null)}
                    onAnalyze={() => analyze(selected)}
                    onDownload={() => download(selected)}
                    onHide={() => hide(selected)}
                    onRestore={() => restore(selected)}
                    onPost={() => post(selected)}
                />
            )}

            <Sheet
                open={addOpen}
                title="Add to your library"
                onClose={() => setAddOpen(false)}
                footer={
                    <button className={styles.secondaryButton} type="button" onClick={runImport} disabled={!youtubeUrl.trim()}>
                        <Link2 size={15} /> Import from YouTube
                    </button>
                }
            >
                <label className={`${styles.filePicker} ${styles.uploadDrop}`}>
                    <span className={styles.fileName}>Choose a file</span>
                    <span className={styles.muted}>An MP4 becomes a film; audio (WAV, MP3, M4A, FLAC…) becomes a song.</span>
                    <input type="file" accept={`video/mp4,.mp4,audio/*,${AUDIO_UPLOAD_EXTENSIONS.map((ext) => `.${ext}`).join(",")}`} onChange={onPick} />
                </label>
                <label className={styles.fieldLabel}>
                    Or paste a YouTube song link
                    <input className={styles.input} placeholder="https://youtu.be/…" value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} />
                </label>
            </Sheet>
        </DashboardPage>
    )
}

function assetStatusText(asset: AssetSummary): { text: string; busy: boolean; ok: boolean } {
    if (asset.archived_at) {
        return { text: "Hidden", busy: false, ok: false }
    }
    const state = assetState(asset)
    if (state === "analyzing") {
        return { text: asset.kind === "song_audio" ? "Listening to the song…" : "Getting to know this film…", busy: true, ok: false }
    }
    if (state === "ready") {
        return { text: "Ready to use", busy: false, ok: true }
    }
    if (state === "failed") {
        return { text: "Needs another try", busy: false, ok: false }
    }
    return { text: "Needs a first look", busy: false, ok: false }
}

function MediaCard({
    asset,
    tall,
    posterUrl,
    postedLabel,
    onOpen,
}: {
    asset: AssetSummary
    tall: boolean
    posterUrl?: string
    postedLabel: string | null
    onOpen: () => void
}) {
    const status = assetStatusText(asset)
    return (
        <button type="button" className={styles.mediaCard} onClick={onOpen}>
            <span className={styles.mediaThumbFrame}>
                {posterUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element -- signed R2 URL, next/image can't optimize
                    <img className={`${styles.mediaThumb} ${tall ? styles.mediaThumbTall : ""}`} src={posterUrl} alt="" />
                ) : (
                    <span className={`${styles.mediaThumb} ${tall ? styles.mediaThumbTall : ""}`} aria-hidden />
                )}
                {tall && (
                    <span className={styles.mediaPlayHint} aria-hidden>
                        <span>▶</span>
                    </span>
                )}
            </span>
            <span className={styles.mediaCardBody}>
                <span className={styles.mediaTitle}>{stripExtension(asset.display_name)}</span>
                <span className={styles.mediaMeta}>
                    {postedLabel ?? (
                        <>
                            {status.busy ? <Spinner /> : <span className={styles.statusDotSwatch} style={{ background: status.ok ? "var(--ok)" : "var(--attention)" }} aria-hidden />}
                            {status.text}
                        </>
                    )}
                </span>
            </span>
        </button>
    )
}

function SongRow({ asset, onOpen }: { asset: AssetSummary; onOpen: () => void }) {
    const status = assetStatusText(asset)
    return (
        <button type="button" className={styles.songRow} onClick={onOpen}>
            <span className={styles.songArt} aria-hidden><Music size={16} /></span>
            <span style={{ minWidth: 0 }}>
                <span className={styles.mediaTitle} style={{ display: "block" }}>{stripExtension(asset.display_name)}</span>
                <span className={styles.mediaMeta}>
                    {status.busy ? <Spinner /> : <span className={styles.statusDotSwatch} style={{ background: status.ok ? "var(--ok)" : "var(--attention)" }} aria-hidden />}
                    {status.text}
                </span>
            </span>
        </button>
    )
}

function reelPostedLabel(post: PublishingPost | undefined) {
    if (!post) {
        return "Not posted yet"
    }
    if (post.status === "published") {
        return "On Instagram"
    }
    if (post.status === "queued" || post.status === "scheduled") {
        return "Queued to post"
    }
    return "Not posted yet"
}

function AssetSheet({
    api,
    asset,
    posterUrl,
    busyAction,
    existingPost,
    onClose,
    onAnalyze,
    onDownload,
    onHide,
    onRestore,
    onPost,
}: {
    api: EclypteApiClient
    asset: AssetSummary
    posterUrl?: string
    busyAction: string | null
    existingPost?: PublishingPost
    onClose: () => void
    onAnalyze: () => void
    onDownload: () => void
    onHide: () => void
    onRestore: () => void
    onPost: () => void
}) {
    // Lazy inits instead of effects: the sheet is keyed by file id, so mount-time
    // facts (a cached playback URL, a missing version) are known immediately, and
    // the compiler bans sync setState in effects.
    const [previewUrl, setPreviewUrl] = useState<string | null>(() =>
        asset.current_version_id
            ? stableMediaUrl(`${asset.file_id}:${asset.current_version_id}`, undefined) ?? null
            : null,
    )
    const [previewError, setPreviewError] = useState<string | null>(() =>
        asset.current_version_id ? null : "This file isn't ready to preview yet.",
    )
    const isArchived = Boolean(asset.archived_at)
    const contentType = asset.current_version?.content_type || ""
    // Kind is authoritative (reels/films are always video, songs always audio);
    // content type is only a fallback so odd/missing metadata can't strand the UI.
    const isReel = asset.kind === "render_output"
    const isVideo = isReel || asset.kind === "source_video" || contentType.startsWith("video/")
    const isAudio = !isVideo && (asset.kind === "song_audio" || contentType.startsWith("audio/"))
    const status = assetStatusText(asset)

    // Fetch the signed playback URL as soon as the sheet opens, so the media is
    // ready to play with one tap on the native controls (the old click-the-poster
    // flow was easy to miss and failed silently). The sheet is keyed by file id at
    // the call site, so switching assets remounts and resets this state naturally.
    const previewFileId = asset.file_id
    const previewVersionId = asset.current_version_id
    useEffect(() => {
        if (!previewVersionId || previewUrl) {
            return
        }
        // No cleanup-based ignore flag: the sheet is keyed by file id, so an asset
        // switch remounts (stale setState is a safe no-op), and under Strict Mode a
        // cleanup flag would waste the first fetch's result.
        const timeoutMs = 12000
        const timeout = new Promise<never>((_, reject) => {
            window.setTimeout(() => reject(new Error(`preview request timed out after ${timeoutMs / 1000}s`)), timeoutMs)
        })
        void Promise.race([
            api.getDownloadUrl({ file_id: previewFileId, version_id: previewVersionId }),
            timeout,
        ])
            .then((download) => {
                // Pin in the stability cache so reopening this sheet skips the fetch
                // and the browser reuses its buffered media for the same URL.
                setPreviewUrl(
                    stableMediaUrl(`${previewFileId}:${previewVersionId}`, download.download_url)
                        ?? download.download_url,
                )
            })
            .catch((caught) => {
                setPreviewError(`Preview couldn't load (${errorMessage(caught)}) — Download still works.`)
            })
    }, [api, previewFileId, previewVersionId, previewUrl])
    const canAnalyze = (asset.kind === "song_audio" || asset.kind === "source_video") && !asset.analysis && !isArchived && !status.busy
    // Already-analyzed media can be re-analyzed on demand (e.g. to pick up a
    // thumbnail or credits data added after the original analysis ran).
    const canRefreshAnalysis =
        (asset.kind === "song_audio" || asset.kind === "source_video") && Boolean(asset.analysis) && !isArchived && !status.busy
    const canPost = asset.kind === "render_output" && Boolean(asset.current_version_id) && !existingPost

    return (
        <Sheet
            open
            title={stripExtension(asset.display_name)}
            onClose={onClose}
            footer={
                <>
                    {canPost && (
                        <button className={styles.primaryButton} type="button" onClick={onPost} disabled={busyAction !== null}>
                            {busyAction === "post" ? <Spinner /> : <Send size={15} />} Post this
                        </button>
                    )}
                    {canAnalyze && (
                        <button className={styles.secondaryButton} type="button" onClick={onAnalyze} disabled={busyAction !== null}>
                            {busyAction === "analyze" ? <Spinner /> : <Activity size={15} />} Get it ready
                        </button>
                    )}
                    {canRefreshAnalysis && (
                        <button className={styles.ghostButton} type="button" onClick={onAnalyze} disabled={busyAction !== null}>
                            {busyAction === "analyze" ? <Spinner /> : <Activity size={15} />} Refresh analysis
                        </button>
                    )}
                    <button className={styles.secondaryButton} type="button" onClick={onDownload} disabled={busyAction !== null || !asset.current_version_id}>
                        {busyAction === "download" ? <Spinner /> : <Download size={15} />} Download
                    </button>
                    <span className={styles.sheetActionsRight}>
                        {isArchived ? (
                            <button className={styles.secondaryButton} type="button" onClick={onRestore} disabled={busyAction !== null}>
                                {busyAction === "restore" ? <Spinner /> : <RotateCcw size={15} />} Restore
                            </button>
                        ) : (
                            <button className={styles.dangerButton} type="button" onClick={onHide} disabled={busyAction !== null}>
                                {busyAction === "hide" ? <Spinner /> : <Trash2 size={15} />} Hide
                            </button>
                        )}
                    </span>
                </>
            }
        >
            {previewError ? (
                <p className={styles.smallText} style={{ margin: 0 }}>{previewError}</p>
            ) : isVideo && previewUrl ? (
                <video
                    className={`${styles.previewMedia} ${isReel ? styles.previewMediaTall : ""}`}
                    controls
                    preload="metadata"
                    poster={posterUrl}
                    src={previewUrl}
                    onError={(event) => {
                        const mediaError = event.currentTarget.error
                        setPreviewError(
                            `Playback failed${mediaError ? ` (media error ${mediaError.code})` : ""} — Download still works.`,
                        )
                    }}
                />
            ) : isAudio && previewUrl ? (
                <audio className={styles.previewMedia} controls src={previewUrl} />
            ) : isVideo ? (
                <span className={styles.mediaThumbFrame} style={isReel ? { maxWidth: 240, alignSelf: "center" } : undefined}>
                    {posterUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element -- signed R2 URL, next/image can't optimize
                        <img className={`${styles.mediaThumb} ${isReel ? styles.mediaThumbTall : ""}`} src={posterUrl} alt="" />
                    ) : (
                        <span className={`${styles.mediaThumb} ${isReel ? styles.mediaThumbTall : ""}`} aria-hidden />
                    )}
                    <span className={styles.posterPlayIcon}>
                        <Spinner onInk />
                    </span>
                </span>
            ) : (
                <p className={styles.smallText} style={{ margin: 0 }}>
                    <Spinner /> Getting ready to play…
                </p>
            )}
            <p className={styles.smallText} style={{ margin: 0 }}>
                <span className={status.busy ? "" : ""}>{status.text}</span>
                {" · added "}{formatDate(asset.created_at)}
                {" · "}{formatBytes(asset.current_version?.size_bytes)}
            </p>
            {asset.kind === "render_output" && existingPost && (
                <p className={styles.muted} style={{ margin: 0 }}>{reelPostedLabel(existingPost)}</p>
            )}
        </Sheet>
    )
}

function emptyTitle(tab: LibraryTab) {
    if (tab === "films") return "No films yet"
    if (tab === "songs") return "No songs yet"
    if (tab === "reels") return "No reels yet"
    return "Nothing hidden"
}

function emptyHint(tab: LibraryTab) {
    if (tab === "films") return "Add an MP4 of a film or anime — it becomes the footage your reels are cut from."
    if (tab === "songs") return "Add an audio file or import a song from YouTube."
    if (tab === "reels") return "Finished reels land here automatically."
    return "Things you hide can be restored from here."
}
