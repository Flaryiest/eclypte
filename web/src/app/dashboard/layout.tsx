"use client"

import { useEffect, useState } from "react"
import { Menu } from "lucide-react"
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

    return (
        <div className={styles.container}>
            <Sidebar
                isOpen={dashboardOpen}
                onToggle={() => setDashboardOpen((prev) => !prev)}
            />
            <div className={styles.dashboard}>
                {isMobile && (
                    <button
                        type="button"
                        className={styles.mobileToggle}
                        onClick={() => setDashboardOpen((prev) => !prev)}
                        aria-controls="dashboard-sidebar"
                        aria-expanded={dashboardOpen}
                        aria-label={dashboardOpen ? "Close menu" : "Open menu"}
                    >
                        <Menu size={20} aria-hidden />
                        <span>Menu</span>
                    </button>
                )}
                {children}
            </div>

            {isMobile && dashboardOpen && (
                <button
                    type="button"
                    className={styles.backdrop}
                    aria-label="Close sidebar"
                    onClick={() => setDashboardOpen(false)}
                />
            )}
        </div>
    )
}
