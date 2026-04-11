import Navbar from "@components/navbar/navbar";
import styles from "./page.module.css";
export default function Home() {
  return (
    <div className={styles.page}>
      <Navbar />
      <main className={styles.main}>
        <section className={styles.heroContainer}>
          <h1>Music, Movies, Magic</h1>
          <p>This is a simple landing page for the Eclypte application.</p>
        </section>
      </main>
    </div>
  );
}
