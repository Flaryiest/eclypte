import styles from "./navbar.module.css"
export default function Navbar() {
    return <div className={styles.navbarContainer}>
        <header className={styles.navbar}>
            <div className={styles.navLeft}>
                <div className={styles.logo}>
                    Eclypte
                </div>
            </div>
            <nav className={styles.navRight}>
                <ul className={styles.navList}>
                    <li>
                        <a href="/editor">Editor</a>
                    </li>
                    <li>
                        <a href="/about">About</a>
                    </li>
                    <li>
                        <a href="/signup">Create</a>
                    </li>
                </ul>
            </nav>
        </header>
        
    </div>
}