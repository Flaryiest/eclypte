import Link from "next/link"
import styles from "./navbar.module.css"
export default function Navbar() {
    return <div className={styles.navbarContainer}>
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
                        <Link className={styles.navLink} href="/about">About</Link>
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