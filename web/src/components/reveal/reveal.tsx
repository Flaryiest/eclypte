"use client"

import { useEffect, useRef, useState, ReactNode } from "react"

type RevealProps = {
    children: ReactNode
    className?: string
    threshold?: number
}

export default function Reveal({ children, className, threshold = 0.2 }: RevealProps) {
    const [visible, setVisible] = useState(false)
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const el = ref.current
        if (!el) return

        // Progressive enhancement: content is visible by default; the
        // pre-reveal hidden state applies only once the observer is live
        // (set directly on the node — no render, and never during SSR/no-JS,
        // so sections can't end up permanently invisible).
        el.setAttribute("data-reveal-armed", "")
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setVisible(true)
                    observer.disconnect()
                }
            },
            { threshold }
        )

        observer.observe(el)
        return () => observer.disconnect()
    }, [threshold])

    return (
        <div ref={ref} className={className} data-revealed={visible || undefined}>
            {children}
        </div>
    )
}
