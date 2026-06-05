import Link from "next/link"
import styles from "./demo.module.css"
import Navbar from "@components/navbar/navbar"
import Footer from "@components/footer/footer"
import Reveal from "@components/reveal/reveal"
import StepCard from "@components/stepCard/stepCard"
import CtaShapes from "@components/ctaShapes/ctaShapes"
import { DemoReel, DemoTile } from "@/components/demo/demoPlayer"

export default function DemoPage() {
    return (
        <div className={styles.page}>
            <Navbar />
            <main className={styles.main}>
                <section className={styles.hero}>
                    <p className={styles.eyebrow}>Demo Reel</p>
                    <h1 className={styles.title}>
                        See Eclypte
                        <br />
                        in motion.
                    </h1>
                    <p className={styles.subtitle}>
                        One song. One source clip. A finished AMV — cut to the beat by the agent,
                        rendered in the cloud.
                    </p>
                </section>

                <DemoReel>
                    <section className={styles.featuredSection}>
                        <div className={styles.featuredFrame}>
                            <DemoTile
                                id="babydoll"
                                featured
                                src="/demo/web/Babydoll.mp4"
                                poster="/demo/posters/Babydoll.webp"
                                label="Babydoll × Project Hail Mary"
                            />
                        </div>
                        <div className={styles.featuredMeta}>
                            <p className={styles.featuredTag}>Featured cut</p>
                            <h2 className={styles.featuredTitle}>
                                Babydoll <span className={styles.cross}>×</span> Project Hail Mary
                            </h2>
                            <ul className={styles.metaRow}>
                                <li>Song · Babydoll</li>
                                <li>Source · Project Hail Mary</li>
                                <li>0:48</li>
                                <li>1080p</li>
                            </ul>
                            <p className={styles.featuredBlurb}>
                                Impact frames land on the downbeats, holds breathe through the verse.
                                Press play — nothing loads until you do.
                            </p>
                        </div>
                    </section>

                    <section className={styles.gallerySection}>
                        <div className={styles.sectionHead}>
                            <p className={styles.eyebrow}>The Gallery</p>
                            <h2 className={styles.sectionTitle}>More from the cutting room.</h2>
                        </div>
                        <Reveal className={styles.galleryGrid}>
                            <figure className={styles.galleryItem}>
                                <DemoTile
                                    id="shape"
                                    src="/demo/web/ShapeOfYou.mp4"
                                    poster="/demo/posters/ShapeOfYou.webp"
                                    label="Shape of You × Super Mario Galaxy"
                                />
                                <figcaption className={styles.tileCaption}>
                                    Shape of You <span className={styles.cross}>×</span> Super Mario Galaxy
                                </figcaption>
                            </figure>
                            <figure className={styles.galleryItem}>
                                <DemoTile
                                    id="headshot"
                                    src="/demo/web/Headshot.mp4"
                                    poster="/demo/posters/Headshot.webp"
                                    label="Headshot × Project Hail Mary"
                                />
                                <figcaption className={styles.tileCaption}>
                                    Headshot <span className={styles.cross}>×</span> Project Hail Mary
                                </figcaption>
                            </figure>
                            <figure className={`${styles.galleryItem} ${styles.galleryPortraitItem}`}>
                                <DemoTile
                                    id="mobile"
                                    orientation="portrait"
                                    src="/demo/web/ShapeOfYouMobile.mp4"
                                    poster="/demo/posters/ShapeOfYouMobile.webp"
                                    label="Shape of You — vertical Reels cut"
                                />
                                <figcaption className={styles.tileCaption}>
                                    Shape of You <span className={styles.cross}>·</span> Vertical / Reels
                                </figcaption>
                            </figure>
                        </Reveal>
                    </section>
                </DemoReel>

                <section className={styles.howSection}>
                    <div className={styles.sectionHead}>
                        <p className={styles.eyebrow}>How it was made</p>
                        <h2 className={styles.sectionTitle}>Three steps. No timeline scrubbing.</h2>
                    </div>
                    <Reveal className={styles.stepsGrid}>
                        <StepCard
                            number="01"
                            title="Upload your clips"
                            description="Drop in a source video and a song. WAV and MP4 in, the agent takes it from there."
                        />
                        <StepCard
                            number="02"
                            title="Choose your style"
                            description="Pick Reels or YouTube, set the trim and a creative brief. The agent matches cuts to the beat."
                        />
                        <StepCard
                            number="03"
                            title="Render & share"
                            description="Render in the cloud, preview instantly, and send straight to Instagram when it's ready."
                        />
                    </Reveal>
                </section>

                <section className={styles.ctaSection}>
                    <Reveal className={styles.cta}>
                        <CtaShapes>
                            <Link href="/dashboard" className={styles.ctaButton}>
                                Make your own →
                            </Link>
                        </CtaShapes>
                    </Reveal>
                </section>
            </main>
            <Footer />
        </div>
    )
}
