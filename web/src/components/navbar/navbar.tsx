"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import styles from "./navbar.module.css"

export default function Navbar() {
    const [scrolled, setScrolled] = useState(false)

    useEffect(() => {
        const onScroll = () => setScrolled(window.scrollY > 50)
        window.addEventListener("scroll", onScroll, { passive: true })
        return () => window.removeEventListener("scroll", onScroll)
    }, [])

    return <div className={`${styles.navbarContainer} ${scrolled ? styles.scrolled : ""}`}>
        <header className={styles.navbar}>
            <div className={styles.navLeft}>
                <Link className={styles.logo} href="/">
                    Eclypte
                </Link>
            </div>
            <nav className={styles.navRight}>
                <ul className={styles.navList}>
                    <li>
                        <Link className={styles.navLink} href="/editor">Editor</Link>
                    </li>
                    <li>
                        <Link className={styles.navLink} href="/pricing">Pricing</Link>
                    </li>
                    <li>
                        <Link className={styles.navLink} href="/signup">
                            Create
                        </Link>
                    </li>
                </ul>
            </nav>
        </header>
        
    </div>
}