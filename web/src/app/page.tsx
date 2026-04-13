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
        <section className={styles.stepsContainer}>
          <div className={styles.stepsTextContainer}>
            <h2 className={styles.stepsTitle}>Get your content in front of your audience</h2>
            <p className={styles.stepsDescription}>We help you reach your audience through transforming snippets of your work into engaging experiences. From movies to music to literature, we help with all.</p>
          </div>
          <div className={styles.stepsGrid}>
            <div className={styles.stepCard}>
              <span className={styles.stepNumber}>01</span>
              <h3 className={styles.stepCardTitle}>Upload Your Clips</h3>
              <p className={styles.stepCardDescription}>Import your raw footage, anime clips, or any video content. We handle all formats so you can focus on the creative.</p>
            </div>
            <div className={styles.stepCard}>
              <span className={styles.stepNumber}>02</span>
              <h3 className={styles.stepCardTitle}>Choose Your Style</h3>
              <p className={styles.stepCardDescription}>Pick a mood, genre, and song. Our AI analyzes rhythm and emotion to match cuts with the music.</p>
            </div>
            <div className={styles.stepCard}>
              <span className={styles.stepNumber}>03</span>
              <h3 className={styles.stepCardTitle}>Export & Share</h3>
              <p className={styles.stepCardDescription}>Render your AMV in cinematic quality. Share directly to YouTube, TikTok, or download for your portfolio.</p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
