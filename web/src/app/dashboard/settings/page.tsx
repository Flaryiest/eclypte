"use client"

import { useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { RefreshCw } from "lucide-react"
import { DashboardPage, StatusBadge, errorMessage, formatDate, isAbortError, useAbortableLoad } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    EclypteApiClient,
    HealthResponse,
    SynthesisPromptState,
} from "@/services/eclypteApi"

export default function SettingsPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [health, setHealth] = useState<"unknown" | "ok" | "failed">("unknown")
    const [healthDetails, setHealthDetails] = useState<HealthResponse | null>(null)
    const [promptState, setPromptState] = useState<SynthesisPromptState | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [isChecking, setIsChecking] = useState(false)

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

    return (
        <DashboardPage
            eyebrow="Settings"
            title="Settings"
            subtitle="Your account and connection status."
            action={
                <button className={styles.secondaryButton} type="button" onClick={checkSettings} disabled={isChecking}>
                    <RefreshCw size={16} /> {isChecking ? "Checking…" : "Refresh"}
                </button>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}

            <div className={styles.settingsStack}>
                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>Connection</h2>
                        <StatusBadge
                            label={health === "ok" ? "connected" : health === "failed" ? "offline" : health}
                            tone={health === "ok" ? "completed" : health === "failed" ? "failed" : undefined}
                        />
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Signed in as</span>
                        <span className={styles.settingsRowValue}>{user.primaryEmailAddress?.emailAddress ?? user.username ?? "—"}</span>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>YouTube access</span>
                        <span className={styles.settingsRowValue}>{healthDetails?.youtube_cookies_configured ? "Connected" : "Not set up"}</span>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Live updates</span>
                        <span className={styles.settingsRowValue}>{healthDetails?.realtime_streaming_configured ? "On" : "Standard"}</span>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Live progress</span>
                        <span className={styles.settingsRowValue}>{healthDetails?.worker_progress_configured ? "On" : "Standard"}</span>
                    </div>
                </div>

                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>Editing style</h2>
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
                </div>
            </div>
        </DashboardPage>
    )
}
