"use client"

import { useEffect, useRef } from "react"
import styles from "./heroLayers.module.css"

export default function HeroLayers() {
    const containerRef = useRef<HTMLDivElement>(null)
    const bgRef = useRef<HTMLDivElement>(null)
    const midRef = useRef<HTMLDivElement>(null)
    const fgRef = useRef<HTMLDivElement>(null)
    const rafRef = useRef<number>(0)
    const scrollRef = useRef(0)
    const mouseRef = useRef({ x: 0, y: 0 })

    useEffect(() => {
        const onScroll = () => {
            scrollRef.current = window.scrollY
            scheduleUpdate()
        }

        const onMouseMove = (e: MouseEvent) => {
            mouseRef.current = {
                x: (e.clientX / window.innerWidth - 0.5) * 2,
                y: (e.clientY / window.innerHeight - 0.5) * 2,
            }
            scheduleUpdate()
        }

        let pending = false
        function scheduleUpdate() {
            if (pending) return
            pending = true
            rafRef.current = requestAnimationFrame(() => {
                pending = false
                updateTransforms()
            })
        }

        function updateTransforms() {
            const scroll = scrollRef.current
            const { x: mx, y: my } = mouseRef.current

            // Scroll-driven zoom: starts at 1.15, eases toward 1.0 over 600px of scroll
            const zoomProgress = Math.min(scroll / 600, 1)
            const bgScale = 1.15 - 0.13 * zoomProgress
            const midScale = 1.1 - 0.1 * zoomProgress
            const fgScale = 1.12 - 0.12 * zoomProgress

            if (bgRef.current) {
                const tx = mx * 8
                const ty = scroll * -0.06 + my * 8
                bgRef.current.style.transform =
                    `translate3d(${tx}px, ${ty}px, 0) scale(${bgScale})`
            }

            if (midRef.current) {
                const tx = mx * 18
                const ty = scroll * -0.2 + my * 18
                midRef.current.style.transform =
                    `translate3d(${tx}px, ${ty}px, 0) scale(${midScale})`
            }

            if (fgRef.current) {
                const tx = mx * 30
                const ty = scroll * -0.35 + my * 30
                fgRef.current.style.transform =
                    `translate3d(${tx}px, ${ty}px, 0) scale(${fgScale})`
            }

            if (containerRef.current) {
                const opacity = Math.max(0, 1 - scroll / 900)
                containerRef.current.style.opacity = String(opacity)
            }
        }

        window.addEventListener("scroll", onScroll, { passive: true })
        window.addEventListener("mousemove", onMouseMove, { passive: true })

        return () => {
            window.removeEventListener("scroll", onScroll)
            window.removeEventListener("mousemove", onMouseMove)
            cancelAnimationFrame(rafRef.current)
        }
    }, [])

    return (
        <div
            ref={containerRef}
            className={styles.container}
        >
            {/* Background: hero image */}
            <div ref={bgRef} className={styles.layerBg}>
                <picture>
                    <source
                        media="(max-width: 768px)"
                        srcSet="/assets/hero/one-mobile.webp"
                    />
                    <img
                        src="/assets/hero/one.webp"
                        className={styles.heroImage}
                        alt=""
                        draggable={false}
                    />
                </picture>
            </div>

            {/* Midground: atmospheric orbs */}
            <div ref={midRef} className={styles.layerMid}>
                <div className={`${styles.orb} ${styles.orb1}`} />
                <div className={`${styles.orb} ${styles.orb2}`} />
                <div className={`${styles.orb} ${styles.orb3}`} />
            </div>

            {/* Foreground: particles + shooting stars */}
            <div ref={fgRef} className={styles.layerFg}>
                <div className={styles.particle} />
                <div className={styles.particle} />
                <div className={styles.particle} />
                <div className={styles.particle} />
                <div className={styles.particle} />
                <div className={styles.particle} />
                <div className={styles.particle} />
                <div className={styles.shootingStar} />
                <div className={styles.shootingStar2} />
                <div className={styles.shootingStar3} />
                <div className={styles.shootingStar4} />
                <div className={styles.shootingStar5} />
            </div>

            {/* Film grain */}
            <div className={styles.grain} />

            {/* Atmospheric overlays */}
            <div className={styles.vignette} />
            <div className={styles.bottomFade} />
            <div className={styles.topFade} />
        </div>
    )
}
