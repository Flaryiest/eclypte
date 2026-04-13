import styles from "./stepCard.module.css"

type StepCardProps = {
    number: string
    title: string
    description: string
}

export default function StepCard({ number, title, description }: StepCardProps) {
    return (
        <div className={styles.card}>
            <span className={styles.number}>{number}</span>
            <h3 className={styles.title}>{title}</h3>
            <p className={styles.description}>{description}</p>
        </div>
    )
}
