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
