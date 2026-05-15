"use client"

import { useClerk } from "@clerk/nextjs"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LogOut } from "lucide-react"
import styles from "./sidebar.module.css"

type SidebarProps = {
    isOpen: boolean
    onToggle: () => void
}

type SidebarItem = {
    id: string
    letter: string
    label: string
    href: string
}

const sidebarItems: SidebarItem[] = [
    { id: "new-edit", letter: "A", label: "New edit", href: "/dashboard/new-edit" },
    { id: "assets", letter: "B", label: "Assets", href: "/dashboard/assets" },
    { id: "automation", letter: "C", label: "Automation", href: "/dashboard/automation" },
    { id: "synthesis", letter: "D", label: "Synthesis", href: "/dashboard/synthesis" },
    { id: "renders", letter: "E", label: "Renders", href: "/dashboard/renders" },
    { id: "settings", letter: "F", label: "Settings", href: "/dashboard/settings" },
]

export default function Sidebar({ isOpen, onToggle }: SidebarProps) {
    const { signOut } = useClerk()
    const pathname = usePathname()

    const handleLogout = async () => {
        await signOut({ redirectUrl: "/" })
    }

    return (
        <aside
            id="dashboard-sidebar"
            className={`${styles.sidebar} ${isOpen ? styles.expanded : styles.minimized}`}
        >
            <div className={styles.header}>
                <span className={styles.brandText}>Eclypte</span>
            </div>

            <nav className={styles.nav} aria-label="Sidebar navigation">
                <ul className={styles.list}>
                    {sidebarItems.map((item) => {
                        const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
                        return (
                            <li key={item.id}>
                                <Link
                                    className={`${styles.navItem} ${active ? styles.active : ""}`}
                                    href={item.href}
                                    onClick={() => {
                                        if (typeof window !== "undefined" && window.matchMedia("(max-width: 768px)").matches) {
                                            onToggle()
                                        }
                                    }}
                                    aria-label={item.label}
                                >
                                    <span className={styles.navLetter}>{item.letter}</span>
                                    <span className={styles.navLabel}>{item.label}</span>
                                </Link>
                            </li>
                        )
                    })}
                </ul>
            </nav>

            <div className={styles.footer}>
                <div className={styles.statusRow}>
                    <span className={styles.statusDot} aria-hidden />
                    <span className={styles.statusText}>Creator</span>
                </div>

                <button
                    type="button"
                    className={styles.logoutButton}
                    onClick={handleLogout}
                    aria-label="Sign out"
                >
                    <span className={styles.logoutIcon}>
                        <LogOut size={16} strokeWidth={1.6} />
                    </span>
                    <span className={styles.logoutLabel}>Sign out</span>
                </button>
            </div>
        </aside>
    )
}
