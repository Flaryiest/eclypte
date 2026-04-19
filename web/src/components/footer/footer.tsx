import styles from "./footer.module.css"
import Link from "next/link"
export default function Footer() {
    return <section className={styles.container}>
        <div className={styles.footer}>
            <div className={styles.top}>
                <div className={styles.left}>
                    <h3 className={styles.title}>Eclypte</h3>
                </div>
                <div className={styles.right}>
                    <div className={styles.resources}>
                        <h4 className={styles.resourcesTitle}>Resources</h4>
                        <ul className={styles.resourcesList}>
                            <li>
                                <Link className={styles.resourceLink} href="/editor">Editor</Link>
                            </li>
                            <li>
                                <Link className={styles.resourceLink} href="/pricing">Pricing</Link>
                            </li>
                            <li>
                                <a className={styles.resourceLink} href="/docs" target="_blank" rel="noopener noreferrer">Documentation</a>
                            </li>
                        </ul>
                    </div>
                    <div className={styles.legal}>
                        <h4 className={styles.legalTitle}>Legal</h4>
                        <ul className={styles.legalList}>
                            <li>
                                <a className={styles.legalLink} href="https://twitter.com/eclypte" target="_blank" rel="noopener noreferrer">Twitter</a>
                            </li>
                            <li>
                                <a className={styles.legalLink} href="https://linkedin.com/company/eclypte" target="_blank" rel="noopener noreferrer">LinkedIn</a>
                            </li>
                        </ul>
                    </div>
                    <div className={styles.contact}>
                        <h4 className={styles.contactTitle}>Contact Us</h4>
                        <p className={styles.contactInfo}>Email: info@eclypte.com</p>   
                    </div>
                </div>
            </div>
            <div className={styles.bottom}>
                <span className={styles.copyright}>© 2026 Eclypte. All rights reserved.</span>
            </div>
        </div>
    </section>
}