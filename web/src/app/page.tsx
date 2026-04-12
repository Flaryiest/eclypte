import Navbar from "@components/navbar/navbar";
import styles from "./page.module.css";
import HeroLayers from "@/components/hero/heroLayers";
export default function Home() {
  return (
    <div className={styles.page}>
      <Navbar />
      <main className={styles.main}>
        <section className={styles.heroContainer}>
          <HeroLayers />
          <div className={styles.heroTextContainer}>
            <h1 className={styles.heroText}>Building Dreams.</h1>
            <h2 className={styles.heroDescription}>Creation is what makes us human. The ability to evoke emotion.</h2>
          </div>

        </section>
        <section className={styles.features}>
          <h2 className={styles.featuresTitle}>The future of creation is here.</h2>
        </section>
      </main>
    </div>
  );
}
