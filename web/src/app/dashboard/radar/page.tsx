"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Archive, Check, ExternalLink, RefreshCw, Search, X } from "lucide-react"
import { DashboardPage, StatusBadge, formatDate } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    ContentCandidate,
    ContentCandidateStatus,
    ContentMediaType,
    EclypteApiClient,
    RunManifest,
    waitForRunCompletion,
} from "@/services/eclypteApi"

type MediaFilter = ContentMediaType | "all"
type StatusFilter = ContentCandidateStatus | "all"
type ReleaseWindow = "all" | "30" | "90" | "365"

const STATUS_FILTERS: StatusFilter[] = ["all", "available", "approved", "rejected", "imported"]
const MEDIA_FILTERS: MediaFilter[] = ["all", "movie", "tv"]
const RELEASE_WINDOWS: Array<{ value: ReleaseWindow; label: string }> = [
    { value: "all", label: "Any release" },
    { value: "30", label: "30 days" },
    { value: "90", label: "90 days" },
    { value: "365", label: "Year" },
]

export default function RadarPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [candidates, setCandidates] = useState<ContentCandidate[]>([])
    const [mediaType, setMediaType] = useState<MediaFilter>("all")
    const [status, setStatus] = useState<StatusFilter>("all")
    const [provider, setProvider] = useState("")
    const [genre, setGenre] = useState("all")
    const [releaseWindow, setReleaseWindow] = useState<ReleaseWindow>("all")
    const [activeRun, setActiveRun] = useState<RunManifest | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [isDiscovering, setIsDiscovering] = useState(false)
    const [updatingId, setUpdatingId] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const genres = useMemo(() => {
        const values = new Set<string>()
        for (const candidate of candidates) {
            for (const item of candidate.genres) {
                values.add(item)
            }
        }
        return Array.from(values).sort()
    }, [candidates])

    const loadCandidates = useCallback(async () => {
        if (!api) {
            return
        }
        setIsLoading(true)
        setError(null)
        try {
            const releaseFrom = releaseWindow === "all" ? undefined : daysAgo(Number(releaseWindow))
            const next = await api.listContentCandidates({
                mediaType,
                status,
                provider: provider.trim() || undefined,
                genre: genre === "all" ? undefined : genre,
                releaseFrom,
            })
            setCandidates(next)
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsLoading(false)
        }
    }, [api, genre, mediaType, provider, releaseWindow, status])

    useEffect(() => {
        void loadCandidates()
    }, [loadCandidates])

    const runDiscovery = async () => {
        if (!api) {
            return
        }
        setIsDiscovering(true)
        setError(null)
        try {
            const run = await api.createContentRadarDiscovery({ region: "US", maxPages: 1 })
            setActiveRun(run)
            const completed = await waitForRunCompletion(api, run, {
                onUpdate: setActiveRun,
                intervalMs: 1500,
            })
            setActiveRun(completed)
            await loadCandidates()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsDiscovering(false)
        }
    }

    const updateCandidate = async (
        candidate: ContentCandidate,
        action: "approve" | "reject" | "imported",
    ) => {
        if (!api) {
            return
        }
        setUpdatingId(candidate.candidate_id)
        setError(null)
        try {
            const updated = action === "approve"
                ? await api.approveContentCandidate(candidate.candidate_id)
                : action === "reject"
                    ? await api.rejectContentCandidate(candidate.candidate_id)
                    : await api.markContentCandidateImported(candidate.candidate_id)
            setCandidates((current) => current.map((item) => item.candidate_id === updated.candidate_id ? updated : item))
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setUpdatingId(null)
        }
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="Radar" title="Loading radar"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Radar" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to review content radar.</div>
            </DashboardPage>
        )
    }

    return (
        <DashboardPage
            eyebrow="Radar"
            title="Content radar"
            subtitle="New and trending movies/shows filtered to currently available TMDb providers."
            action={
                <>
                    <button className={styles.secondaryButton} type="button" onClick={loadCandidates} disabled={isLoading || isDiscovering}>
                        <RefreshCw size={16} /> Refresh
                    </button>
                    <button className={styles.primaryButton} type="button" onClick={runDiscovery} disabled={isDiscovering}>
                        <Search size={16} /> {isDiscovering ? "Scanning" : "Scan"}
                    </button>
                </>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}
            {activeRun && (
                <div className={styles.successBanner}>
                    {activeRun.workflow_type} - {activeRun.current_step || activeRun.status} - {formatDate(activeRun.updated_at)}
                </div>
            )}

            <section className={styles.panel}>
                <div className={styles.radarFilters}>
                    <label className={styles.fieldLabel}>
                        Media
                        <select className={styles.select} value={mediaType} onChange={(event) => setMediaType(event.target.value as MediaFilter)}>
                            {MEDIA_FILTERS.map((item) => <option key={item} value={item}>{filterLabel(item)}</option>)}
                        </select>
                    </label>
                    <label className={styles.fieldLabel}>
                        Status
                        <select className={styles.select} value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}>
                            {STATUS_FILTERS.map((item) => <option key={item} value={item}>{filterLabel(item)}</option>)}
                        </select>
                    </label>
                    <label className={styles.fieldLabel}>
                        Release
                        <select className={styles.select} value={releaseWindow} onChange={(event) => setReleaseWindow(event.target.value as ReleaseWindow)}>
                            {RELEASE_WINDOWS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                        </select>
                    </label>
                    <label className={styles.fieldLabel}>
                        Genre
                        <select className={styles.select} value={genre} onChange={(event) => setGenre(event.target.value)}>
                            <option value="all">All genres</option>
                            {genres.map((item) => <option key={item} value={item}>{item}</option>)}
                        </select>
                    </label>
                    <label className={styles.fieldLabel}>
                        Provider
                        <input
                            className={styles.input}
                            value={provider}
                            onChange={(event) => setProvider(event.target.value)}
                            placeholder="Netflix"
                        />
                    </label>
                </div>
            </section>

            {candidates.length === 0 ? (
                <div className={styles.emptyState}>{isLoading ? "Loading candidates." : "No content candidates found."}</div>
            ) : (
                <section className={styles.candidateGrid}>
                    {candidates.map((candidate) => (
                        <article className={styles.candidateCard} key={candidate.candidate_id}>
                            <div
                                className={styles.candidatePoster}
                                style={candidate.poster_path ? { backgroundImage: `url(${posterUrl(candidate.poster_path)})` } : undefined}
                            >
                                {!candidate.poster_path && <span>{candidate.title}</span>}
                            </div>
                            <div className={styles.candidateBody}>
                                <div className={styles.cardTop}>
                                    <div>
                                        <h2 className={styles.candidateTitle}>{candidate.title}</h2>
                                        <p className={styles.smallText}>
                                            {filterLabel(candidate.media_type)} - {formatReleaseDate(candidate.release_date)} - {sourceLabel(candidate.source)}
                                        </p>
                                    </div>
                                    <StatusBadge label={candidate.status} tone={candidate.status} />
                                </div>

                                <p className={styles.candidateOverview}>{candidate.overview || "No overview available."}</p>

                                <div className={styles.metricStrip}>
                                    <span><strong>{candidate.score.toFixed(1)}</strong> score</span>
                                    <span><strong>{candidate.vote_average.toFixed(1)}</strong> rating</span>
                                    <span><strong>{candidate.vote_count}</strong> votes</span>
                                </div>

                                <div className={styles.candidateProviders}>
                                    {candidate.providers.slice(0, 5).map((item) => (
                                        <span className={styles.providerPill} key={`${candidate.candidate_id}-${item.provider_id}-${item.provider_type}`}>
                                            {item.name} / {providerTypeLabel(item.provider_type)}
                                        </span>
                                    ))}
                                </div>

                                {candidate.genres.length > 0 && (
                                    <p className={styles.assetCaption}>{candidate.genres.join(" / ")}</p>
                                )}

                                <div className={styles.cardActions}>
                                    <button
                                        className={styles.primaryButton}
                                        type="button"
                                        onClick={() => updateCandidate(candidate, "approve")}
                                        disabled={updatingId === candidate.candidate_id || candidate.status === "approved" || candidate.status === "imported"}
                                    >
                                        <Check size={16} /> Approve
                                    </button>
                                    <button
                                        className={styles.secondaryButton}
                                        type="button"
                                        onClick={() => updateCandidate(candidate, "imported")}
                                        disabled={updatingId === candidate.candidate_id || candidate.status === "imported"}
                                    >
                                        <Archive size={16} /> Imported
                                    </button>
                                    <button
                                        className={styles.dangerButton}
                                        type="button"
                                        onClick={() => updateCandidate(candidate, "reject")}
                                        disabled={updatingId === candidate.candidate_id || candidate.status === "rejected" || candidate.status === "imported"}
                                    >
                                        <X size={16} /> Reject
                                    </button>
                                    <a className={styles.ghostButton} href={candidate.provider_link || candidate.tmdb_url} target="_blank" rel="noreferrer">
                                        <ExternalLink size={16} /> Open
                                    </a>
                                </div>
                            </div>
                        </article>
                    ))}
                </section>
            )}
        </DashboardPage>
    )
}

function daysAgo(days: number) {
    const value = new Date()
    value.setDate(value.getDate() - days)
    return value.toISOString().slice(0, 10)
}

function posterUrl(path: string) {
    return `https://image.tmdb.org/t/p/w342${path}`
}

function formatReleaseDate(value: string | null) {
    if (!value) {
        return "Unknown"
    }
    return new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
    }).format(new Date(`${value}T00:00:00Z`))
}

function sourceLabel(value: string) {
    return value.replace(/^tmdb_/, "").replaceAll("_", " ")
}

function filterLabel(value: string) {
    return value === "tv" ? "TV" : value.replaceAll("_", " ")
}

function providerTypeLabel(value: string) {
    return value === "flatrate" ? "stream" : value
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
