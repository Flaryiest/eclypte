import Navbar from "@components/navbar/navbar";
import styles from "./page.module.css";
export default function Home() {
  return (
    <div className={styles.page}>
      <Navbar />
      <main className={styles.main}>
        <section className={styles.heroContainer}>
          <h1 className={styles.heroText}>Building Dreams.</h1>
          <h2 className={styles.heroDescription}>Creation is what makes us human. The ability to feel emotion.</h2>
        </section>
      </main>
    </div>
  );
}
