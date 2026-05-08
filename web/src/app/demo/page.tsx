import styles from "./demo.module.css"
import Navbar from "@components/navbar/navbar";
export default function DemoPage() {
    return <div className={styles.page}>
        <Navbar/>
        <div className={styles.titleContainer}>
            <h1 className={styles.title}>Demoes</h1>
            <h2 className={styles.subtitle}>Check out our demoes to see Eclypte in action!</h2>
        </div>

        <div className={styles.videoContainer}>
            <h2 className={styles.videoTitle}>AMV Demo</h2>
            <div className={styles.videos}>
                <div className={styles.videoRow}>
                    <div className={styles.videoWrapper}>
                        <h3 className={styles.videoTitle}>Babydoll - Project Hail Mary</h3>
                        <video controls className={styles.horizontalVideo}>
                            <source src="/demo/Babydoll.mp4"></source>
                        </video>
                    </div>
                    <div className={styles.videoWrapper}>
                        <h3 className={styles.videoTitle}>Shape of You - Super Mario Galaxy Movie</h3>
                        <video controls className={styles.horizontalVideo}>
                            <source src="/demo/ShapeOfYou.mp4"></source>
                        </video>
                    </div>
                </div>
                <div className={styles.videoRow}>
                    <div className={styles.videoWrapper}>
                        <h3 className={styles.videoTitle}>Headshot - Project Hail Mary</h3>
                        <video controls className={styles.horizontalVideo}>
                            <source src="/demo/Headshot.mp4"></source>
                        </video>
                    </div>
                    <div className={styles.videoWrapper}>
                        <h3 className={styles.videoTitle}>Mobile - Shape of You - Super Mario Galaxy Movie</h3>
                        <video controls className={styles.verticalVideo}>
                            <source src="/demo/ShapeOfYouMobile.mp4"></source>
                        </video>
                    </div>
                </div>

            </div>

            
        </div>

    </div>
}