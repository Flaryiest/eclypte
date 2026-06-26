"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import {
    CalendarClock,
    CheckCircle,
    ExternalLink,
    RefreshCw,
    Save,
    Send,
    Sparkles,
    XCircle,
} from "lucide-react"
import {
    DashboardPage,
    SkeletonList,
    StatusBadge,
    errorMessage,
    formatDate,
} from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    EclypteApiClient,
    PublishingConfig,
    PublishingPost,
    PublishingPostStatus,
} from "@/services/eclypteApi"
import { usePublishingConfig, usePublishingPosts } from "@/stores/dashboardResources"

type PublishTab = "ready" | "queued_scheduled" | "published" | "failed"
type Preview = { postId: string; url: string }

const tabs: Array<{ id: PublishTab; label: string }> = [
    { id: "ready", label: "Ready" },
    { id: "queued_scheduled", label: "Queued" },
    { id: "published", label: "Posted" },
    { id: "failed", label: "Failed" },
]

// How often in-flight posts are reconciled against Buffer while the tab is visible.
const POLL_INTERVAL_MS = 25000

export default function PublishPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [tab, setTab] = useState<PublishTab>("ready")
    const [caption, setCaption] = useState("")
    const [hashtags, setHashtags] = useState("")
    const [notes, setNotes] = useState("")
    const [scheduledAt, setScheduledAt] = useState("")
    const [preview, setPreview] = useState<Preview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isWorking, setIsWorking] = useState(false)
    const pollableIdsRef = useRef<string[]>([])
    const syncedPostIdRef = useRef<string | null>(null)
    const previewKeyRef = useRef<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const postsResource = usePublishingPosts(api, { status: "all" })
    const posts = useMemo(() => postsResource.data ?? [], [postsResource.data])
    const setPosts = postsResource.set
    const configResource = usePublishingConfig(api)
    const config = configResource.data ?? null
    const isLoading = postsResource.isLoading
    const loadError = postsResource.error ?? configResource.error
    const visiblePosts = useMemo(() => filterPosts(posts, tab), [posts, tab])
    // Lane-aware: the detail panel always shows a post that lives in the active tab,
    // so switching tabs never strands the panel on a post hidden from the list.
    const selected = visiblePosts.find((post) => post.post_id === selectedId) ?? visiblePosts[0] ?? null
    // Posts still moving through Buffer (queued/scheduled, or published without a
    // permalink yet); these get polled until they settle so the UI reconciles live.
    const pollablePosts = useMemo(
        () =>
            posts.filter(
                (post) =>
                    Boolean(post.buffer_post_id)
                    && (post.status === "queued"
                        || post.status === "scheduled"
                        || (post.status === "published" && !post.post_url)),
            ),
        [posts],
    )
    const hasPollable = pollablePosts.length > 0

    // The loader must not depend on `tab` — that coupling made every tab switch
    // refetch the whole list (and clobber optimistic updates). Read the live tab
    // through a ref so default-selection stays correct without re-subscribing.
    const tabRef = useRef(tab)
    tabRef.current = tab

    const handleManualRefresh = () => {
        postsResource.revalidate()
        configResource.revalidate()
    }

    // Default the selected post once the cached list loads (or when the current
    // selection drops out of the list), preferring a post in the active tab. The
    // live tab is read via ref so a tab switch doesn't re-run this.
    useEffect(() => {
        setSelectedId((current) => {
            if (current && posts.some((post) => post.post_id === current)) {
                return current
            }
            return filterPosts(posts, tabRef.current)[0]?.post_id ?? posts[0]?.post_id ?? null
        })
    }, [posts])

    // Resync the editor only when the displayed post changes — not when a background
    // poll replaces the same post's object — so live reconciliation never wipes
    // unsaved caption/hashtag edits.
    useEffect(() => {
        const id = selected?.post_id ?? null
        if (id === syncedPostIdRef.current) {
            return
        }
        syncedPostIdRef.current = id
        if (!selected) {
            setCaption("")
            setHashtags("")
            setNotes("")
            setScheduledAt("")
            return
        }
        setCaption(selected.caption)
        setHashtags(selected.hashtags.join(" "))
        setNotes(selected.notes)
        setScheduledAt(toLocalDateTimeInput(selected.scheduled_at))
    }, [selected])

    // Fetch the preview only when the displayed media changes. A background poll that
    // updates the selected post's object (same render) must not reset the <video>.
    useEffect(() => {
        if (!api || !selected) {
            previewKeyRef.current = null
            setPreview(null)
            return
        }
        const key = `${selected.render_file_id}:${selected.render_version_id}`
        if (key === previewKeyRef.current) {
            return
        }
        previewKeyRef.current = key
        const postId = selected.post_id
        let ignore = false
        setPreview(null)
        void api.getDownloadUrl({
            file_id: selected.render_file_id,
            version_id: selected.render_version_id,
        }).then((download) => {
            if (!ignore) {
                setPreview({ postId, url: download.download_url })
            }
        }).catch((caught) => {
            if (!ignore) {
                setError(errorMessage(caught))
            }
        })
        return () => {
            ignore = true
        }
    }, [api, selected])

    // Keep the latest pollable ids in a ref so the interval below always reconciles the
    // current in-flight set without re-subscribing on every poll.
    useEffect(() => {
        pollableIdsRef.current = pollablePosts.map((post) => post.post_id)
    })

    // Live reconciliation: while posts are in flight, refresh them against Buffer on an
    // interval and immediately when the tab regains focus, so queued posts auto-advance
    // to Posted and permalinks fill in without a manual refresh. Background errors are
    // swallowed (the manual "Refresh from Buffer" button surfaces them); merges are by
    // id so the selected post's editor and unrelated rows are untouched.
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
                    setPosts((current = []) =>
                        current.map((post) => (post.post_id === next.post_id ? next : post)),
                    )
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
        setPosts((current = []) => current.map((post) => post.post_id === next.post_id ? next : post))
        setSelectedId(next.post_id)
    }

    const saveCurrent = async () => {
        if (!api || !selected) {
            return null
        }
        const next = await api.updatePublishingPost(selected.post_id, {
            caption,
            hashtags: parseHashtags(hashtags),
            notes,
            scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
        })
        replacePost(next)
        return next
    }

    const handleSave = async () => {
        setIsWorking(true)
        setError(null)
        try {
            await saveCurrent()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsWorking(false)
        }
    }

    const handleRegenerate = async () => {
        if (!api || !selected) {
            return
        }
        setIsWorking(true)
        setError(null)
        try {
            const next = await api.regeneratePublishingCaption(selected.post_id)
            replacePost(next)
            setCaption(next.caption)
            setHashtags(next.hashtags.join(" "))
            setNotes(next.notes)
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsWorking(false)
        }
    }

    const handleSend = async (mode: "queue" | "schedule") => {
        if (!api || !selected) {
            return
        }
        if (mode === "schedule" && !scheduledAt) {
            setError("Choose a scheduled time first.")
            return
        }
        setIsWorking(true)
        setError(null)
        try {
            const saved = await saveCurrent()
            if (!saved) {
                return
            }
            const sent = await api.sendPublishingPostToBuffer(saved.post_id, {
                mode,
                scheduledAt: scheduledAt ? new Date(scheduledAt).toISOString() : null,
            })
            replacePost(sent)
            setTab(sent.status === "scheduled" ? "queued_scheduled" : statusToTab(sent.status))
        } catch (caught) {
            setError(errorMessage(caught))
            postsResource.revalidate()
        } finally {
            setIsWorking(false)
        }
    }

    const handleCancel = async () => {
        if (!api || !selected) {
            return
        }
        setIsWorking(true)
        setError(null)
        try {
            const next = await api.cancelPublishingPost(selected.post_id)
            replacePost(next)
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsWorking(false)
        }
    }

    const handleRefreshFromBuffer = async () => {
        if (!api || !selected) {
            return
        }
        // Manual, on-demand re-check that surfaces any Buffer error (the background
        // poll swallows them), so we can see why a live post's URL isn't coming back.
        setIsWorking(true)
        setError(null)
        try {
            const next = await api.refreshPublishingPostStatus(selected.post_id)
            replacePost(next)
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsWorking(false)
        }
    }

    const handleMarkPosted = async () => {
        if (!api || !selected) {
            return
        }
        // Manual override: the post went live but Buffer can't reconcile it (stale id).
        // Move it to the Posted lane and follow it there.
        setIsWorking(true)
        setError(null)
        try {
            const next = await api.markPublishingPostPosted(selected.post_id)
            replacePost(next)
            setTab(statusToTab(next.status))
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsWorking(false)
        }
    }

    if (!isLoaded) {
        return (
            <DashboardPage eyebrow="Publish" title="Loading publishing">
                <SkeletonList count={3} />
            </DashboardPage>
        )
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Publish" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to manage publishing.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Publish"
            title="Reels queue"
            subtitle="Review generated post packages, edit captions, and send approved renders to Buffer."
            action={
                <button className={styles.secondaryButton} type="button" onClick={handleManualRefresh} disabled={isLoading}>
                    <RefreshCw size={16} /> Refresh
                </button>
            }
        >
            {(error || loadError) && <div className={styles.errorBanner}>{error || loadError}</div>}

            {config && (
                <section className={styles.grid}>
                    <div className={`${styles.panel} ${styles.full}`}>
                        <div className={styles.panelHeader}>
                            <div>
                                <h2>Publishing setup</h2>
                                <p>Buffer, public media, and caption generation status.</p>
                            </div>
                            <StatusBadge
                                label={publishingConfigReady(config) ? "ready" : "needs setup"}
                                tone={publishingConfigReady(config) ? "ready" : "blocked"}
                            />
                        </div>
                        <div className={styles.settingsGrid}>
                            <PostDetail label="Buffer API key" value={configuredLabel(config.buffer_api_key_configured)} />
                            <PostDetail label="Instagram channel" value={channelLabel(config)} href={config.buffer_channel?.external_link} />
                            <PostDetail label="Public R2 media" value={configuredLabel(config.public_media_base_url_configured)} />
                            <PostDetail label="Caption model" value={config.openai_api_key_configured ? config.caption_model : "Fallback captions"} />
                        </div>
                        {config.buffer_channel?.last_error && (
                            <div className={styles.errorBanner}>{config.buffer_channel.last_error}</div>
                        )}
                    </div>
                </section>
            )}

            <div className={styles.segmentedControl} role="tablist" aria-label="Publish status">
                {tabs.map((item) => {
                    const count = filterPosts(posts, item.id).length
                    return (
                        <button
                            key={item.id}
                            className={tab === item.id ? styles.segmentActive : styles.segmentButton}
                            type="button"
                            onClick={() => setTab(item.id)}
                        >
                            {item.label}{count > 0 ? ` ${count}` : ""}
                        </button>
                    )
                })}
            </div>

            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Packages</h2>
                            <p>{visiblePosts.length} post{visiblePosts.length === 1 ? "" : "s"}</p>
                        </div>
                    </div>
                    {isLoading && visiblePosts.length === 0 ? (
                        <SkeletonList count={3} />
                    ) : visiblePosts.length === 0 ? (
                        <div className={styles.emptyState}>No posts in this lane.</div>
                    ) : (
                        <div className={styles.packageList}>
                            {visiblePosts.map((post) => (
                                <button
                                    type="button"
                                    key={post.post_id}
                                    className={`${styles.packageRow} ${selected?.post_id === post.post_id ? styles.packageRowSelected : ""}`}
                                    onClick={() => setSelectedId(post.post_id)}
                                    aria-pressed={selected?.post_id === post.post_id}
                                >
                                    <span className={styles.packageRowHead}>
                                        <span className={styles.packageRowTitle} title={post.render_display_name}>
                                            {post.render_display_name}
                                        </span>
                                        <StatusBadge label={post.status} tone={post.status} />
                                    </span>
                                    <span className={styles.packageRowMeta}>
                                        {post.collection_slug || "uncategorized"}
                                        {post.auto_created ? " · autopilot" : ""}
                                        {" · "}
                                        {formatDate(post.updated_at)}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                <div className={`${styles.detailPanel} ${styles.wide}`}>
                    {!selected ? (
                        <div className={styles.detailEmpty}>No publishing package selected.</div>
                    ) : (
                        <>
                            <div className={styles.cardTop}>
                                <div>
                                    <h2 className={styles.heroCaptionTitle}>{selected.render_display_name}</h2>
                                    <p className={styles.heroCaptionMeta}>
                                        {selected.collection_slug || "uncategorized"} - {formatDate(selected.updated_at)}
                                    </p>
                                </div>
                                <StatusBadge label={selected.status} tone={selected.status} />
                            </div>

                            {preview?.postId === selected.post_id && (
                                <video className={styles.previewMedia} controls src={preview.url} />
                            )}

                            <div className={styles.fieldStack}>
                                <label className={styles.fieldLabel}>
                                    Caption
                                    <textarea
                                        className={styles.textarea}
                                        value={caption}
                                        onChange={(event) => setCaption(event.target.value)}
                                    />
                                </label>
                                <label className={styles.fieldLabel}>
                                    Hashtags
                                    <textarea
                                        className={`${styles.textarea} ${styles.compactTextarea}`}
                                        value={hashtags}
                                        onChange={(event) => setHashtags(event.target.value)}
                                    />
                                </label>
                                <label className={styles.fieldLabel}>
                                    Notes
                                    <textarea
                                        className={`${styles.textarea} ${styles.compactTextarea}`}
                                        value={notes}
                                        onChange={(event) => setNotes(event.target.value)}
                                    />
                                </label>
                                <label className={styles.fieldLabel}>
                                    Schedule
                                    <input
                                        className={styles.input}
                                        type="datetime-local"
                                        value={scheduledAt}
                                        onChange={(event) => setScheduledAt(event.target.value)}
                                    />
                                </label>
                            </div>

                            <div className={styles.cardActions}>
                                <button className={styles.secondaryButton} type="button" onClick={handleSave} disabled={isWorking}>
                                    <Save size={16} /> Save
                                </button>
                                <button className={styles.secondaryButton} type="button" onClick={handleRegenerate} disabled={isWorking}>
                                    <Sparkles size={16} /> Regenerate
                                </button>
                                <button className={styles.primaryButton} type="button" onClick={() => handleSend("queue")} disabled={isWorking}>
                                    <Send size={16} /> Queue
                                </button>
                                <button className={styles.secondaryButton} type="button" onClick={() => handleSend("schedule")} disabled={isWorking}>
                                    <CalendarClock size={16} /> Schedule
                                </button>
                                {selected.buffer_post_id && (
                                    <button className={styles.secondaryButton} type="button" onClick={handleRefreshFromBuffer} disabled={isWorking}>
                                        <RefreshCw size={16} /> Refresh from Buffer
                                    </button>
                                )}
                                {(selected.status === "queued" || selected.status === "scheduled") && (
                                    <button className={styles.secondaryButton} type="button" onClick={handleMarkPosted} disabled={isWorking}>
                                        <CheckCircle size={16} /> Mark as posted
                                    </button>
                                )}
                                <button className={styles.dangerButton} type="button" onClick={handleCancel} disabled={isWorking}>
                                    <XCircle size={16} /> Cancel
                                </button>
                            </div>

                            <div className={styles.settingsGrid}>
                                <PostDetail label="Buffer post" value={selected.buffer_post_id || "Not sent"} />
                                <PostDetail label="Buffer status" value={selected.buffer_status || "Not sent"} />
                                <PostDetail label="Caption source" value={captionSourceLabel(selected)} />
                                <PostDetail label="Scheduled" value={formatDate(selected.scheduled_at)} />
                                <PostDetail label="Public media" value={selected.public_media_url || "Not prepared"} href={selected.public_media_url} />
                                <PostDetail label="Post URL" value={selected.post_url || "Not available"} href={selected.post_url} />
                            </div>

                            {selected.caption_error && <div className={styles.errorBanner}>{selected.caption_error}</div>}
                            {selected.last_error && <div className={styles.errorBanner}>{selected.last_error}</div>}
                        </>
                    )}
                </div>
            </section>
        </DashboardPage>
    )
}

function PostDetail({ label, value, href }: { label: string; value: string; href?: string | null }) {
    return (
        <div className={styles.settingCard}>
            <div>
                <span className={styles.settingLabel}>{label}</span>
                {href ? (
                    <a className={styles.monoText} href={href} target="_blank" rel="noreferrer">
                        {value} <ExternalLink size={13} aria-hidden />
                    </a>
                ) : (
                    <span className={styles.monoText}>{value}</span>
                )}
            </div>
        </div>
    )
}

function publishingConfigReady(config: PublishingConfig) {
    return (
        config.buffer_api_key_configured
        && config.buffer_channel_id_configured
        && config.public_media_base_url_configured
        && !config.buffer_channel?.last_error
        && !config.buffer_channel?.is_disconnected
        && !config.buffer_channel?.is_locked
    )
}

function configuredLabel(value: boolean) {
    return value ? "Configured" : "Missing"
}

function channelLabel(config: PublishingConfig) {
    if (!config.buffer_channel_id_configured) {
        return "Missing"
    }
    if (!config.buffer_channel) {
        return "Configured"
    }
    const name = config.buffer_channel.display_name || config.buffer_channel.name || config.buffer_channel.id
    if (config.buffer_channel.is_disconnected) {
        return `${name} disconnected`
    }
    if (config.buffer_channel.is_locked) {
        return `${name} locked`
    }
    return name
}

function captionSourceLabel(post: PublishingPost) {
    if (post.caption_source === "openai") {
        return "OpenAI"
    }
    if (post.caption_error) {
        return "Fallback after model error"
    }
    return "Fallback"
}

function filterPosts(posts: PublishingPost[], tab: PublishTab) {
    if (tab === "queued_scheduled") {
        return posts.filter((post) => post.status === "queued" || post.status === "scheduled")
    }
    return posts.filter((post) => statusToTab(post.status) === tab)
}

function statusToTab(status: PublishingPostStatus): PublishTab {
    if (status === "queued" || status === "scheduled") {
        return "queued_scheduled"
    }
    if (status === "published") {
        return "published"
    }
    if (status === "failed") {
        return "failed"
    }
    return "ready"
}

function parseHashtags(value: string) {
    return value.split(/\s+/).map((item) => item.trim()).filter(Boolean)
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
