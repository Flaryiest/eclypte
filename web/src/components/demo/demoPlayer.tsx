"use client"

import { createContext, useContext, useState, type ReactNode } from "react"
import { Play } from "lucide-react"
import styles from "./demoPlayer.module.css"

type ReelContext = {
    activeId: string | null
    setActiveId: (id: string | null) => void
}

const DemoReelContext = createContext<ReelContext>({
    activeId: null,
    setActiveId: () => {},
})

/**
 * Wraps the demo tiles and tracks which clip is playing so only ONE video is
 * ever mounted at a time. Everything else stays a cheap poster image.
 */
export function DemoReel({ children }: { children: ReactNode }) {
    const [activeId, setActiveId] = useState<string | null>(null)
    return (
        <DemoReelContext.Provider value={{ activeId, setActiveId }}>
            {children}
        </DemoReelContext.Provider>
    )
}

type DemoTileProps = {
    id: string
    src: string
    poster: string
    label: string
    orientation?: "landscape" | "portrait"
    featured?: boolean
}

export function DemoTile({
    id,
    src,
    poster,
    label,
    orientation = "landscape",
    featured = false,
}: DemoTileProps) {
    const { activeId, setActiveId } = useContext(DemoReelContext)
    const active = activeId === id
    const tileClass = [
        styles.tile,
        orientation === "portrait" ? styles.portrait : styles.landscape,
        featured ? styles.featured : "",
    ]
        .filter(Boolean)
        .join(" ")

    return (
        <div className={tileClass}>
            {active ? (
                <video
                    className={styles.media}
                    src={src}
                    poster={poster}
                    controls
                    autoPlay
                    playsInline
                    preload="auto"
                    onEnded={() => setActiveId(null)}
                />
            ) : (
                <button
                    type="button"
                    className={styles.posterButton}
                    onClick={() => setActiveId(id)}
                    aria-label={`Play ${label}`}
                >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img className={styles.media} src={poster} alt={label} loading="lazy" />
                    <span className={styles.scrim} aria-hidden />
                    <span className={styles.playIcon} aria-hidden>
                        <Play size={featured ? 30 : 22} fill="currentColor" strokeWidth={0} />
                    </span>
                    <span className={styles.ticks} aria-hidden />
                </button>
            )}
        </div>
    )
}
