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
                    forceRedirectUrl="/dashboard"
                    appearance={{
                        variables: {
                            colorPrimary: "#e8a838",
                            colorBackground: "transparent",
                            colorText: "#ffffff",
                            colorTextSecondary: "#cacaca",
                            colorInputBackground: "rgba(255, 255, 255, 0.03)",
                            colorInputText: "#ffffff",
                            colorDanger: "#ff6b6b",
                            colorSuccess: "#e8a838",
                            colorNeutral: "#cacaca",
                            fontFamily: "var(--font-neue), var(--font-outfit), system-ui, sans-serif",
                            fontSize: "0.95rem",
                            borderRadius: "0.6rem",
                        },
                        elements: {
                            rootBox: {
                                width: "100%",
                                display: "flex",
                                justifyContent: "center",
                            },
                            card: {
                                background: "transparent",
                                boxShadow: "none",
                                border: "none",
                                padding: 0,
                                width: "100%",
                            },
                            headerTitle: {
                                fontFamily: "var(--font-eiko)",
                                fontSize: "1.8rem",
                                fontWeight: 500,
                                color: "#ffffff",
                                letterSpacing: "-0.01em",
                            },
                            headerSubtitle: {
                                fontFamily: "var(--font-neue)",
                                color: "#cacaca",
                                fontSize: "0.95rem",
                            },
                            socialButtonsBlockButton: {
                                background: "rgba(255, 255, 255, 0.03)",
                                border: "1px solid rgba(255, 255, 255, 0.08)",
                                color: "#ffffff",
                                transition: "background 0.2s ease, border-color 0.2s ease",
                                "&:hover": {
                                    background: "rgba(255, 255, 255, 0.06)",
                                    borderColor: "rgba(232, 168, 56, 0.3)",
                                },
                            },
                            socialButtonsBlockButtonText: {
                                color: "#ffffff",
                                fontWeight: 500,
                            },
                            dividerLine: {
                                background: "rgba(255, 255, 255, 0.08)",
                            },
                            dividerText: {
                                color: "#cacaca",
                                fontSize: "0.85rem",
                            },
                            formFieldLabel: {
                                color: "#f0f0f0",
                                fontWeight: 500,
                                fontSize: "0.9rem",
                            },
                            formFieldInput: {
                                background: "rgba(255, 255, 255, 0.03)",
                                border: "1px solid rgba(255, 255, 255, 0.08)",
                                color: "#ffffff",
                                transition: "border-color 0.2s ease, box-shadow 0.2s ease",
                                "&:focus": {
                                    borderColor: "rgba(232, 168, 56, 0.5)",
                                    boxShadow: "0 0 0 3px rgba(232, 168, 56, 0.12)",
                                },
                            },
                            formButtonPrimary: {
                                background: "#e8a838",
                                color: "#000000",
                                fontWeight: 600,
                                fontFamily: "var(--font-outfit), var(--font-neue), sans-serif",
                                textTransform: "none",
                                letterSpacing: "0",
                                boxShadow: "0px 2px 24px 4px rgba(232, 168, 56, 0.18)",
                                transition: "transform 0.2s ease, box-shadow 0.2s ease",
                                "&:hover": {
                                    background: "#f0b845",
                                    boxShadow: "0px 2px 30px 6px rgba(232, 168, 56, 0.28)",
                                    transform: "translateY(-1px)",
                                },
                                "&:focus": {
                                    boxShadow: "0 0 0 3px rgba(232, 168, 56, 0.25)",
                                },
                            },
                            footerActionText: {
                                color: "#cacaca",
                            },
                            footerActionLink: {
                                color: "#e8a838",
                                fontWeight: 500,
                                "&:hover": {
                                    color: "#f0b845",
                                },
                            },
                            identityPreviewText: {
                                color: "#ffffff",
                            },
                            identityPreviewEditButton: {
                                color: "#e8a838",
                            },
                            formFieldAction: {
                                color: "#e8a838",
                            },
                            formFieldHintText: {
                                color: "#cacaca",
                            },
                            footer: {
                                background: "transparent",
                            },
                        },
                    }}
                />
            </div>
        </div>
    )
}
