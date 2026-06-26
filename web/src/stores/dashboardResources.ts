import type {
    ArtifactKind,
    AssetSummary,
    EclypteApiClient,
    EditJobStatus,
} from "@/services/eclypteApi"
import { useResource, type UseResourceResult } from "./useResource"

// Typed, user-scoped wrappers around the dashboard resource cache. Add the
// remaining collections (runs, publishing posts, synthesis references, autopilot)
// here as the other pages migrate.

export function useAssets(
    api: EclypteApiClient | null,
    options: { includeArchived?: boolean; kind?: ArtifactKind } = {},
): UseResourceResult<AssetSummary[]> {
    const includeArchived = options.includeArchived ?? false
    const kind = options.kind ?? null
    const key = api ? `assets:${api.userId}:${includeArchived}:${kind ?? "all"}` : null
    return useResource<AssetSummary[]>(
        key,
        (signal) =>
            api!.listAssets({ includeArchived, kind: kind ?? undefined }, signal),
        { enabled: api !== null },
    )
}

export function useEditJobs(api: EclypteApiClient | null): UseResourceResult<EditJobStatus[]> {
    const key = api ? `edits:${api.userId}` : null
    return useResource<EditJobStatus[]>(
        key,
        (signal) => api!.listEditJobs(signal),
        { enabled: api !== null },
    )
}
