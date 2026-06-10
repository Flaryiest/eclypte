"use client"

import { useEffect } from "react"
import { isAbortError } from "./dashboardCommon"
import type { EclypteApiClient, RunStreamMessage } from "@/services/eclypteApi"

const REFRESH_DEBOUNCE_MS = 150
const POLL_INTERVAL_MS = 1000

export function useRunStream({
    api,
    enabled,
    shouldRefresh,
    refresh,
}: {
    api: EclypteApiClient | null
    enabled: boolean
    shouldRefresh: (message: RunStreamMessage) => boolean
    refresh: () => void
}) {
    useEffect(() => {
        if (!api || !enabled) {
            return
        }
        const controller = new AbortController()
        let stopped = false
        let fallbackInterval: number | undefined
        let refreshTimeout: number | undefined
        const scheduleRefresh = () => {
            if (refreshTimeout !== undefined) {
                return
            }
            refreshTimeout = window.setTimeout(() => {
                refreshTimeout = undefined
                refresh()
            }, REFRESH_DEBOUNCE_MS)
        }
        void api.streamRunUpdates({
            signal: controller.signal,
            onMessage: (message) => {
                if (shouldRefresh(message)) {
                    scheduleRefresh()
                }
            },
        }).catch((caught) => {
            if (stopped || isAbortError(caught)) {
                return
            }
            fallbackInterval = window.setInterval(refresh, POLL_INTERVAL_MS)
        })
        return () => {
            stopped = true
            controller.abort()
            if (fallbackInterval !== undefined) {
                window.clearInterval(fallbackInterval)
            }
            if (refreshTimeout !== undefined) {
                window.clearTimeout(refreshTimeout)
            }
        }
    }, [api, enabled, shouldRefresh, refresh])
}
