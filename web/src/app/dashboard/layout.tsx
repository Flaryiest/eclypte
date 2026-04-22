"use client"

import { useEffect, useState } from "react"
import styles from "./layout.module.css"
import Sidebar from "@/components/dashboard/sidebar/sidebar"

export default function Layout({ children }: { children: React.ReactNode }) {
    const [isMobile, setIsMobile] = useState(false)
    const [dashboardOpen, setDashboardOpen] = useState(true)

    useEffect(() => {
        const mediaQuery = window.matchMedia("(max-width: 768px)")

        const syncViewport = () => {
            const mobile = mediaQuery.matches
            setIsMobile(mobile)
            setDashboardOpen(!mobile)
        }

        syncViewport()
        mediaQuery.addEventListener("change", syncViewport)

        return () => mediaQuery.removeEventListener("change", syncViewport)
    }, [])

    return <div className={styles.container}>
            <Sidebar
                isOpen={dashboardOpen}
                onToggle={() => setDashboardOpen((prev) => !prev)}
            />
            <div className={styles.dashboard}>
                {isMobile && <button
                    type="button"
                    className={styles.mobileToggle}
                    onClick={() => setDashboardOpen((prev) => !prev)}
                    aria-controls="dashboard-sidebar"
                    aria-expanded={dashboardOpen}
                    aria-label={dashboardOpen ? "Close menu" : "Open menu"}
                >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <line x1="3" y1="12" x2="21" y2="12" />
                        <line x1="3" y1="6" x2="21" y2="6" />
                        <line x1="3" y1="18" x2="21" y2="18" />
                    </svg>
                    <span>Menu</span>
                </button>}
                {children}
            </div>

            {isMobile && dashboardOpen && <button
                type="button"
                className={styles.backdrop}
                aria-label="Close sidebar"
                onClick={() => setDashboardOpen(false)}
            />}
        </div>
}