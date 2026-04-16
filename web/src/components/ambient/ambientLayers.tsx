"use client";

import { useEffect, useRef } from "react";
import styles from "./ambientLayers.module.css";

type Props = {
    targetId: string;
    fadeDistance?: number;
    exitOffset?: number;
};

export default function AmbientLayers({ targetId, fadeDistance = 200, exitOffset = 600 }: Props) {
    const containerRef = useRef<HTMLDivElement>(null);
    const rafRef = useRef<number>(0);

    useEffect(() => {
        const target = document.getElementById(targetId);
        if (!target) return;

        let pending = false;

        const update = () => {
            pending = false;
            if (!containerRef.current) return;
            const rect = target.getBoundingClientRect();
            const vh = window.innerHeight;
            const enter = Math.min(Math.max((vh - rect.top) / fadeDistance, 0), 1);
            const exit = Math.min(Math.max((rect.bottom - exitOffset) / fadeDistance, 0), 1);
            containerRef.current.style.opacity = String(Math.min(enter, exit));
        };

        const onScroll = () => {
            if (pending) return;
            pending = true;
            rafRef.current = requestAnimationFrame(update);
        };

        window.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", onScroll);
        update();

        return () => {
            window.removeEventListener("scroll", onScroll);
            window.removeEventListener("resize", onScroll);
            cancelAnimationFrame(rafRef.current);
        };
    }, [targetId, fadeDistance, exitOffset]);

    return (
        <div
            ref={containerRef}
            className={styles.container}
            style={{ opacity: 0 }}
            aria-hidden
        >
            <div className={`${styles.orb} ${styles.orb1}`} />
            <div className={`${styles.orb} ${styles.orb2}`} />
            <div className={`${styles.orb} ${styles.orb3}`} />
            <div className={`${styles.orb} ${styles.orb4}`} />
            <div className={`${styles.orb} ${styles.orb5}`} />
            <div className={`${styles.orb} ${styles.orb6}`} />
            <div className={styles.particle} />
            <div className={styles.particle} />
            <div className={styles.particle} />
            <div className={styles.particle} />
            <div className={styles.particle} />
            <div className={styles.particle} />
            <div className={styles.particle} />
            <div className={styles.particle} />
        </div>
    );
}
