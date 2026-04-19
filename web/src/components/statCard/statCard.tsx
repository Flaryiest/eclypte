import styles from "./statCard.module.css";

type Props = {
    value: string;
    label: string;
    description: string;
};

export default function StatCard({ value, label, description }: Props) {
    return (
        <div className={styles.card}>
            <h3 className={styles.value}>{value}</h3>
            <div className={styles.cardText}>
                <p className={styles.label}>{label}</p>
                <p className={styles.description}>{description}</p>
            </div>
        </div>
    );
}
