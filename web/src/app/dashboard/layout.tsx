"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useClerk } from "@clerk/nextjs"
import { LogOut, Settings } from "lucide-react"
import styles from "./layout.module.css"
import { ToastProvider } from "./dashboardCommon"

const navItems = [
    { href: "/dashboard", label: "Home" },
    { href: "/dashboard/assets", label: "Library" },
]

export default function Layout({ children }: { children: React.ReactNode }) {
    const pathname = usePathname()
    const { signOut } = useClerk()

    const isActive = (href: string) =>
        href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href)

    return (
        <div className={styles.container} data-surface="studio">
            {/* React hoists this into <head>: warm the API connection before the
                first data fetch (the media-host preconnect happens at runtime in
                posterUrls once the first signed URL reveals its origin). */}
            <link
                rel="preconnect"
                href={process.env.NEXT_PUBLIC_ECLYPTE_API_BASE_URL || "http://127.0.0.1:8000"}
                crossOrigin="anonymous"
            />
            <ToastProvider>
                <header className={styles.topBar}>
                    <Link className={styles.brand} href="/dashboard">
                        Eclypte
                    </Link>
                    <nav className={styles.nav} aria-label="Main">
                        {navItems.map((item) => (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={isActive(item.href) ? styles.navLinkActive : styles.navLink}
                                aria-current={isActive(item.href) ? "page" : undefined}
                            >
                                {item.label}
                            </Link>
                        ))}
                    </nav>
                    <div className={styles.topBarRight}>
                        <Link
                            href="/dashboard/settings"
                            className={isActive("/dashboard/settings") ? styles.navLinkActive : styles.navLink}
                            aria-label="Settings"
                            aria-current={isActive("/dashboard/settings") ? "page" : undefined}
                        >
                            <Settings size={17} aria-hidden />
                        </Link>
                        <button
                            type="button"
                            className={styles.signOut}
                            onClick={() => signOut({ redirectUrl: "/" })}
                            aria-label="Sign out"
                        >
                            <LogOut size={16} aria-hidden />
                        </button>
                    </div>
                </header>
                <main className={styles.main}>{children}</main>
            </ToastProvider>
        </div>
    )
}
