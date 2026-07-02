import { useEffect, useRef, useState } from "react"
import type { EclypteApiClient, FileVersionInput } from "@/services/eclypteApi"

export function posterKey(ref: FileVersionInput) {
    return `${ref.file_id}:${ref.version_id}`
}

// Resolves signed URLs for poster refs, once per ref. Signed URLs are never
// cached across sessions (they expire); within the page a fetched URL is kept
// for the component's lifetime, which is comfortably inside the expiry window.
// Keys are content-addressed (file id + version id), so a result that arrives
// after the input list has already changed is still correct — results are
// always applied. (An earlier cancelled-flag design discarded in-flight results
// whenever the ref list grew, which silently dropped most thumbnails.)
export function usePosterUrls(
    api: EclypteApiClient | null,
    refs: (FileVersionInput | null | undefined)[],
): Record<string, string> {
    const [urls, setUrls] = useState<Record<string, string>>({})
    const inFlightRef = useRef<Set<string>>(new Set())
    const resolvedRef = useRef<Set<string>>(new Set())
    const mountedRef = useRef(true)
    useEffect(() => {
        mountedRef.current = true
        return () => {
            mountedRef.current = false
        }
    }, [])
    const wanted = refs.filter((ref): ref is FileVersionInput => Boolean(ref)).map(posterKey).sort().join("|")

    useEffect(() => {
        if (!api || wanted === "") {
            return
        }
        for (const key of wanted.split("|")) {
            if (resolvedRef.current.has(key) || inFlightRef.current.has(key)) {
                continue
            }
            inFlightRef.current.add(key)
            const [file_id, version_id] = key.split(":")
            void api
                .getDownloadUrl({ file_id, version_id })
                .then((download) => {
                    resolvedRef.current.add(key)
                    if (mountedRef.current) {
                        setUrls((current) => ({ ...current, [key]: download.download_url }))
                    }
                })
                .catch(() => undefined) // decorative — a missing thumb falls back to the gradient tile
                .finally(() => {
                    inFlightRef.current.delete(key)
                })
        }
    }, [api, wanted])

    return urls
}
