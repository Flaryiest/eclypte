"use client";

import { useEffect, useRef } from "react";
import styles from "./ambientLayers.module.css";

export default function AmbientLayers() {
    const containerRef = useRef<HTMLDivElement>(null);
    const rafRef = useRef<number>(0);

    useEffect(() => {
        let pending = false;

        const update = () => {
            pending = false;
            if (!containerRef.current) return;
            const opacity = Math.min(window.scrollY / 900, 1);
            containerRef.current.style.opacity = String(opacity);
        };

        const onScroll = () => {
            if (pending) return;
            pending = true;
            rafRef.current = requestAnimationFrame(update);
        };

        window.addEventListener("scroll", onScroll, { passive: true });
        update();

        return () => {
            window.removeEventListener("scroll", onScroll);
            cancelAnimationFrame(rafRef.current);
        };
    }, []);

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
