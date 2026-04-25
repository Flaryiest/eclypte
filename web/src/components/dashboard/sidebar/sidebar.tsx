"use client"

import { useClerk } from "@clerk/nextjs"
import Link from "next/link"
import { usePathname } from "next/navigation"
import type { ComponentType } from "react"
import {
    Clapperboard,
    Download,
    FolderUp,
    LogOut,
    PanelLeftClose,
    PanelLeftOpen,
    Settings,
    Sparkles,
} from "lucide-react"
import styles from "./sidebar.module.css"

type SidebarProps = {
    isOpen: boolean
    onToggle: () => void
}

type SidebarItem = {
    id: string
    label: string
    href: string
    Icon: ComponentType<{ size?: number; strokeWidth?: number }>
}

const sidebarItems: SidebarItem[] = [
    {
        id: "new-edit",
        label: "New Edit",
        href: "/dashboard/new-edit",
        Icon: Clapperboard,
    },
    {
        id: "assets",
        label: "Assets",
        href: "/dashboard/assets",
        Icon: FolderUp,
    },
    {
        id: "synthesis",
        label: "Synthesis",
        href: "/dashboard/synthesis",
        Icon: Sparkles,
    },
    {
        id: "renders",
        label: "Renders",
        href: "/dashboard/renders",
        Icon: Download,
    },
    {
        id: "settings",
        label: "Settings",
        href: "/dashboard/settings",
        Icon: Settings,
    },
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
                <button
                    type="button"
                    className={styles.toggleButton}
                    onClick={onToggle}
                    aria-label={isOpen ? "Minimize sidebar" : "Expand sidebar"}
                >
                    {isOpen ? <PanelLeftClose size={20} /> : <PanelLeftOpen size={20} />}
                </button>

                <div className={styles.brandRow}>
                    <span className={styles.brandText}>Eclypte</span>
                </div>
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
                                    title={!isOpen ? item.label : undefined}
                                >
                                <span className={styles.icon}>
                                    <item.Icon size={20} strokeWidth={2} />
                                </span>
                                <span className={styles.label}>{item.label}</span>
                                </Link>
                            </li>
                        )
                    })}
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
                        <LogOut size={18} strokeWidth={2} />
                    </span>
                    <span className={styles.logoutLabel}>Log out</span>
                </button>
            </div>
        </aside>
    )
}
