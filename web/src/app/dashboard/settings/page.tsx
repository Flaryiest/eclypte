"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { RefreshCw } from "lucide-react"
import { DashboardPage, StatusBadge, formatDate } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    ECLYPTE_API_BASE_URL,
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

    const checkSettings = useCallback(async () => {
        if (!api) {
            return
        }
        setIsChecking(true)
        setError(null)
        try {
            const [healthResponse, prompt] = await Promise.all([
                api.health(),
                api.getSynthesisPrompt(),
            ])
            setHealth(healthResponse.ok ? "ok" : "failed")
            setHealthDetails(healthResponse)
            setPromptState(prompt)
        } catch (caught) {
            setHealth("failed")
            setHealthDetails(null)
            setError(errorMessage(caught))
        } finally {
            setIsChecking(false)
        }
    }, [api])

    useEffect(() => {
        void checkSettings()
    }, [checkSettings])

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
            title="Workspace settings"
            subtitle="Current frontend and API wiring for this signed-in creator session."
            action={
                <button className={styles.secondaryButton} type="button" onClick={checkSettings} disabled={isChecking}>
                    <RefreshCw size={16} /> {isChecking ? "Checking" : "Check health"}
                </button>
            }
        >
            {error && <div className={styles.errorBanner}>{error}</div>}

            <div className={styles.settingsStack}>
                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>API connection</h2>
                        <StatusBadge
                            label={health}
                            tone={health === "ok" ? "completed" : health === "failed" ? "failed" : undefined}
                        />
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Base URL</span>
                        <span className={`${styles.settingsRowValue} ${styles.settingsRowMono}`}>{ECLYPTE_API_BASE_URL}</span>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>Signed-in as</span>
                        <span className={`${styles.settingsRowValue} ${styles.settingsRowMono}`}>{user.id}</span>
                    </div>
                    <div className={styles.settingsRow}>
                        <span className={styles.settingsRowLabel}>YouTube cookies</span>
                        <span className={styles.settingsRowValue}>{healthDetails?.youtube_cookies_configured ? "Configured" : "Not configured"}</span>
                    </div>
                </div>

                <div className={styles.settingsGroup}>
                    <div className={styles.settingsGroupHeader}>
                        <h2 className={styles.settingsGroupTitle}>Synthesis prompt</h2>
                    </div>
                    {promptState ? (
                        <>
                            <div className={styles.settingsRow}>
                                <span className={styles.settingsRowLabel}>Active version</span>
                                <span className={`${styles.settingsRowValue} ${styles.settingsRowMono}`}>{promptState.active_version_id}</span>
                            </div>
                            <div className={styles.settingsRow}>
                                <span className={styles.settingsRowLabel}>Label</span>
                                <span className={styles.settingsRowValue}>{promptState.active_prompt.label}</span>
                            </div>
                            <div className={styles.settingsRow}>
                                <span className={styles.settingsRowLabel}>Updated</span>
                                <span className={styles.settingsRowValue}>{formatDate(promptState.active_prompt.created_at)}</span>
                            </div>
                        </>
                    ) : (
                        <div className={styles.emptyState}>Prompt state has not loaded yet.</div>
                    )}
                </div>
            </div>
        </DashboardPage>
    )
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
