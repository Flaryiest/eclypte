"use client"

import { useState } from "react"
import { useClerk } from "@clerk/nextjs"
import styles from "./sidebar.module.css"

type SidebarProps = {
    isOpen: boolean
    onToggle: () => void
}

type SidebarItem = {
    id: string
    label: string
    paths: string[]
}

const sidebarItems: SidebarItem[] = [
    {
        id: "new-edit",
        label: "New Edit",
        paths: ["M12 5v14", "M5 12h14"]
    },
    {
        id: "projects",
        label: "Projects",
        paths: ["M3 7h18", "M3 12h18", "M3 17h18"]
    },
    {
        id: "assets",
        label: "Assets",
        paths: ["M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z", "m3.27 6.96 8.73 5.05 8.73-5.05", "M12 22.08V12"]
    },
    {
        id: "timeline",
        label: "Timeline",
        paths: ["M3 3v18", "M7 8h14", "M7 12h10", "M7 16h12"]
    },
    {
        id: "settings",
        label: "Settings",
        paths: ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6", "M19.4 15a1.65 1.65 0 0 0 .33 1.82", "m19.73 16.82-.06.06a2 2 0 1 1-2.83 2.83l-.06-.06", "M15 19.4a1.65 1.65 0 0 0-1 1.51", "M14 20.91V21a2 2 0 1 1-4 0v-.09", "M10 20.91A1.65 1.65 0 0 0 9 19.4", "m7.12.31-.06.06a2 2 0 1 1-2.83-2.83l.06-.06", "M4.6 15a1.65 1.65 0 0 0-1.51-1", "M3.09 14H3a2 2 0 1 1 0-4h.09", "M3.09 10A1.65 1.65 0 0 0 4.6 9", "m.31-7.12.06-.06a2 2 0 1 1 2.83 2.83l-.06.06", "M9 4.6a1.65 1.65 0 0 0 1-1.51", "M10 3.09V3a2 2 0 1 1 4 0v.09", "M14 3.09A1.65 1.65 0 0 0 15 4.6", "m7.12-.31.06.06a2 2 0 1 1-2.83 2.83l-.06-.06", "M19.4 9A1.65 1.65 0 0 0 20.91 10", "M20.91 10H21a2 2 0 1 1 0 4h-.09", "M20.91 14A1.65 1.65 0 0 0 19.4 15"]
    }
]

export default function Sidebar({ isOpen, onToggle }: SidebarProps) {
    const { signOut } = useClerk()
    const [activeItemId, setActiveItemId] = useState(sidebarItems[0].id)

    const handleLogout = async () => {
        await signOut({ redirectUrl: "/" })
    }

    return (
        <aside
            id="dashboard-sidebar"
            className={`${styles.sidebar} ${isOpen ? styles.expanded : styles.minimized}`}
        >
            <div className={styles.header}>
                <button
                    type="button"
                    className={styles.toggleButton}
                    onClick={onToggle}
                    aria-label={isOpen ? "Minimize sidebar" : "Expand sidebar"}
                >
                    {isOpen ? <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <path d="M15 18l-6-6 6-6" />
                    </svg> : <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <path d="M9 18l6-6-6-6" />
                    </svg>}
                </button>

                <div className={styles.brandRow}>
                    <span className={styles.brandText}>Eclypte</span>
                </div>
            </div>

            <nav className={styles.nav} aria-label="Sidebar navigation">
                <ul className={styles.list}>
                    {sidebarItems.map((item) => (
                        <li key={item.id}>
                            <button
                                type="button"
                                className={`${styles.navItem} ${activeItemId === item.id ? styles.active : ""}`}
                                onClick={() => setActiveItemId(item.id)}
                                title={!isOpen ? item.label : undefined}
                            >
                                <span className={styles.icon}>
                                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                                        {item.paths.map((path, index) => (
                                            <path key={`${item.id}-path-${index}`} d={path} />
                                        ))}
                                    </svg>
                                </span>
                                <span className={styles.label}>{item.label}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            </nav>

            <div className={styles.footer}>
                <div className={styles.statusRow}>
                    <span className={styles.statusDot} aria-hidden />
                    <span className={styles.statusText}>Creator mode</span>
                </div>

                <button
                    type="button"
                    className={styles.logoutButton}
                    onClick={handleLogout}
                >
                    <span className={styles.logoutIcon}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                            <polyline points="16 17 21 12 16 7" />
                            <line x1="21" y1="12" x2="9" y2="12" />
                        </svg>
                    </span>
                    <span className={styles.logoutLabel}>Log out</span>
                </button>
            </div>
        </aside>
    )
}