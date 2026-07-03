"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import Link from "next/link"
import { Play, Plus, RefreshCw, Zap } from "lucide-react"
import {
    DashboardPage,
    FadeImg,
    PostedStripSkeleton,
    ProgressRow,
    QueueRowsSkeleton,
    ReviewCardsSkeleton,
    Select,
    Sheet,
    Skeleton,
    SkeletonList,
    Spinner,
    errorMessage,
    formatClock,
    formatDate,
    humanizeStageDetail,
    stripExtension,
    useToast,
} from "./dashboardCommon"
import styles from "./studio.module.css"
import { useRunStream } from "./useRunStream"
import { useNow, useRenderEta } from "./editEta"
import { assetPosterUrl, postPosterUrl, postRenderUrl } from "./posterUrls"
import {
    AssetSummary,
    AutopilotItem,
    EclypteApiClient,
    EditJobStatus,
    PublishingPost,
    RunStreamMessage,
} from "@/services/eclypteApi"
import { useAssets, useAutopilot, useEditJobs, usePublishingPosts } from "@/stores/dashboardResources"

const POLL_INTERVAL_MS = 25000
const POSTED_STRIP_LIMIT = 10

export default function HomePage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const toast = useToast()
    const [error, setError] = useState<string | null>(null)
    const [reviewPostId, setReviewPostId] = useState<string | null>(null)
    const [composerOpen, setComposerOpen] = useState(false)
    const [isTicking, setIsTicking] = useState(false)
    const [isSavingSettings, setIsSavingSettings] = useState(false)
    const [removingItemId, setRemovingItemId] = useState<string | null>(null)
    const pollableIdsRef = useRef<string[]>([])

    const api = useMemo(() => (user?.id ? new EclypteApiClient({ userId: user.id }) : null), [user?.id])
    const autopilotResource = useAutopilot(api)
    const autopilot = autopilotResource.data ?? null
    const setAutopilot = autopilotResource.set
    const postsResource = usePublishingPosts(api, { status: "all" })
    const posts = useMemo(() => postsResource.data ?? [], [postsResource.data])
    const setPosts = postsResource.set
    const jobsResource = useEditJobs(api)
    const jobs = useMemo(() => jobsResource.data ?? [], [jobsResource.data])
    const assetsResource = useAssets(api, { includeArchived: true })
    const assets = useMemo(() => assetsResource.data ?? [], [assetsResource.data])

    const readyPosts = useMemo(() => posts.filter((post) => post.status === "ready" || post.status === "draft"), [posts])
    const postedPosts = useMemo(
        () =>
            posts
                .filter((post) => post.status === "published" || post.status === "queued" || post.status === "scheduled")
                .slice(0, POSTED_STRIP_LIMIT),
        [posts],
    )
    const workingItems = useMemo(
        () => (autopilot?.items ?? []).filter((item) => ["importing", "analyzing", "editing"].includes(item.status)),
        [autopilot],
    )
    const pendingItems = useMemo(() => (autopilot?.items ?? []).filter((item) => item.status === "pending"), [autopilot])
    const failedItems = useMemo(() => (autopilot?.items ?? []).filter((item) => item.status === "failed"), [autopilot])

    const revalidateAll = useMemo(() => {
        const a = autopilotResource.revalidate
        const p = postsResource.revalidate
        const j = jobsResource.revalidate
        return () => {
            a()
            p()
            j()
        }
    }, [autopilotResource.revalidate, postsResource.revalidate, jobsResource.revalidate])

    useRunStream({
        api,
        enabled: workingItems.length > 0,
        shouldRefresh: isPipelineRunUpdate,
        refresh: revalidateAll,
    })

    const assetById = useMemo(() => new Map(assets.map((asset) => [asset.file_id, asset])), [assets])

    // --- Buffer reconciliation (ported behavior contract from the publish page).
    const pollablePosts = useMemo(
        () =>
            posts.filter(
                (post) =>
                    Boolean(post.buffer_post_id)
                    && (post.status === "queued" || post.status === "scheduled" || (post.status === "published" && !post.post_url)),
            ),
        [posts],
    )
    const hasPollable = pollablePosts.length > 0
    useEffect(() => {
        pollableIdsRef.current = pollablePosts.map((post) => post.post_id)
    })
    useEffect(() => {
        if (!api || !hasPollable) {
            return
        }
        const controller = new AbortController()
        let stopped = false
        const reconcile = async () => {
            if (document.visibilityState === "hidden") {
                return
            }
            for (const postId of pollableIdsRef.current) {
                try {
                    const next = await api.refreshPublishingPostStatus(postId, controller.signal)
                    if (stopped) {
                        return
                    }
                    setPosts((current = []) => current.map((post) => (post.post_id === next.post_id ? next : post)))
                } catch {
                    // Silent: background reconciliation must never clobber the UI.
                }
            }
        }
        const interval = window.setInterval(reconcile, POLL_INTERVAL_MS)
        const onVisible = () => {
            if (document.visibilityState === "visible") {
                void reconcile()
            }
        }
        document.addEventListener("visibilitychange", onVisible)
        return () => {
            stopped = true
            controller.abort()
            window.clearInterval(interval)
            document.removeEventListener("visibilitychange", onVisible)
        }
    }, [api, hasPollable, setPosts])

    const replacePost = (next: PublishingPost) => {
        setPosts((current = []) => current.map((post) => (post.post_id === next.post_id ? next : post)))
    }

    const updateSettings = async (input: { enabled?: boolean; dailyTarget?: number; clearHalt?: boolean }) => {
        if (!api) {
            return
        }
        setError(null)
        setIsSavingSettings(true)
        try {
            setAutopilot(await api.updateAutopilot(input))
        } catch (caught) {
            toast(errorMessage(caught), "err")
        } finally {
            setIsSavingSettings(false)
        }
    }

    const runTick = async () => {
        if (!api) {
            return
        }
        setIsTicking(true)
        setError(null)
        try {
            setAutopilot(await api.triggerAutopilotTick())
            toast("Checked the queue")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsTicking(false)
        }
    }

    const removeItem = async (itemId: string) => {
        if (!api) {
            return
        }
        setRemovingItemId(itemId)
        try {
            setAutopilot(await api.removeAutopilotItem(itemId))
        } catch (caught) {
            toast(errorMessage(caught), "err")
        } finally {
            setRemovingItemId(null)
        }
    }

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Home" title="Today">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Home" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to see your reels.</div>
            </DashboardPage>
        )
    }

    const reviewPost = reviewPostId ? posts.find((post) => post.post_id === reviewPostId) ?? null : null
    const madeToday = autopilot?.packaged_today ?? 0
    const target = autopilot?.daily_target ?? 3

    return (
        <DashboardPage
            eyebrow={formatDate(new Date().toISOString())}
            title="Today"
            action={
                <button className={styles.primaryButton} type="button" onClick={() => setComposerOpen(true)}>
                    <Plus size={16} /> New reel
                </button>
            }
        >
            <div className={styles.statusLine}>
                {autopilotResource.isLoading ? (
                    <Skeleton className={styles.skeletonLineShort} />
                ) : (
                    <>
                <span className={autopilot?.enabled ? styles.statusOnDot : styles.statusOffDot} aria-hidden />
                {autopilot?.enabled
                    ? `Autopilot is on · ${madeToday} of ${target} reels made today`
                    : "Autopilot is paused"}
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem", marginLeft: "auto" }}>
                    Daily goal
                    <Select
                        compact
                        ariaLabel="Daily goal"
                        value={String(target)}
                        onChange={(next) => updateSettings({ dailyTarget: Number(next) })}
                        disabled={isSavingSettings}
                        options={Array.from({ length: 10 }, (_, index) => ({
                            value: String(index + 1),
                            label: `${index + 1} per day`,
                        }))}
                    />
                    <button
                        type="button"
                        className={`${styles.switchButton} ${autopilot?.enabled ? styles.switchButtonOn : ""}`}
                        role="switch"
                        aria-checked={Boolean(autopilot?.enabled)}
                        aria-label={autopilot?.enabled ? "Pause autopilot" : "Turn autopilot on"}
                        onClick={() => updateSettings({ enabled: !autopilot?.enabled })}
                        disabled={isSavingSettings}
                    />
                    {!autopilot?.loop_configured && (
                        <button className={styles.ghostButton} type="button" onClick={runTick} disabled={isTicking}>
                            {isTicking ? <Spinner /> : <Zap size={15} />} Run now
                        </button>
                    )}
                    {isSavingSettings && <Spinner />}
                </span>
                    </>
                )}
            </div>

            {autopilot?.halted_reason && (
                <div className={styles.topBanner}>
                    <span className={styles.breakAny}>Autopilot paused itself: {autopilot.halted_reason}</span>
                    <button
                        className={`${styles.secondaryButton} ${styles.haltClearButton}`}
                        type="button"
                        onClick={() => updateSettings({ clearHalt: true })}
                        disabled={isSavingSettings}
                    >
                        {isSavingSettings ? <Spinner /> : <Play size={15} />} Resume
                    </button>
                </div>
            )}
            {(error || autopilotResource.error || postsResource.error) && (
                <div className={styles.errorBanner}>{error || autopilotResource.error || postsResource.error}</div>
            )}

            {/* Ready for you */}
            <section className={styles.feedSection}>
                <div className={styles.feedSectionHead}>
                    <h2 className={styles.feedSectionTitle}>Ready for you</h2>
                    <span className={styles.feedSectionCount}>
                        {postsResource.isLoading ? "…" : readyPosts.length}
                    </span>
                </div>
                {postsResource.isLoading ? (
                    <ReviewCardsSkeleton />
                ) : readyPosts.length === 0 ? (
                    <p className={styles.smallText}>
                        Nothing to review right now — new reels land here when they&apos;re done.
                    </p>
                ) : (
                    <div className={styles.reviewCardGrid}>
                        {readyPosts.map((post) => {
                            const url = postPosterUrl(post)
                            return (
                                <div key={post.post_id} className={styles.reviewCard}>
                                    {url ? (
                                        <FadeImg className={styles.posterThumb} src={url} alt="" />
                                    ) : (
                                        <span className={`${styles.posterThumb} ${styles.posterThumbPlaceholder}`} aria-hidden>▶</span>
                                    )}
                                    <div className={styles.reviewCardBody}>
                                        <h3 style={{ margin: 0 }} className={styles.truncate}>{postTitle(post)}</h3>
                                        <p className={styles.smallText} style={{ margin: 0 }}>
                                            made {formatDate(post.created_at)}
                                            {post.auto_created ? " · by autopilot" : ""}
                                        </p>
                                        <p className={styles.captionPreview}>{post.caption} {post.hashtags.join(" ")}</p>
                                        <div className={styles.cardActions}>
                                            <button className={styles.primaryButton} type="button" onClick={() => setReviewPostId(post.post_id)}>
                                                Review &amp; post
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>

            {/* In the works */}
            {(workingItems.length > 0 || failedItems.length > 0) && (
                <section className={styles.feedSection}>
                    <div className={styles.feedSectionHead}>
                        <h2 className={styles.feedSectionTitle}>In the works</h2>
                        <span className={styles.feedSectionCount}>{workingItems.length}</span>
                    </div>
                    {workingItems.map((item) => (
                        <WorkingRow key={item.item_id} item={item} jobs={jobs} assets={assetById} />
                    ))}
                    {failedItems.map((item) => (
                        <ProgressRow
                            key={item.item_id}
                            title={itemTitle(item, assetById)}
                            stageText="Didn't work"
                            percent={null}
                            error={item.last_error ?? "Something went wrong — remove it below and try again."}
                        />
                    ))}
                </section>
            )}

            {/* Up next */}
            <section className={styles.feedSection}>
                <div className={styles.feedSectionHead}>
                    <h2 className={styles.feedSectionTitle}>Up next</h2>
                    <span className={styles.feedSectionCount}>
                        {autopilotResource.isLoading ? "…" : pendingItems.length + failedItems.length}
                    </span>
                </div>
                {autopilotResource.isLoading ? (
                    <QueueRowsSkeleton />
                ) : pendingItems.length === 0 && failedItems.length === 0 ? (
                    <p className={styles.smallText}>The queue is empty — add a film and a song with “New reel”.</p>
                ) : (
                    <div>
                        {[...pendingItems, ...failedItems].map((item) => {
                            const asset = assetById.get(item.source_video_file_id)
                            const url = asset ? assetPosterUrl(asset) : undefined
                            return (
                                <div key={item.item_id} className={styles.queueRow}>
                                    {url ? (
                                        <FadeImg className={styles.queueThumb} src={url} alt="" loading="lazy" />
                                    ) : (
                                        <span className={styles.queueThumb} aria-hidden />
                                    )}
                                    <span className={styles.truncate}>{itemTitle(item, assetById)}</span>
                                    <span style={{ marginLeft: "auto", display: "inline-flex", gap: "0.6rem", alignItems: "center" }}>
                                        {item.status === "failed" && <span className={styles.smallText} style={{ margin: 0, color: "var(--danger)" }}>didn&apos;t work</span>}
                                        <button
                                            className={styles.ghostButton}
                                            type="button"
                                            onClick={() => removeItem(item.item_id)}
                                            disabled={removingItemId === item.item_id}
                                        >
                                            {removingItemId === item.item_id ? <Spinner /> : null} Remove
                                        </button>
                                    </span>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>

            {/* Posted */}
            <section className={styles.feedSection}>
                <div className={styles.feedSectionHead}>
                    <h2 className={styles.feedSectionTitle}>Posted</h2>
                    <span className={styles.feedSectionCount}>recent</span>
                    <Link className={styles.feedSectionLink} href="/dashboard/assets?tab=reels">
                        See all
                    </Link>
                </div>
                {postsResource.isLoading ? (
                    <PostedStripSkeleton />
                ) : postedPosts.length === 0 ? (
                    <p className={styles.smallText}>Reels you approve show up here once they&apos;re queued or live.</p>
                ) : (
                    <div className={styles.postedStrip}>
                        {postedPosts.map((post) => {
                            const url = postPosterUrl(post)
                            return (
                                <button key={post.post_id} type="button" className={styles.postedCard} onClick={() => setReviewPostId(post.post_id)}>
                                    {url ? (
                                        <FadeImg className={styles.postedThumb} src={url} alt={postTitle(post)} loading="lazy" />
                                    ) : (
                                        <span className={styles.postedThumb} aria-hidden />
                                    )}
                                    <p className={styles.postedMeta}>{postedLabel(post)}</p>
                                </button>
                            )
                        })}
                    </div>
                )}
            </section>

            {reviewPost && api && (
                <ReviewSheet
                    api={api}
                    post={reviewPost}
                    posterUrl={postPosterUrl(reviewPost)}
                    onClose={() => setReviewPostId(null)}
                    replacePost={replacePost}
                    onError={setError}
                />
            )}
            {api && (
                <ComposerSheet
                    api={api}
                    open={composerOpen}
                    assets={assets}
                    onClose={() => setComposerOpen(false)}
                    onQueued={(next) => {
                        setAutopilot(next)
                        setComposerOpen(false)
                        toast("Added to the queue")
                    }}
                />
            )}
        </DashboardPage>
    )
}

function isPipelineRunUpdate(message: RunStreamMessage) {
    return (
        message.type === "run_manifest"
        && (message.run.workflow_type === "edit_pipeline"
            || message.run.workflow_type === "youtube_song_import"
            || message.run.workflow_type === "music_analysis")
    )
}

function postTitle(post: PublishingPost) {
    if (post.source_name && post.song_name) {
        return `${post.source_name} × ${post.song_name}`
    }
    return post.render_display_name
}

function postedLabel(post: PublishingPost) {
    if (post.status === "published") {
        return `${formatDate(post.posted_at ?? post.updated_at)} · on Instagram`
    }
    if (post.status === "scheduled") {
        return `scheduled ${post.scheduled_at ? formatDate(post.scheduled_at) : ""}`
    }
    return "queued"
}

function itemTitle(item: AutopilotItem, assetById: Map<string, AssetSummary>) {
    const video = assetById.get(item.source_video_file_id)?.display_name ?? "Video"
    const song = item.song_file_id
        ? assetById.get(item.song_file_id)?.display_name ?? "Song"
        : item.song_youtube_url ?? "Song"
    return `${stripExtension(video)} × ${stripExtension(song)}`
}

// One row per in-flight autopilot item. Editing items have a real edit run —
// show its live percent + ETA; importing/analyzing show the stage sentence.
function WorkingRow({ item, jobs, assets }: { item: AutopilotItem; jobs: EditJobStatus[]; assets: Map<string, AssetSummary> }) {
    const job = item.edit_run_id ? jobs.find((candidate) => candidate.run_id === item.edit_run_id) ?? null : null
    const title = itemTitle(item, assets)
    if (item.status === "editing" && job) {
        return <EditingRow title={title} job={job} item={item} />
    }
    const stageText = item.status === "importing" ? "Getting the song…" : "Listening to the song…"
    return <ProgressRow title={title} stageText={stageText} percent={null} />
}

function EditingRow({ title, job, item }: { title: string; job: EditJobStatus; item: AutopilotItem }) {
    const isActive = job.status === "running" || job.status === "created" || job.status === "blocked"
    const now = useNow(isActive)
    const etaSec = useRenderEta(job, isActive, now)
    const stage = job.stages.find((candidate) => candidate.status === "running") ?? null
    const trimWindow =
        item.audio_start_sec !== null && item.audio_end_sec !== null
            ? ` · cutting ${formatClock(item.audio_start_sec)}–${formatClock(item.audio_end_sec)}`
            : ""
    const eta = etaSec !== null ? ` · about ${Math.max(1, Math.round(etaSec))}s left` : ""
    return (
        <ProgressRow
            title={`${title}${trimWindow}`}
            stageText={`${humanizeStageDetail(stage?.detail, stage?.id ?? job.status)} · ${job.progress_percent}%${eta}`}
            percent={job.progress_percent}
        />
    )
}

function ReviewSheet({
    api,
    post,
    posterUrl,
    onClose,
    replacePost,
    onError,
}: {
    api: EclypteApiClient
    post: PublishingPost
    posterUrl?: string
    onClose: () => void
    replacePost: (next: PublishingPost) => void
    onError: (message: string | null) => void
}) {
    const toast = useToast()
    const [caption, setCaption] = useState("")
    const [hashtags, setHashtags] = useState("")
    const [scheduledAt, setScheduledAt] = useState("")
    const [videoError, setVideoError] = useState<string | null>(null)
    const [playing, setPlaying] = useState(false)
    const [busy, setBusy] = useState<string | null>(null) // which action is running
    const syncedPostIdRef = useRef<string | null>(null)
    // The signed render URL arrives with the post itself — no fetch, no spinner wait.
    const videoUrl = postRenderUrl(post) ?? null

    // Dirty-guard (ported): reseed the editor only when the DISPLAYED post changes,
    // never when a background poll swaps the same post's object.
    useEffect(() => {
        if (post.post_id === syncedPostIdRef.current) {
            return
        }
        syncedPostIdRef.current = post.post_id
        setCaption(post.caption)
        setHashtags(post.hashtags.join(" "))
        setScheduledAt(toLocalDateTimeInput(post.scheduled_at))
        setPlaying(false)
        setVideoError(null)
    }, [post])

    const saveCurrent = async () => {
        const next = await api.updatePublishingPost(post.post_id, {
            caption,
            hashtags: hashtags.split(/\s+/).map((tag) => tag.trim()).filter(Boolean),
            notes: post.notes,
            scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
        })
        replacePost(next)
        return next
    }

    const act = async (name: string, action: () => Promise<void>) => {
        setBusy(name)
        onError(null)
        try {
            await action()
        } catch (caught) {
            onError(errorMessage(caught))
        } finally {
            setBusy(null)
        }
    }

    const send = (mode: "queue" | "schedule" | "now") =>
        act(mode, async () => {
            if (mode === "schedule" && !scheduledAt) {
                throw new Error("Choose a time first.")
            }
            const saved = await saveCurrent()
            const sent = await api.sendPublishingPostToBuffer(saved.post_id, {
                mode,
                scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
            })
            replacePost(sent)
            toast(mode === "now" ? "Posting to Instagram" : mode === "queue" ? "Added to the posting queue" : "Scheduled")
            onClose()
        })

    const rewrite = () =>
        act("rewrite", async () => {
            const next = await api.regeneratePublishingCaption(post.post_id)
            replacePost(next)
            setCaption(next.caption)
            setHashtags(next.hashtags.join(" "))
        })

    const canSend = post.status === "ready" || post.status === "draft" || post.status === "failed"
    const inFlight = post.status === "queued" || post.status === "scheduled"

    return (
        <Sheet
            open
            title={postTitle(post)}
            onClose={onClose}
            footer={
                canSend ? (
                    <>
                        <button className={styles.primaryButton} type="button" onClick={() => send("now")} disabled={busy !== null}>
                            {busy === "now" ? <Spinner onInk /> : null} Post now
                        </button>
                        <button className={styles.secondaryButton} type="button" onClick={() => send("schedule")} disabled={busy !== null}>
                            {busy === "schedule" ? <Spinner /> : null} Schedule
                        </button>
                        <button className={styles.secondaryButton} type="button" onClick={() => send("queue")} disabled={busy !== null}>
                            {busy === "queue" ? <Spinner /> : null} Add to queue
                        </button>
                        <span className={styles.sheetActionsRight}>
                            <button
                                className={styles.dangerButton}
                                type="button"
                                onClick={() => act("skip", async () => {
                                    replacePost(await api.cancelPublishingPost(post.post_id))
                                    toast("Skipped")
                                    onClose()
                                })}
                                disabled={busy !== null}
                            >
                                {busy === "skip" ? <Spinner /> : null} Skip this reel
                            </button>
                        </span>
                    </>
                ) : (
                    <>
                        {post.buffer_post_id && (
                            <button
                                className={styles.secondaryButton}
                                type="button"
                                onClick={() => act("recheck", async () => {
                                    replacePost(await api.refreshPublishingPostStatus(post.post_id))
                                    toast("Checked with Instagram")
                                })}
                                disabled={busy !== null}
                            >
                                {busy === "recheck" ? <Spinner /> : <RefreshCw size={15} />} Re-check status
                            </button>
                        )}
                        {inFlight && (
                            <button
                                className={styles.secondaryButton}
                                type="button"
                                onClick={() => act("mark", async () => {
                                    replacePost(await api.markPublishingPostPosted(post.post_id))
                                    toast("Marked as posted")
                                })}
                                disabled={busy !== null}
                            >
                                {busy === "mark" ? <Spinner /> : null} Mark as posted
                            </button>
                        )}
                        {post.post_url && (
                            <a className={styles.detailLink} href={post.post_url} target="_blank" rel="noreferrer">
                                Open on Instagram
                            </a>
                        )}
                    </>
                )
            }
        >
            {videoError ? (
                <p className={styles.smallText} style={{ margin: 0 }}>{videoError}</p>
            ) : (
                // One constant footprint: the poster and the player share this frame,
                // so pressing play never resizes the sheet.
                <div className={`${styles.mediaFrame} ${styles.mediaFrameTall}`}>
                    {playing && videoUrl ? (
                        <video
                            className={styles.mediaFrameFill}
                            controls
                            autoPlay
                            src={videoUrl}
                            onError={(event) => {
                                const mediaError = event.currentTarget.error
                                setVideoError(`Playback failed${mediaError ? ` (media error ${mediaError.code})` : ""}.`)
                            }}
                        />
                    ) : (
                        <>
                            {posterUrl && (
                                <FadeImg
                                    className={styles.mediaFrameFill}
                                    style={{ objectFit: "cover" }}
                                    src={posterUrl}
                                    alt=""
                                />
                            )}
                            <button
                                type="button"
                                className={styles.posterPlayIcon}
                                onClick={() => setPlaying(true)}
                                disabled={!videoUrl}
                                aria-label="Play preview"
                            >
                                {videoUrl ? "▶" : <Spinner onInk />}
                            </button>
                        </>
                    )}
                </div>
            )}
            {canSend ? (
                <>
                    <label className={styles.fieldLabel}>
                        <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            Caption
                            <button className={styles.ghostButton} type="button" onClick={rewrite} disabled={busy !== null} style={{ minHeight: 0, padding: "0.2rem 0.4rem" }}>
                                {busy === "rewrite" ? <Spinner /> : "↺"} Rewrite
                            </button>
                        </span>
                        <textarea className={styles.textarea} value={caption} onChange={(event) => setCaption(event.target.value)} />
                    </label>
                    <label className={styles.fieldLabel}>
                        Hashtags
                        <input className={styles.input} value={hashtags} onChange={(event) => setHashtags(event.target.value)} />
                    </label>
                    <label className={styles.fieldLabel}>
                        Schedule for (optional)
                        <input className={styles.input} type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
                    </label>
                    <p className={styles.smallText}>Posts to Instagram as a Reel.</p>
                </>
            ) : (
                <>
                    <p className={styles.proseText}>{post.caption}</p>
                    <p className={styles.smallText}>{post.hashtags.join(" ")}</p>
                    <p className={styles.smallText}>{postedLabel(post)}</p>
                </>
            )}
            {post.last_error && <div className={styles.errorBanner}>{post.last_error}</div>}
        </Sheet>
    )
}

function toLocalDateTimeInput(value: string | null) {
    if (!value) {
        return ""
    }
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
        return ""
    }
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    return local.toISOString().slice(0, 16)
}

function ComposerSheet({
    api,
    open,
    assets,
    onClose,
    onQueued,
}: {
    api: EclypteApiClient
    open: boolean
    assets: AssetSummary[]
    onClose: () => void
    onQueued: (next: Awaited<ReturnType<EclypteApiClient["addAutopilotItems"]>>) => void
}) {
    const [videoId, setVideoId] = useState("")
    const [songMode, setSongMode] = useState<"asset" | "youtube">("asset")
    const [songId, setSongId] = useState("")
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [brief, setBrief] = useState("")
    const [formError, setFormError] = useState<string | null>(null)
    const [isAdding, setIsAdding] = useState(false)

    const videos = assets.filter((asset) => asset.kind === "source_video" && asset.current_version_id && !asset.archived_at)
    const songs = assets.filter((asset) => asset.kind === "song_audio" && asset.current_version_id && !asset.archived_at)

    const add = async () => {
        const video = videos.find((asset) => asset.file_id === videoId)
        if (!video?.current_version_id) {
            setFormError("Pick a film first.")
            return
        }
        const song = songMode === "asset" ? songs.find((asset) => asset.file_id === songId) : null
        if (songMode === "asset" && !song?.current_version_id) {
            setFormError("Pick a song, or switch to a YouTube link.")
            return
        }
        if (songMode === "youtube" && !youtubeUrl.trim()) {
            setFormError("Paste a YouTube link, or pick a saved song.")
            return
        }
        setIsAdding(true)
        setFormError(null)
        try {
            const next = await api.addAutopilotItems([
                {
                    source_video: { file_id: video.file_id, version_id: video.current_version_id },
                    song: song?.current_version_id ? { file_id: song.file_id, version_id: song.current_version_id } : null,
                    song_youtube_url: songMode === "youtube" ? youtubeUrl.trim() : null,
                    creative_brief: brief.trim(),
                },
            ])
            setYoutubeUrl("")
            setBrief("")
            onQueued(next)
        } catch (caught) {
            setFormError(errorMessage(caught))
        } finally {
            setIsAdding(false)
        }
    }

    return (
        <Sheet
            open={open}
            title="New reel"
            onClose={onClose}
            footer={
                <button className={styles.primaryButton} type="button" onClick={add} disabled={isAdding}>
                    {isAdding ? <Spinner onInk /> : <Plus size={16} />} Add to queue
                </button>
            }
        >
            {formError && <div className={styles.errorBanner}>{formError}</div>}
            <div className={styles.fieldLabel}>
                Film
                <div className={styles.mediaGrid} role="radiogroup" aria-label="Film">
                    {videos.map((asset) => {
                        const url = assetPosterUrl(asset)
                        const selected = videoId === asset.file_id
                        return (
                            <button
                                key={asset.file_id}
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                className={styles.mediaCard}
                                style={selected ? { borderColor: "var(--text-primary)", boxShadow: "inset 0 0 0 1px var(--text-primary)" } : undefined}
                                onClick={() => setVideoId(asset.file_id)}
                            >
                                {url ? (
                                    <FadeImg className={styles.mediaThumb} src={url} alt="" loading="lazy" />
                                ) : (
                                    <span className={styles.mediaThumb} aria-hidden />
                                )}
                                <span className={styles.mediaCardBody}>
                                    <span className={styles.mediaTitle}>{stripExtension(asset.display_name)}</span>
                                </span>
                            </button>
                        )
                    })}
                </div>
            </div>
            <div className={styles.fieldLabel}>
                Song
                <Select
                    ariaLabel="Song source"
                    value={songMode}
                    onChange={(next) => setSongMode(next as "asset" | "youtube")}
                    options={[
                        { value: "asset", label: "Use a saved song" },
                        { value: "youtube", label: "Import from YouTube" },
                    ]}
                />
            </div>
            {songMode === "asset" ? (
                <div className={styles.fieldLabel}>
                    Saved song
                    <Select
                        ariaLabel="Saved song"
                        value={songId}
                        onChange={setSongId}
                        placeholder="Pick a song…"
                        options={songs.map((asset) => ({ value: asset.file_id, label: stripExtension(asset.display_name) }))}
                    />
                </div>
            ) : (
                <label className={styles.fieldLabel}>
                    YouTube link
                    <input className={styles.input} placeholder="https://youtu.be/…" value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} />
                </label>
            )}
            <label className={styles.fieldLabel}>
                Creative note (optional)
                <textarea className={`${styles.textarea} ${styles.compactTextarea}`} placeholder="Open on the most impactful shot, lean into the chorus…" value={brief} onChange={(event) => setBrief(event.target.value)} />
            </label>
        </Sheet>
    )
}
