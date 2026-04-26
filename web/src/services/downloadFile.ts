export async function downloadSignedUrl({
    url,
    filename,
    signal,
}: {
    url: string
    filename: string
    signal?: AbortSignal
}) {
    let response: Response
    try {
        response = await fetch(url, { signal })
    } catch (error) {
        if (isAbortError(error)) {
            throw error
        }
        throw new Error("Download failed. The signed storage URL may have expired or browser CORS may be blocking it.")
    }

    if (!response.ok) {
        throw new Error(`Download failed with status ${response.status}.`)
    }

    saveBlob(await response.blob(), filename)
}

export function safeDownloadFilename(name: string | null | undefined, fallback: string) {
    const raw = (name || fallback).trim()
    const cleaned = raw
        .replace(/[<>:"/\\|?*\x00-\x1F]/g, "-")
        .replace(/\s+/g, " ")
        .trim()
    return cleaned || fallback
}

function saveBlob(blob: Blob, filename: string) {
    const objectUrl = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = objectUrl
    anchor.download = filename
    anchor.style.display = "none"
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}

function isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError"
}
