import { useEffect, useRef, useState } from "react"
import type { EclypteApiClient, FileVersionInput } from "@/services/eclypteApi"

export function posterKey(ref: FileVersionInput) {
    return `${ref.file_id}:${ref.version_id}`
}

// Resolves signed URLs for poster refs, once per ref. Signed URLs are never
// cached across sessions (they expire); within the page a fetched URL is kept
// for the component's lifetime, which is comfortably inside the expiry window.
export function usePosterUrls(
    api: EclypteApiClient | null,
    refs: (FileVersionInput | null | undefined)[],
): Record<string, string> {
    const [urls, setUrls] = useState<Record<string, string>>({})
    const inFlightRef = useRef<Set<string>>(new Set())
    const wanted = refs.filter((ref): ref is FileVersionInput => Boolean(ref)).map(posterKey).sort().join("|")

    useEffect(() => {
        if (!api || wanted === "") {
            return
        }
        let cancelled = false
        for (const key of wanted.split("|")) {
            if (urls[key] || inFlightRef.current.has(key)) {
                continue
            }
            inFlightRef.current.add(key)
            const [file_id, version_id] = key.split(":")
            void api
                .getDownloadUrl({ file_id, version_id })
                .then((download) => {
                    if (!cancelled) {
                        setUrls((current) => ({ ...current, [key]: download.download_url }))
                    }
                })
                .catch(() => undefined) // decorative — a missing thumb falls back to the gradient tile
                .finally(() => {
                    inFlightRef.current.delete(key)
                })
        }
        return () => {
            cancelled = true
        }
        // `urls` intentionally omitted: re-running on every resolved URL would refetch nothing
        // (guards above) but churn the effect; `wanted` captures the actual input identity.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [api, wanted])

    return urls
}
