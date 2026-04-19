"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import styles from "./navbar.module.css"
import Login from "@components/login/login"

export default function Navbar() {
    const [scrolled, setScrolled] = useState(false)
    const [showLogin, setShowLogin] = useState(false)

    useEffect(() => {
        const onScroll = () => setScrolled(window.scrollY > 50)
        window.addEventListener("scroll", onScroll, { passive: true })
        return () => window.removeEventListener("scroll", onScroll)
    }, [])

    useEffect(() => {
        if (window.location.hash.startsWith("#/")) setShowLogin(true)
    }, [])

    return (
        <>
            <div className={`${styles.navbarContainer} ${scrolled ? styles.scrolled : ""}`}>
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
                                <button
                                    type="button"
                                    className={`${styles.navLink} ${styles.navButton}`}
                                    onClick={() => setShowLogin(true)}
                                >
                                    Sign in
                                </button>
                            </li>
                        </ul>
                    </nav>
                </header>
            </div>
            {showLogin && <Login onClose={() => setShowLogin(false)} />}
        </>
    )
}
