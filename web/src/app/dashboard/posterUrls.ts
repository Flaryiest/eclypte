import type { AssetSummary, FileVersionInput, PublishingPost } from "@/services/eclypteApi"

export function posterKey(ref: FileVersionInput) {
    return `${ref.file_id}:${ref.version_id}`
}

// Signed media URLs now arrive inside list payloads, but every refetch re-signs
// them, and the browser's image/video cache keys on the exact URL string. This
// module-level cache pins the FIRST URL seen for each content key (file+version)
// until it nears the 1h signature expiry, so SWR refetches (~30s TTL) and
// Home ↔ Library navigation keep byte-identical srcs — cache hits, no
// re-downloads. Content keys are immutable, so a pinned URL is never wrong,
// only eventually expired (at which point the fresh URL takes over).
const STABLE_URL_TTL_MS = 50 * 60 * 1000

const stableUrls = new Map<string, { url: string; seenAtMs: number }>()

export function stableMediaUrl(
    key: string,
    freshUrl: string | null | undefined,
): string | undefined {
    const cached = stableUrls.get(key)
    if (cached && Date.now() - cached.seenAtMs < STABLE_URL_TTL_MS) {
        return cached.url
    }
    if (!freshUrl) {
        return undefined
    }
    stableUrls.set(key, { url: freshUrl, seenAtMs: Date.now() })
    return freshUrl
}

export function postPosterUrl(post: PublishingPost): string | undefined {
    const key =
        post.render_poster_file_id && post.render_poster_version_id
            ? `${post.render_poster_file_id}:${post.render_poster_version_id}`
            : `post-poster:${post.post_id}`
    return stableMediaUrl(key, post.poster_url)
}

export function postRenderUrl(post: PublishingPost): string | undefined {
    return stableMediaUrl(`${post.render_file_id}:${post.render_version_id}`, post.render_url)
}

export function assetPosterUrl(asset: AssetSummary): string | undefined {
    const key = asset.poster ? posterKey(asset.poster) : `asset-poster:${asset.file_id}`
    return stableMediaUrl(key, asset.poster_url)
}
