"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import {
    CalendarClock,
    ExternalLink,
    RefreshCw,
    Save,
    Send,
    Sparkles,
    XCircle,
} from "lucide-react"
import {
    DashboardPage,
    StatusBadge,
    formatDate,
} from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    EclypteApiClient,
    PublishingConfig,
    PublishingPost,
    PublishingPostStatus,
} from "@/services/eclypteApi"

type PublishTab = "ready" | "queued_scheduled" | "published" | "failed"
type Preview = { postId: string; url: string }

const tabs: Array<{ id: PublishTab; label: string }> = [
    { id: "ready", label: "Ready" },
    { id: "queued_scheduled", label: "Queued" },
    { id: "published", label: "Posted" },
    { id: "failed", label: "Failed" },
]

export default function PublishPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [posts, setPosts] = useState<PublishingPost[]>([])
    const [config, setConfig] = useState<PublishingConfig | null>(null)
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [tab, setTab] = useState<PublishTab>("ready")
    const [caption, setCaption] = useState("")
    const [hashtags, setHashtags] = useState("")
    const [notes, setNotes] = useState("")
    const [scheduledAt, setScheduledAt] = useState("")
    const [preview, setPreview] = useState<Preview | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [isWorking, setIsWorking] = useState(false)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const visiblePosts = useMemo(() => filterPosts(posts, tab), [posts, tab])
    const selected = posts.find((post) => post.post_id === selectedId) || visiblePosts[0] || null

    const loadPosts = useCallback(async () => {
        if (!api) {
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            const [nextConfig, next] = await Promise.all([
                api.getPublishingConfig(),
                api.listPublishingPosts({ status: "all" }),
            ])
            setConfig(nextConfig)
            setPosts(next)
            setSelectedId((current) => {
                if (current && next.some((post) => post.post_id === current)) {
                    return current
                }
                return filterPosts(next, tab)[0]?.post_id ?? next[0]?.post_id ?? null
            })
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsLoading(false)
        }
    }, [api, tab])

    useEffect(() => {
        void loadPosts()
    }, [loadPosts])

    useEffect(() => {
        if (!selected) {
            setCaption("")
            setHashtags("")
            setNotes("")
            setScheduledAt("")
            setPreview(null)
            return
        }
        setCaption(selected.caption)
        setHashtags(selected.hashtags.join(" "))
        setNotes(selected.notes)
        setScheduledAt(toLocalDateTimeInput(selected.scheduled_at))
    }, [selected])

    useEffect(() => {
        if (!api || !selected) {
            return
        }
        let ignore = false
        setPreview(null)
        void api.getDownloadUrl({
            file_id: selected.render_file_id,
            version_id: selected.render_version_id,
        }).then((download) => {
            if (!ignore) {
                setPreview({ postId: selected.post_id, url: download.download_url })
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

    const replacePost = (next: PublishingPost) => {
        setPosts((current) => current.map((post) => post.post_id === next.post_id ? next : post))
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
            await loadPosts()
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

    if (!isLoaded) {
        return <DashboardPage eyebrow="Publish" title="Loading publishing"><div /></DashboardPage>
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
                <button className={styles.secondaryButton} type="button" onClick={loadPosts} disabled={isLoading}>
                    <RefreshCw size={16} /> Refresh
                </button>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}

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
                {tabs.map((item) => (
                    <button
                        key={item.id}
                        className={tab === item.id ? styles.segmentActive : styles.segmentButton}
                        type="button"
                        onClick={() => setTab(item.id)}
                    >
                        {item.label}
                    </button>
                ))}
            </div>

            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Packages</h2>
                            <p>{visiblePosts.length} post{visiblePosts.length === 1 ? "" : "s"}</p>
                        </div>
                    </div>
                    {visiblePosts.length === 0 ? (
                        <div className={styles.emptyState}>No posts in this lane.</div>
                    ) : (
                        <div className={styles.assetTable}>
                            {visiblePosts.map((post) => (
                                <button
                                    type="button"
                                    key={post.post_id}
                                    className={`${styles.assetRow} ${selected?.post_id === post.post_id ? styles.assetRowSelected : ""}`}
                                    onClick={() => setSelectedId(post.post_id)}
                                    aria-pressed={selected?.post_id === post.post_id}
                                >
                                    <span className={styles.assetRowName}>
                                        <span className={styles.assetRowTitle}>{post.render_display_name}</span>
                                        <span className={styles.assetRowMeta}>{post.collection_slug || "uncategorized"}</span>
                                    </span>
                                    <span className={styles.assetRowCell}>
                                        <StatusBadge label={post.status} tone={post.status} />
                                    </span>
                                    <span className={styles.assetRowCell}>{formatDate(post.updated_at)}</span>
                                    <span className={styles.assetRowCell}>{post.buffer_post_id || "Not sent"}</span>
                                    <span className={styles.assetRowCellNumeral}>{post.provider}</span>
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

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
