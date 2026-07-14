import type {
    ArtifactKind,
    AssetSummary,
    AutopilotStatus,
    EclypteApiClient,
    EditJobStatus,
    PublishingPost,
    PublishingPostStatus,
    SynthesisPromptState,
    SynthesisReference,
} from "@/services/eclypteApi"
import { useResource, type UseResourceResult } from "./useResource"

// Typed, user-scoped wrappers around the dashboard resource cache.

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

export function usePublishingPosts(
    api: EclypteApiClient | null,
    filters: { status?: PublishingPostStatus | "queued_scheduled" | "all" } = {},
): UseResourceResult<PublishingPost[]> {
    const status = filters.status ?? "all"
    const key = api ? `publishing-posts:${api.userId}:${status}` : null
    return useResource<PublishingPost[]>(
        key,
        (signal) => api!.listPublishingPosts({ status }, signal),
        { enabled: api !== null },
    )
}

export function useSynthesisReferences(
    api: EclypteApiClient | null,
): UseResourceResult<SynthesisReference[]> {
    const key = api ? `synthesis-references:${api.userId}` : null
    return useResource<SynthesisReference[]>(
        key,
        (signal) => api!.listSynthesisReferences(signal),
        { enabled: api !== null },
    )
}

export function useSynthesisPrompt(
    api: EclypteApiClient | null,
): UseResourceResult<SynthesisPromptState> {
    const key = api ? `synthesis-prompt:${api.userId}` : null
    return useResource<SynthesisPromptState>(
        key,
        (signal) => api!.getSynthesisPrompt(signal),
        { enabled: api !== null },
    )
}

export function useAutopilot(api: EclypteApiClient | null): UseResourceResult<AutopilotStatus> {
    const key = api ? `autopilot:${api.userId}` : null
    return useResource<AutopilotStatus>(
        key,
        (signal) => api!.getAutopilot(signal),
        { enabled: api !== null },
    )
}
