"use client"

import { useEffect } from "react"
import { SignIn } from "@clerk/nextjs"
import styles from "./login.module.css"

type LoginProps = {
    onClose: () => void
}

export default function Login({ onClose }: LoginProps) {
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose()
        }
        window.addEventListener("keydown", onKey)
        return () => window.removeEventListener("keydown", onKey)
    }, [onClose])

    return (
        <div
            className={styles.container}
            onClick={(e) => {
                if (e.target === e.currentTarget) onClose()
            }}
        >
            <div className={styles.box}>
                <SignIn
                    routing="hash"
                    appearance={{
                        variables: {
                            colorPrimary: "#e8a838",
                            colorBackground: "transparent",
                            colorText: "#ffffff",
                        },
                        elements: {
                            rootBox: { width: "100%" },
                            card: {
                                background: "transparent",
                                boxShadow: "none",
                            },
                        },
                    }}
                />
            </div>
        </div>
    )
}
