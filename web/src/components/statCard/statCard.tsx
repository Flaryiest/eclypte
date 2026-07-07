import styles from "./statCard.module.css";

type Props = {
    value: string;
    label: string;
    description: string;
};

export default function StatCard({ value, label, description }: Props) {
    return (
        <div className={styles.card}>
            {/* Not a heading: bare numbers ("10k+") pollute the document
                outline for screen-reader heading navigation. */}
            <p className={styles.value}>{value}</p>
            <div className={styles.cardText}>
                <p className={styles.label}>{label}</p>
                <p className={styles.description}>{description}</p>
            </div>
        </div>
    );
}
