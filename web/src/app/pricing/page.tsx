import Link from "next/link"
import { Check } from "lucide-react"
import styles from "./pricing.module.css"
import Navbar from "@components/navbar/navbar"
import Footer from "@components/footer/footer"
import Reveal from "@components/reveal/reveal"

type Tier = {
    name: string
    price: string
    period: string
    tagline: string
    features: string[]
    cta: string
    featured?: boolean
}

const TIERS: Tier[] = [
    {
        name: "Free",
        price: "$0",
        period: "forever",
        tagline: "Cut your first AMVs and see the agent work.",
        features: ["3 edits / month", "1080p render", "Eclypte watermark", "Community support"],
        cta: "Start free",
    },
    {
        name: "Creator",
        price: "$12",
        period: "/ month",
        tagline: "For creators shipping reels on a schedule.",
        features: [
            "Unlimited edits",
            "4K render",
            "No watermark",
            "Publish straight to Instagram",
            "Priority render queue",
        ],
        cta: "Go Creator",
        featured: true,
    },
    {
        name: "Studio",
        price: "$29",
        period: "/ month",
        tagline: "For channels and teams running volume.",
        features: [
            "Everything in Creator",
            "Higher render concurrency",
            "Early access to new features",
            "Priority support",
        ],
        cta: "Go Studio",
    },
]

const FAQ: { q: string; a: string }[] = [
    {
        q: "What counts as an edit?",
        a: "One song paired with one source video, planned and rendered into a finished AMV. Re-rendering the same edit doesn't count again.",
    },
    {
        q: "Can I cancel anytime?",
        a: "Yes — plans are month to month. Cancel whenever and you keep access through the end of the billing period.",
    },
    {
        q: "What formats can I export?",
        a: "Reels 9:16 and YouTube 16:9 out of the box, with audio trimming and crop focus. WAV audio and MP4 video in.",
    },
    {
        q: "Who owns the videos?",
        a: "You do. Eclypte never claims rights to your renders — make sure you have the rights to the source material you upload.",
    },
]

function PricingCard({ tier }: { tier: Tier }) {
    const className = tier.featured ? `${styles.card} ${styles.cardFeatured}` : styles.card
    return (
        <article className={className}>
            {tier.featured && <span className={styles.popularTag}>Most popular</span>}
            {/* Heading so screen-reader users can jump between plans. */}
            <h2 className={styles.planName}>{tier.name}</h2>
            <p className={styles.price}>
                <span className={styles.priceNum}>{tier.price}</span>
                <span className={styles.pricePeriod}>{tier.period}</span>
            </p>
            <p className={styles.tagline}>{tier.tagline}</p>
            <ul className={styles.featureList}>
                {tier.features.map((feature) => (
                    <li key={feature} className={styles.feature}>
                        <Check size={16} className={styles.featureIcon} aria-hidden />
                        {feature}
                    </li>
                ))}
            </ul>
            <Link
                href="/dashboard"
                className={tier.featured ? `${styles.cardButton} ${styles.cardButtonPrimary}` : styles.cardButton}
            >
                {tier.cta}
            </Link>
        </article>
    )
}

export default function PricingPage() {
    return (
        <div className={styles.page}>
            <Navbar />
            <main className={styles.main}>
                <section className={styles.hero}>
                    <p className={styles.eyebrow}>Pricing</p>
                    <h1 className={styles.title}>
                        Simple, while
                        <br />
                        you create.
                    </h1>
                    <p className={styles.subtitle}>
                        Start free. Upgrade when you ship. No render is locked behind a contract.
                    </p>
                </section>

                <Reveal className={styles.tiers}>
                    {TIERS.map((tier) => (
                        <PricingCard key={tier.name} tier={tier} />
                    ))}
                </Reveal>

                <section className={styles.faqSection}>
                    <div className={styles.sectionHead}>
                        <p className={styles.eyebrow}>FAQ</p>
                        <h2 className={styles.sectionTitle}>The fine print.</h2>
                    </div>
                    <dl className={styles.faqList}>
                        {FAQ.map((item) => (
                            <div key={item.q} className={styles.faqRow}>
                                <dt className={styles.faqQ}>{item.q}</dt>
                                <dd className={styles.faqA}>{item.a}</dd>
                            </div>
                        ))}
                    </dl>
                </section>
            </main>
            <Footer />
        </div>
    )
}
