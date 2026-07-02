"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useUser } from "@clerk/nextjs"
import { RefreshCw } from "lucide-react"
import { CopyableId, DashboardPage, Spinner, errorMessage, formatDate, isAbortError, useAbortableLoad } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    ECLYPTE_API_BASE_URL,
    EclypteApiClient,
    HealthResponse,
    SynthesisPromptState,
} from "@/services/eclypteApi"

// The backend's /healthz also reports whether always-on creation (autopilot)
// is running, but the shared HealthResponse type predates that field. Widen
// it locally rather than touching the shared API client contract.
type HealthDetails = HealthResponse & { autopilot_loop_configured?: boolean }

export default function SettingsPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [health, setHealth] = useState<"unknown" | "ok" | "failed">("unknown")
    const [healthDetails, setHealthDetails] = useState<HealthDetails | null>(null)
    const [promptState, setPromptState] = useState<SynthesisPromptState | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isChecking, setIsChecking] = useState(false)
    const [advancedOpen, setAdvancedOpen] = useState(false)

    const api = useMemo(() => user?.id ? new EclypteApiClient({ userId: user.id }) : null, [user?.id])

    const checkSettings = useAbortableLoad(async (signal) => {
        if (!api) {
            return
        }
        setIsChecking(true)
        setError(null)
        try {
            const [healthResponse, prompt] = await Promise.all([
                api.health(signal),
                api.getSynthesisPrompt(signal),
            ])
            setHealth(healthResponse.ok ? "ok" : "failed")
            setHealthDetails(healthResponse)
            setPromptState(prompt)
        } catch (caught) {
            if (isAbortError(caught)) {
                return
            }
            setHealth("failed")
            setHealthDetails(null)
            setError(errorMessage(caught))
        } finally {
            if (!signal.aborted) {
                setIsChecking(false)
            }
        }
    })

    useEffect(() => {
        checkSettings()
    }, [api, checkSettings])

    if (!isLoaded) {
        return <DashboardPage eyebrow="Settings" title="Loading settings"><div /></DashboardPage>
    }
    if (!isSignedIn || !user) {
        return (
            <DashboardPage eyebrow="Settings" title="Sign in required">
                <div className={styles.emptyState}>Sign in from the homepage to view settings.</div>
            </DashboardPage>
        )
    }

    // Binary diagnostic rows fall back to a dash while the health check is
    // still in flight or failed, instead of guessing a false "may be flaky".
    const flagText = (value: boolean | undefined, onText: string, offText: string) =>
        healthDetails ? (value ? onText : offText) : "—"

    return (
        <DashboardPage
            eyebrow="Settings"
            title="Settings"
            subtitle="Your account, connection, and creative defaults."
            action={
                <button className={styles.secondaryButton} type="button" onClick={checkSettings} disabled={isChecking}>
                    {isChecking ? <Spinner /> : <RefreshCw size={16} />} Refresh
                </button>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}

            <div className={styles.settingsStack}>
                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>Account</h2>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Signed in as</span>
                        <span className={styles.settingsRowValue}>
                            {user.fullName || user.username || "Your account"}
                            {user.primaryEmailAddress?.emailAddress ? ` (${user.primaryEmailAddress.emailAddress})` : ""}
                        </span>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Sign out</span>
                        <span className={styles.settingsRowValue}>Use the icon next to Settings in the top bar.</span>
                    </div>
                </div>

                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>Connection</h2>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Studio connection</span>
                        <span className={styles.settingsRowValue}>
                            <span className={styles.statusDot}>
                                <span
                                    className={styles.statusDotSwatch}
                                    style={{
                                        background:
                                            health === "ok" ? "var(--ok)" : health === "failed" ? "var(--danger)" : "var(--text-faint)",
                                    }}
                                    aria-hidden
                                />
                                {health === "ok" ? "Working" : health === "failed" ? "Not responding" : "Checking…"}
                            </span>
                        </span>
                    </div>
                </div>

                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>Creative style</h2>
                    </div>
                    {promptState ? (
                        <>
                            <div className={styles.settingsRow}>
                                <span className={styles.settingsRowLabel}>Active</span>
                                <span className={styles.settingsRowValue}>{promptState.active_prompt.label}</span>
                            </div>
                            <div className={styles.settingsRow}>
                                <span className={styles.settingsRowLabel}>Updated</span>
                                <span className={styles.settingsRowValue}>{formatDate(promptState.active_prompt.created_at)}</span>
                            </div>
                        </>
                    ) : (
                        <div className={styles.emptyState}>Still loading…</div>
                    )}
                    <Link className={styles.detailLink} href="/dashboard/synthesis">Tune how your reels are edited</Link>
                </div>

                <div className={styles.settingsGroup}>
                    <div className={`${styles.disclosure} ${advancedOpen ? styles.disclosureOpen : ""}`}>
                        <button
                            type="button"
                            className={styles.disclosureToggle}
                            onClick={() => setAdvancedOpen((current) => !current)}
                            aria-expanded={advancedOpen}
                        >
                            <span>Advanced</span>
                            <span className={styles.disclosureCaret} aria-hidden>+</span>
                        </button>
                        {advancedOpen && (
                            <div className={styles.disclosureBody}>
                                <div className={styles.full}>
                                    <div className={styles.settingsRow}>
                                        <span className={styles.settingsRowLabel}>API base URL</span>
                                        <span className={styles.settingsRowValue}>{ECLYPTE_API_BASE_URL}</span>
                                    </div>
                                    <div className={styles.settingsRow}>
                                        <span className={styles.settingsRowLabel}>Song imports</span>
                                        <span className={styles.settingsRowValue}>
                                            {flagText(healthDetails?.youtube_cookies_configured, "Ready", "May be flaky")}
                                        </span>
                                    </div>
                                    <div className={styles.settingsRow}>
                                        <span className={styles.settingsRowLabel}>Live updates</span>
                                        <span className={styles.settingsRowValue}>
                                            {flagText(healthDetails?.realtime_streaming_configured, "On", "Checking periodically")}
                                        </span>
                                    </div>
                                    <div className={styles.settingsRow}>
                                        <span className={styles.settingsRowLabel}>Detailed progress</span>
                                        <span className={styles.settingsRowValue}>
                                            {flagText(healthDetails?.worker_progress_configured, "On", "Off")}
                                        </span>
                                    </div>
                                    <div className={styles.settingsRow}>
                                        <span className={styles.settingsRowLabel}>Always-on creation</span>
                                        <span className={styles.settingsRowValue}>
                                            {flagText(healthDetails?.autopilot_loop_configured, "On", "Manual")}
                                        </span>
                                    </div>
                                    <div className={styles.settingsRow}>
                                        <span className={styles.settingsRowLabel}>Account ID</span>
                                        <span className={styles.settingsRowValue}>
                                            <CopyableId value={user.id} label="Copy account ID" />
                                        </span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </DashboardPage>
    )
}
