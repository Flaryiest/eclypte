"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useUser } from "@clerk/nextjs"
import { RefreshCw, Server, UserRound } from "lucide-react"
import { DashboardPage, StatusBadge, formatDate } from "../dashboardCommon"
import styles from "../studio.module.css"
import {
    ECLYPTE_API_BASE_URL,
    EclypteApiClient,
    SynthesisPromptState,
} from "@/services/eclypteApi"

export default function SettingsPage() {
    const { isLoaded, isSignedIn, user } = useUser()
    const [health, setHealth] = useState<"unknown" | "ok" | "failed">("unknown")
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
            setPromptState(prompt)
        } catch (caught) {
            setHealth("failed")
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
            <section className={styles.grid}>
                <div className={`${styles.panel} ${styles.wide}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>API connection</h2>
                            <p>The dashboard sends Clerk user identity as an X-User-Id header.</p>
                        </div>
                        <StatusBadge label={health} tone={health === "ok" ? "completed" : health === "failed" ? "failed" : undefined} />
                    </div>
                    {error && <div className={styles.errorBanner}>{error}</div>}
                    <div className={styles.settingsGrid}>
                        <div className={styles.settingCard}>
                            <Server size={18} />
                            <div>
                                <span className={styles.settingLabel}>API base URL</span>
                                <span className={styles.monoText}>{ECLYPTE_API_BASE_URL}</span>
                            </div>
                        </div>
                        <div className={styles.settingCard}>
                            <UserRound size={18} />
                            <div>
                                <span className={styles.settingLabel}>Signed-in user ID</span>
                                <span className={styles.monoText}>{user.id}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className={`${styles.panel} ${styles.side}`}>
                    <div className={styles.panelHeader}>
                        <div>
                            <h2>Synthesis prompt</h2>
                            <p>Active version used by future prompt-aware workflows.</p>
                        </div>
                    </div>
                    {promptState ? (
                        <div className={styles.fieldStack}>
                            <div className={styles.settingCard}>
                                <div>
                                    <span className={styles.settingLabel}>Active version</span>
                                    <span className={styles.monoText}>{promptState.active_version_id}</span>
                                </div>
                            </div>
                            <div className={styles.settingCard}>
                                <div>
                                    <span className={styles.settingLabel}>Label</span>
                                    <span>{promptState.active_prompt.label}</span>
                                </div>
                            </div>
                            <div className={styles.settingCard}>
                                <div>
                                    <span className={styles.settingLabel}>Updated</span>
                                    <span>{formatDate(promptState.active_prompt.created_at)}</span>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className={styles.emptyState}>Prompt state has not loaded yet.</div>
                    )}
                </div>
            </section>
        </DashboardPage>
    )
}

function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : "Something went wrong"
}
