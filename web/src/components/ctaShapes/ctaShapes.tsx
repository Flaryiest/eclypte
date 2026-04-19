import styles from "./ctaShapes.module.css";
import { ReactNode } from "react";

type CtaShapesProps = {
    children: ReactNode;
};

export default function CtaShapes({ children }: CtaShapesProps) {
    return (
        <div className={styles.root}>
            {children}
            <span className={`${styles.shape} ${styles.frame} ${styles.s1}`} aria-hidden="true" />
            <span className={`${styles.shape} ${styles.play} ${styles.s2}`} aria-hidden="true" />
            <span className={`${styles.shape} ${styles.bars} ${styles.s3}`} aria-hidden="true">
                <span /><span /><span /><span />
            </span>
            <span className={`${styles.shape} ${styles.frame} ${styles.s4}`} aria-hidden="true" />
            <span className={`${styles.shape} ${styles.play} ${styles.s5}`} aria-hidden="true" />
            <span className={`${styles.shape} ${styles.frame} ${styles.s6}`} aria-hidden="true" />
            <span className={`${styles.shape} ${styles.bars} ${styles.s7}`} aria-hidden="true">
                <span /><span /><span /><span />
            </span>
            <span className={`${styles.shape} ${styles.frame} ${styles.s8}`} aria-hidden="true" />
        </div>
    );
}
