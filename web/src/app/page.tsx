import Navbar from "@components/navbar/navbar";
import styles from "./page.module.css";
import HeroLayers from "@/components/hero/heroLayers";
import StepCard from "@components/stepCard/stepCard";
import StatCard from "@components/statCard/statCard";
import Reveal from "@components/reveal/reveal";

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
        <section id="steps" className={styles.stepsContainer}>
          <Reveal className={styles.stepsTextContainer}>
            <h2 className={styles.stepsTitle}>Get your content in front of your audience</h2>
            <p className={styles.stepsDescription}>We help you reach your audience through transforming snippets of your work into engaging experiences. From movies to music to literature, we help with all.</p>
          </Reveal>
          <Reveal className={styles.stepsGrid}>
            <StepCard
              number="01"
              title="Upload Your Clips"
              description="Import your raw footage, anime clips, or any video content. We handle all formats so you can focus on the creative."
            />
            <StepCard
              number="02"
              title="Choose Your Style"
              description="Pick a mood, genre, and song. Our AI analyzes rhythm and emotion to match cuts with the music."
            />
            <StepCard
              number="03"
              title="Export & Share"
              description="Render your AMV in cinematic quality. Share directly to YouTube, TikTok, or download for your portfolio."
            />
          </Reveal>
        </section>
        <section className={styles.aboutBand}>
          <div className={styles.aboutContainer}>
            <h2 className={styles.aboutTitle}>Crafted for Creators, by Creators</h2>
            <p className={styles.aboutDescription}>Eclypte was born from a passion for anime and a desire to empower creators. We understand the love and effort that goes into every cut, every beat. Our mission is to make AMV creation accessible, intuitive, and fun for everyone.</p>
          </div>
        </section>
        <section className={styles.statsContainer}>
          <h2 className={styles.statsTitle}>Growth in days, not years</h2>
          <div className={styles.statsGrid}>
            <StatCard value="10k+" label="AMVs Created" description="Creators have produced thousands of AMVs using our AI-powered editing pipeline." />
            <StatCard value="250k+" label="Followers Gained" description="Our creators have grown their audiences across YouTube, TikTok, and beyond." />
            <StatCard value="5M+" label="Video Views" description="Eclypte-made videos have captured millions of views worldwide." />
          </div>
        </section>
        <section className={styles.ctaContainer}></section>
      </main>
    </div>
  );
}
