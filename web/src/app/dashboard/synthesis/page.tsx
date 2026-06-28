"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Link, RefreshCw, RotateCcw, Save, Sparkles } from "lucide-react"
import { DashboardPage, Pager, StatusBadge, errorMessage, formatDate, humanizeLabel, usePagination } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    EclypteApiClient,
    RunManifest,
    waitForRunCompletion,
} from "@/services/eclypteApi"
import { useSynthesisPrompt, useSynthesisReferences } from "@/stores/dashboardResources"

const DEFAULT_LABEL = "Manual prompt edit"

export default function SynthesisPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [urlInput, setUrlInput] = useState("")
    const [promptText, setPromptText] = useState("")
    const [versionLabel, setVersionLabel] = useState(DEFAULT_LABEL)
    const [activeRun, setActiveRun] = useState<RunManifest | null>(null)
    const [status, setStatus] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isConsolidating, setIsConsolidating] = useState(false)
    const [isSaving, setIsSaving] = useState(false)
    const [refsOpen, setRefsOpen] = useState(false)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])
    const referencesResource = useSynthesisReferences(api)
    const references = referencesResource.data ?? []
    const promptResource = useSynthesisPrompt(api)
    const promptState = promptResource.data ?? null
    const setPromptState = promptResource.set
    const loadError = referencesResource.error ?? promptResource.error
    const revalidateReferences = referencesResource.revalidate
    const revalidatePrompt = promptResource.revalidate
    const loadSynthesis = useCallback(() => {
        revalidateReferences()
        revalidatePrompt()
    }, [revalidateReferences, revalidatePrompt])
    const completedReferences = references.filter((reference) => reference.status === "completed")
    const activePrompt = promptState?.active_prompt
    const promptChanged = Boolean(activePrompt && promptText !== activePrompt.prompt_text)
    const sortedVersions = promptState
        ? [...promptState.versions].sort((a, b) => {
            if (a.version_id === promptState.active_version_id) return -1
            if (b.version_id === promptState.active_version_id) return 1
            return 0
        })
        : []
    const versionsPager = usePagination(sortedVersions, 10)
    const referencesPager = usePagination(references, 10)

    // Reseed the user-owned prompt textarea from the cached prompt only when it isn't
    // dirty, so a background revalidate (or another tab's activation) never wipes
    // unsaved edits. `lastSeededRef` tracks the value we last wrote into the textarea.
    const activePromptText = promptState?.active_prompt.prompt_text
    const lastSeededRef = useRef<string | null>(null)
    useEffect(() => {
        if (activePromptText === undefined) {
            return
        }
        setPromptText((current) => {
            if (current === activePromptText) {
                lastSeededRef.current = activePromptText
                return current
            }
            if (lastSeededRef.current === null || current === lastSeededRef.current) {
                lastSeededRef.current = activePromptText
                return activePromptText
            }
            return current
        })
    }, [activePromptText])

    const submitReferences = async () => {
        if (!api) {
            return
        }
        const urls = uniqueLines(urlInput)
        if (urls.length === 0) {
            setError("Add at least one Instagram Reel URL.")
            return
        }
        setIsSubmitting(true)
        setError(null)
        setStatus("Submitting references")
        try {
            await api.createSynthesisReferences(urls)
            setUrlInput("")
            setStatus(`${urls.length} reference${urls.length === 1 ? "" : "s"} queued`)
            loadSynthesis()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsSubmitting(false)
        }
    }

    const consolidateReferences = async () => {
        if (!api) {
            return
        }
        setIsConsolidating(true)
        setError(null)
        setStatus("Starting synthesis consolidation")
        try {
            const run = await api.createSynthesisConsolidation()
            const completed = await waitForRunCompletion(api, run, {
                onUpdate: (next) => {
                    setActiveRun(next)
                    setStatus(runDetail(next))
                },
            })
            setActiveRun(completed)
            setStatus("Prompt guidance updated")
            loadSynthesis()
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsConsolidating(false)
        }
    }

    const savePromptVersion = async () => {
        if (!api || !promptState) {
            return
        }
        setIsSaving(true)
        setError(null)
        setStatus("Saving prompt version")
        try {
            const next = await api.createSynthesisPromptVersion({
                label: versionLabel.trim() || DEFAULT_LABEL,
                prompt_text: promptText,
                generated_guidance: promptState.active_prompt.generated_guidance,
                source_reference_ids: completedReferences.map((reference) => reference.reference_id),
                activate: true,
            })
            setPromptState(next)
            setPromptText(next.active_prompt.prompt_text)
            setVersionLabel(DEFAULT_LABEL)
            setStatus("Prompt version saved")
        } catch (caught) {
            setError(errorMessage(caught))
        } finally {
            setIsSaving(false)
        }
    }

    const activateVersion = async (versionId: string) => {
        if (!api) {
            return
        }
        setError(null)
        setStatus("Activating prompt version")
        try {
            const next = await api.activateSynthesisPromptVersion(versionId)
            setPromptState(next)
            setPromptText(next.active_prompt.prompt_text)
            setStatus("Prompt version activated")
        } catch (caught) {
            setError(errorMessage(caught))
        }
    }

    if (!isLoaded) {
        return <DashboardPage eyebrow="Synthesis" title="Loading synthesis"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Synthesis" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to tune synthesis.</div>
            </DashboardPage>
        )
    }


    return (
        <DashboardPage
            eyebrow="Synthesis"
            title="Reference learning"
            subtitle="Edit the active system prompt directly. Queue Instagram Reel references below to teach new patterns."
            action={
                <>
                    <button className={styles.ghostButton} type="button" onClick={loadSynthesis}>
                        <RefreshCw size={16} /> Refresh
                    </button>
                    <button className={styles.primaryButton} type="button" onClick={savePromptVersion} disabled={isSaving || !promptText.trim()}>
                        <Save size={16} /> {isSaving ? "Saving" : "Save new version"}
                    </button>
                </>
            }
        >
            {(error || loadError || status) && (
                <div className={styles.fieldStack}>
                    {status && !error && !loadError && <div className={styles.successBanner}>{status}</div>}
                    {(error || loadError) && <div className={styles.errorBanner}>{error || loadError}</div>}
                </div>
            )}

            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Effective system prompt</h2>
                            <p>Active version: {promptState?.active_version_id || "loading"}</p>
                        </div>
                        <StatusBadge label={promptChanged ? "edited" : "active"} tone={promptChanged ? "queued" : "completed"} />
                    </div>
                    <div className={styles.fieldStack}>
                        <label className={styles.fieldLabel}>
                            Version label
                            <input
                                className={styles.input}
                                value={versionLabel}
                                onChange={(event) => setVersionLabel(event.target.value)}
                            />
                        </label>
                        <textarea
                            className={`${styles.textarea} ${styles.promptTextarea}`}
                            value={promptText}
                            onChange={(event) => setPromptText(event.target.value)}
                        />
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Versions</h2>
                            <p>{promptState?.versions.length ?? 0} saved</p>
                        </div>
                    </div>
                    {!promptState || sortedVersions.length === 0 ? (
                        <div className={styles.emptyState}>No prompt versions loaded.</div>
                    ) : (
                        <>
                        <ul className={styles.versionList}>
                            {versionsPager.pageItems.map((version) => {
                                const isActive = version.version_id === promptState.active_version_id
                                return (
                                    <li className={styles.listCard} key={version.version_id}>
                                        <div className={styles.cardTop}>
                                            <div>
                                                <h3>{version.label}</h3>
                                                <p className={styles.smallText}>{formatDate(version.created_at)}</p>
                                            </div>
                                            <StatusBadge label={isActive ? "active" : "saved"} tone={isActive ? "completed" : undefined} />
                                        </div>
                                        {!isActive && (
                                            <div className={styles.cardActions}>
                                                <button className={styles.secondaryButton} type="button" onClick={() => activateVersion(version.version_id)}>
                                                    <RotateCcw size={16} /> Activate
                                                </button>
                                            </div>
                                        )}
                                    </li>
                                )
                            })}
                        </ul>
                        <Pager
                            page={versionsPager.page}
                            pageCount={versionsPager.pageCount}
                            onPrev={versionsPager.prev}
                            onNext={versionsPager.next}
                        />
                        </>
                    )}
                </div>

                <div className={`${styles.full}`}>
                    <div className={`${styles.disclosure} ${refsOpen ? styles.disclosureOpen : ""}`}>
                        <button
                            type="button"
                            className={styles.disclosureToggle}
                            onClick={() => setRefsOpen((current) => !current)}
                            aria-expanded={refsOpen}
                        >
                            <span>References &amp; guidance · {completedReferences.length} of {references.length} complete</span>
                            <span className={styles.disclosureCaret} aria-hidden>+</span>
                        </button>
                        {refsOpen && (
                            <div className={styles.disclosureBody}>
                                <div className={`${styles.panel} ${styles.side}`}>
                                    <div className={styles.panelHeader}>
                                        <div>
                                            <h2>Reel intake</h2>
                                            <p>One URL per line.</p>
                                        </div>
                                    </div>
                                    <div className={styles.fieldStack}>
                                        <label className={styles.fieldLabel}>
                                            Instagram Reel URLs
                                            <textarea
                                                className={styles.textarea}
                                                placeholder="https://www.instagram.com/reel/..."
                                                value={urlInput}
                                                onChange={(event) => setUrlInput(event.target.value)}
                                            />
                                        </label>
                                        <button className={styles.primaryButton} type="button" onClick={submitReferences} disabled={isSubmitting}>
                                            <Link size={16} /> {isSubmitting ? "Queueing" : "Queue references"}
                                        </button>
                                        <button className={styles.secondaryButton} type="button" onClick={consolidateReferences} disabled={isConsolidating || completedReferences.length === 0}>
                                            <Sparkles size={16} /> {isConsolidating ? "Consolidating" : "Consolidate"}
                                        </button>
                                    </div>
                                </div>

                                <div className={`${styles.panel} ${styles.wide}`}>
                                    <div className={styles.panelHeader}>
                                        <div>
                                            <h2>Reference queue</h2>
                                            <p>{completedReferences.length} complete of {references.length} total</p>
                                        </div>
                                        {activeRun && <StatusBadge label={activeRun.status} tone={activeRun.status} />}
                                    </div>
                                    {references.length === 0 ? (
                                        <div className={styles.emptyState}>No references submitted yet.</div>
                                    ) : (
                                        <>
                                        <ul className={styles.referenceList}>
                                            {referencesPager.pageItems.map((reference) => (
                                                <li className={styles.listCard} key={reference.reference_id}>
                                                    <div className={styles.cardTop}>
                                                        <div>
                                                            <h3>{reference.title || reference.url}</h3>
                                                            <p className={styles.smallText}>{reference.author || "Unknown creator"} · {formatDate(reference.updated_at)}</p>
                                                        </div>
                                                        <StatusBadge label={reference.status} tone={reference.status} />
                                                    </div>
                                                    {reference.last_error && <div className={styles.errorBanner}>{reference.last_error}</div>}
                                                    {Object.keys(reference.metrics).length > 0 && (
                                                        <pre className={styles.codeBlock}>{JSON.stringify(reference.metrics, null, 2)}</pre>
                                                    )}
                                                </li>
                                            ))}
                                        </ul>
                                        <Pager
                                            page={referencesPager.page}
                                            pageCount={referencesPager.pageCount}
                                            onPrev={referencesPager.prev}
                                            onNext={referencesPager.next}
                                        />
                                        </>
                                    )}
                                </div>

                                <div className={`${styles.panel} ${styles.full}`}>
                                    <div className={styles.panelHeader}>
                                        <div>
                                            <h2>Generated guidance</h2>
                                            <p>Latest consolidated learning from completed references.</p>
                                        </div>
                                    </div>
                                    {activePrompt?.generated_guidance ? (
                                        <pre className={styles.codeBlock}>{activePrompt.generated_guidance}</pre>
                                    ) : (
                                        <div className={styles.emptyState}>Run consolidation after references complete to generate guidance.</div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </section>
        </DashboardPage>
    )
}

function uniqueLines(value: string) {
    return Array.from(new Set(value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)))
}

function runDetail(run: RunManifest) {
    return run.current_step
        ? `${humanizeLabel(run.status)} · ${humanizeLabel(run.current_step)}`
        : humanizeLabel(run.status)
}
