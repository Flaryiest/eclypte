export type ArtifactKind =
    | "source_video"
    | "song_audio"
    | "lyrics"
    | "music_analysis"
    | "video_analysis"
    | "clip_index"
    | "timeline"
    | "render_output"

export type FileVersionInput = {
    file_id: string
    version_id: string
}

export type UploadCreateRequest = {
    kind: "song_audio" | "source_video"
    filename: string
    content_type: string
    size_bytes: number
}

export type UploadCreateResponse = {
    upload_id: string
    file_id: string
    version_id: string
    upload_url: string
    required_headers: Record<string, string>
    expires_in: number
}

export type FileVersionMeta = {
    version_id: string
    file_id: string
    owner_user_id: string
    content_type: string
    size_bytes: number
    sha256: string
    original_filename: string
    created_at: string
    created_by_step: string
    storage_key: string
}

export type RunStatus = "created" | "running" | "blocked" | "failed" | "completed" | "canceled"
export type PlanningMode = "agent" | "deterministic"
export type ExportFormat = "reels_9_16" | "youtube_16_9"

export type ExportOptions = {
    format: ExportFormat
    audioStartSec?: number
    audioEndSec?: number | null
    cropFocusX?: number
}

export type RunManifest = {
    run_id: string
    owner_user_id: string
    workflow_type: string
    status: RunStatus
    inputs: Record<string, string>
    outputs: Record<string, string>
    steps: Array<{ name: string; status: "pending" | "running" | "completed" | "failed" }>
    current_step: string | null
    last_error: string | null
    created_at: string
    updated_at: string
    archived_at: string | null
    archived_reason: string | null
}

export type AssetState = "uploaded" | "analyzing" | "ready" | "failed" | "archived"

export type AssetSummary = {
    file_id: string
    kind: ArtifactKind
    display_name: string
    current_version_id: string | null
    created_at: string
    updated_at: string
    source_run_id: string | null
    tags: string[]
    current_version: FileVersionMeta | null
    latest_run: RunManifest | null
    analysis: FileVersionInput | null
    archived_at: string | null
    archived_reason: string | null
}

export type RunSummary = RunManifest

export type ContentCandidateStatus = "discovered" | "available" | "approved" | "rejected" | "imported"
export type ContentMediaType = "movie" | "tv"

export type ContentProvider = {
    provider_id: number
    name: string
    provider_type: "flatrate" | "free" | "ads" | "rent" | "buy"
    logo_path: string | null
}

export type ContentCandidate = {
    candidate_id: string
    owner_user_id: string
    source: string
    status: ContentCandidateStatus
    media_type: ContentMediaType
    tmdb_id: number
    title: string
    overview: string
    release_date: string | null
    poster_path: string | null
    backdrop_path: string | null
    genre_ids: number[]
    genres: string[]
    popularity: number
    vote_average: number
    vote_count: number
    provider_region: string
    provider_link: string | null
    providers: ContentProvider[]
    score: number
    tmdb_url: string
    created_at: string
    updated_at: string
}

export type SynthesisReference = {
    reference_id: string
    owner_user_id: string
    url: string
    status: "queued" | "running" | "completed" | "failed"
    likes: number
    views: number
    title: string | null
    author: string | null
    duration_sec: number | null
    metrics: Record<string, unknown>
    last_error: string | null
    created_at: string
    updated_at: string
}

export type SynthesisPromptVersion = {
    version_id: string
    owner_user_id: string
    label: string
    prompt_text: string
    generated_guidance: string
    source_reference_ids: string[]
    created_at: string
}

export type SynthesisPromptState = {
    owner_user_id: string
    active_version_id: string
    active_prompt: SynthesisPromptVersion
    versions: SynthesisPromptVersion[]
}

export type RunProgressEvent = {
    stage: string
    percent: number
    detail: string
}

export type RunEvent = {
    event_id: string
    run_id: string
    owner_user_id: string
    event_type: string
    timestamp: string
    payload: Record<string, unknown>
}

export type RunStreamMessage =
    | { type: "run_manifest"; run: RunManifest }
    | { type: "run_event"; event: RunEvent }
    | { type: "heartbeat"; timestamp: string }

export type EditJobStage = {
    id: string
    label: string
    status: "pending" | "running" | "completed" | "failed" | "canceled"
    percent: number
    detail: string
}

export type EditJobStatus = {
    run_id: string
    workflow_type: "edit_pipeline"
    status: RunStatus
    title: string
    progress_percent: number
    stages: EditJobStage[]
    child_runs: Record<string, string>
    render_output: FileVersionInput | null
    last_error: string | null
    created_at: string
    updated_at: string
}

export type EditJobRequest = {
    audio: FileVersionInput
    sourceVideo: FileVersionInput
    planningMode?: PlanningMode
    creativeBrief?: string
    title?: string
    exportOptions?: ExportOptions
}

export type DownloadUrlResponse = {
    download_url: string
    expires_in: number
}

export type HealthResponse = {
    ok: boolean
    youtube_cookies_configured?: boolean
}

export const ECLYPTE_API_BASE_URL =
    process.env.NEXT_PUBLIC_ECLYPTE_API_BASE_URL || "http://127.0.0.1:8000"
const RUN_STREAM_STALE_TIMEOUT_MS = 15000

type ApiClientOptions = {
    baseUrl?: string
    userId: string
}

export class EclypteApiError extends Error {
    status: number

    constructor(message: string, status: number) {
        super(message)
        this.name = "EclypteApiError"
        this.status = status
    }
}

export class EclypteApiClient {
    private readonly baseUrl: string
    private readonly userId: string

    constructor({ baseUrl = ECLYPTE_API_BASE_URL, userId }: ApiClientOptions) {
        this.baseUrl = baseUrl.replace(/\/+$/, "")
        this.userId = userId
    }

    async health(signal?: AbortSignal) {
        return this.request<HealthResponse>("/healthz", { signal })
    }

    async listAssets(
        kindOrOptions?: ArtifactKind | { kind?: ArtifactKind; includeArchived?: boolean },
        signal?: AbortSignal,
    ) {
        const params = new URLSearchParams()
        if (typeof kindOrOptions === "string") {
            params.set("kind", kindOrOptions)
        } else if (kindOrOptions) {
            if (kindOrOptions.kind) {
                params.set("kind", kindOrOptions.kind)
            }
            if (kindOrOptions.includeArchived) {
                params.set("include_archived", "true")
            }
        }
        const query = params.size ? `?${params.toString()}` : ""
        return this.request<AssetSummary[]>(`/v1/assets${query}`, { signal })
    }

    async listRuns(
        filters: { workflowType?: string; status?: RunStatus } = {},
        signal?: AbortSignal,
    ) {
        const params = new URLSearchParams()
        if (filters.workflowType) {
            params.set("workflow_type", filters.workflowType)
        }
        if (filters.status) {
            params.set("status", filters.status)
        }
        const query = params.size ? `?${params.toString()}` : ""
        return this.request<RunSummary[]>(`/v1/runs${query}`, { signal })
    }

    async createContentRadarDiscovery(
        input: { region?: string; maxPages?: number } = {},
        signal?: AbortSignal,
    ) {
        return this.request<RunManifest>("/v1/content-radar/discover", {
            method: "POST",
            body: JSON.stringify({
                region: input.region ?? "US",
                max_pages: input.maxPages ?? 1,
            }),
            signal,
        })
    }

    async listContentCandidates(
        filters: {
            mediaType?: ContentMediaType | "all"
            status?: ContentCandidateStatus | "all"
            provider?: string
            genre?: string
            releaseFrom?: string
            releaseTo?: string
        } = {},
        signal?: AbortSignal,
    ) {
        const params = new URLSearchParams()
        if (filters.mediaType && filters.mediaType !== "all") {
            params.set("media_type", filters.mediaType)
        }
        if (filters.status && filters.status !== "all") {
            params.set("status", filters.status)
        }
        if (filters.provider) {
            params.set("provider", filters.provider)
        }
        if (filters.genre) {
            params.set("genre", filters.genre)
        }
        if (filters.releaseFrom) {
            params.set("release_from", filters.releaseFrom)
        }
        if (filters.releaseTo) {
            params.set("release_to", filters.releaseTo)
        }
        const query = params.size ? `?${params.toString()}` : ""
        return this.request<ContentCandidate[]>(`/v1/content-candidates${query}`, { signal })
    }

    async approveContentCandidate(candidateId: string, signal?: AbortSignal) {
        return this.request<ContentCandidate>(
            `/v1/content-candidates/${encodeURIComponent(candidateId)}/approve`,
            { method: "POST", signal },
        )
    }

    async rejectContentCandidate(candidateId: string, signal?: AbortSignal) {
        return this.request<ContentCandidate>(
            `/v1/content-candidates/${encodeURIComponent(candidateId)}/reject`,
            { method: "POST", signal },
        )
    }

    async markContentCandidateImported(candidateId: string, signal?: AbortSignal) {
        return this.request<ContentCandidate>(
            `/v1/content-candidates/${encodeURIComponent(candidateId)}/mark-imported`,
            { method: "POST", signal },
        )
    }

    async createUpload(request: UploadCreateRequest, signal?: AbortSignal) {
        return this.request<UploadCreateResponse>("/v1/uploads", {
            method: "POST",
            body: JSON.stringify(request),
            signal,
        })
    }

    async completeUpload(uploadId: string, sha256: string, signal?: AbortSignal) {
        return this.request<FileVersionMeta>(`/v1/uploads/${uploadId}/complete`, {
            method: "POST",
            body: JSON.stringify({ sha256 }),
            signal,
        })
    }

    async deleteUpload(uploadId: string, signal?: AbortSignal) {
        await this.requestNoBody(`/v1/uploads/${encodeURIComponent(uploadId)}`, {
            method: "DELETE",
            signal,
        })
    }

    async deleteAsset(fileId: string, signal?: AbortSignal) {
        await this.requestNoBody(`/v1/assets/${encodeURIComponent(fileId)}`, {
            method: "DELETE",
            signal,
        })
    }

    async restoreAsset(fileId: string, signal?: AbortSignal) {
        return this.request<AssetSummary>(`/v1/assets/${encodeURIComponent(fileId)}/restore`, {
            method: "POST",
            signal,
        })
    }

    async createMusicAnalysis(audio: FileVersionInput, signal?: AbortSignal) {
        return this.request<RunManifest>("/v1/music/analyses", {
            method: "POST",
            body: JSON.stringify({ audio }),
            signal,
        })
    }

    async createYouTubeSongImport(url: string, signal?: AbortSignal) {
        return this.request<RunManifest>("/v1/music/youtube-imports", {
            method: "POST",
            body: JSON.stringify({ url }),
            signal,
        })
    }

    async createVideoAnalysis(sourceVideo: FileVersionInput, signal?: AbortSignal) {
        return this.request<RunManifest>("/v1/video/analyses", {
            method: "POST",
            body: JSON.stringify({ source_video: sourceVideo }),
            signal,
        })
    }

    async createTimelinePlan(
        input: {
            audio: FileVersionInput
            sourceVideo: FileVersionInput
            musicAnalysis: FileVersionInput
            videoAnalysis: FileVersionInput
            planningMode?: PlanningMode
            creativeBrief?: string
            exportOptions?: ExportOptions
        },
        signal?: AbortSignal,
    ) {
        return this.request<RunManifest>("/v1/timelines", {
            method: "POST",
            body: JSON.stringify({
                audio: input.audio,
                source_video: input.sourceVideo,
                music_analysis: input.musicAnalysis,
                video_analysis: input.videoAnalysis,
                planning_mode: input.planningMode,
                creative_brief: input.creativeBrief,
                export_options: serializeExportOptions(input.exportOptions),
            }),
            signal,
        })
    }

    async createRender(
        input: {
            timeline: FileVersionInput
            audio: FileVersionInput
            sourceVideo: FileVersionInput
        },
        signal?: AbortSignal,
    ) {
        return this.request<RunManifest>("/v1/renders", {
            method: "POST",
            body: JSON.stringify({
                timeline: input.timeline,
                audio: input.audio,
                source_video: input.sourceVideo,
            }),
            signal,
        })
    }

    async createEditJob(input: EditJobRequest, signal?: AbortSignal) {
        return this.request<EditJobStatus>("/v1/edits", {
            method: "POST",
            body: JSON.stringify({
                audio: input.audio,
                source_video: input.sourceVideo,
                planning_mode: input.planningMode,
                creative_brief: input.creativeBrief,
                title: input.title,
                export_options: serializeExportOptions(input.exportOptions),
            }),
            signal,
        })
    }

    async listEditJobs(signal?: AbortSignal) {
        return this.request<EditJobStatus[]>("/v1/edits", { signal })
    }

    async getEditJob(runId: string, signal?: AbortSignal) {
        return this.request<EditJobStatus>(`/v1/edits/${runId}`, { signal })
    }

    async cancelEditJob(runId: string, signal?: AbortSignal) {
        return this.request<EditJobStatus>(`/v1/edits/${encodeURIComponent(runId)}/cancel`, {
            method: "POST",
            signal,
        })
    }

    async deleteEditJob(runId: string, signal?: AbortSignal) {
        await this.requestNoBody(`/v1/edits/${encodeURIComponent(runId)}`, {
            method: "DELETE",
            signal,
        })
    }

    async redoEditJob(runId: string, signal?: AbortSignal) {
        return this.request<EditJobStatus>(`/v1/edits/${encodeURIComponent(runId)}/redo`, {
            method: "POST",
            signal,
        })
    }

    async getRun(runId: string, signal?: AbortSignal) {
        return this.request<RunManifest>(`/v1/runs/${runId}`, { signal })
    }

    async streamRunUpdates({
        runId,
        signal,
        onMessage,
    }: {
        runId?: string
        signal?: AbortSignal
        onMessage: (message: RunStreamMessage) => void
    }) {
        const path = runId
            ? `/v1/runs/${encodeURIComponent(runId)}/stream`
            : "/v1/runs/stream"
        const response = await fetch(`${this.baseUrl}${path}`, {
            headers: {
                "Accept": "application/x-ndjson",
                "X-User-Id": this.userId,
            },
            signal,
        })

        if (!response.ok) {
            throw new EclypteApiError(await readErrorMessage(response), response.status)
        }
        if (!response.body) {
            throw new Error("Run update stream is unavailable")
        }
        await readJsonLineStream(response.body, onMessage, signal)
    }

    async getDownloadUrl(ref: FileVersionInput, signal?: AbortSignal) {
        return this.request<DownloadUrlResponse>(
            `/v1/files/${ref.file_id}/versions/${ref.version_id}/download-url`,
            { signal },
        )
    }

    async createSynthesisReferences(urls: string[], signal?: AbortSignal) {
        return this.request<SynthesisReference[]>("/v1/synthesis/references", {
            method: "POST",
            body: JSON.stringify({ urls }),
            signal,
        })
    }

    async listSynthesisReferences(signal?: AbortSignal) {
        return this.request<SynthesisReference[]>("/v1/synthesis/references", { signal })
    }

    async createSynthesisConsolidation(signal?: AbortSignal) {
        return this.request<RunManifest>("/v1/synthesis/consolidations", {
            method: "POST",
            signal,
        })
    }

    async getSynthesisPrompt(signal?: AbortSignal) {
        return this.request<SynthesisPromptState>("/v1/synthesis/prompt", { signal })
    }

    async createSynthesisPromptVersion(
        input: {
            label: string
            prompt_text: string
            generated_guidance?: string
            source_reference_ids?: string[]
            activate?: boolean
        },
        signal?: AbortSignal,
    ) {
        return this.request<SynthesisPromptState>("/v1/synthesis/prompt/versions", {
            method: "POST",
            body: JSON.stringify(input),
            signal,
        })
    }

    async activateSynthesisPromptVersion(versionId: string, signal?: AbortSignal) {
        return this.request<SynthesisPromptState>(
            `/v1/synthesis/prompt/versions/${versionId}/activate`,
            { method: "POST", signal },
        )
    }

    private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
        const response = await fetch(`${this.baseUrl}${path}`, {
            ...init,
            headers: {
                "Content-Type": "application/json",
                "X-User-Id": this.userId,
                ...init.headers,
            },
        })

        if (!response.ok) {
            throw new EclypteApiError(await readErrorMessage(response), response.status)
        }

        return response.json() as Promise<T>
    }

    private async requestNoBody(path: string, init: RequestInit = {}): Promise<void> {
        const response = await fetch(`${this.baseUrl}${path}`, {
            ...init,
            headers: {
                "Content-Type": "application/json",
                "X-User-Id": this.userId,
                ...init.headers,
            },
        })

        if (!response.ok) {
            throw new EclypteApiError(await readErrorMessage(response), response.status)
        }
    }
}

export async function uploadAsset(
    api: EclypteApiClient,
    {
        file,
        kind,
        contentType,
        signal,
        onStatus,
    }: {
        file: File
        kind: "song_audio" | "source_video"
        contentType: "audio/wav" | "video/mp4"
        signal?: AbortSignal
        onStatus?: (status: string) => void
    },
): Promise<FileVersionInput> {
    onStatus?.("Preparing upload")
    const reservation = await api.createUpload(
        {
            kind,
            filename: file.name,
            content_type: contentType,
            size_bytes: file.size,
        },
        signal,
    )
    try {
        const sha256 = await sha256File(file)
        onStatus?.("Uploading to R2")
        await uploadToPresignedUrl(reservation.upload_url, file, reservation.required_headers, signal)
        onStatus?.("Completing upload")
        await api.completeUpload(reservation.upload_id, sha256, signal)
    } catch (caught) {
        await api.deleteUpload(reservation.upload_id).catch(() => undefined)
        throw caught
    }
    return {
        file_id: reservation.file_id,
        version_id: reservation.version_id,
    }
}

export function assetState(asset: AssetSummary): AssetState {
    if (asset.archived_at) {
        return "archived"
    }
    if (asset.latest_run?.status === "failed") {
        return "failed"
    }
    if (
        asset.latest_run?.status === "created" ||
        asset.latest_run?.status === "running" ||
        asset.latest_run?.status === "blocked"
    ) {
        return "analyzing"
    }
    if (
        asset.analysis ||
        asset.kind === "music_analysis" ||
        asset.kind === "video_analysis" ||
        asset.kind === "timeline" ||
        asset.kind === "render_output"
    ) {
        return "ready"
    }
    return "uploaded"
}

export function isRunActive(run: RunManifest) {
    return run.status === "created" || run.status === "running" || run.status === "blocked"
}

function serializeExportOptions(options: ExportOptions | undefined) {
    if (!options) {
        return undefined
    }
    return {
        format: options.format,
        audio_start_sec: options.audioStartSec ?? 0,
        audio_end_sec: options.audioEndSec ?? null,
        crop_focus_x: options.cropFocusX ?? 0.5,
    }
}

export async function waitForRunCompletion(
    api: EclypteApiClient,
    initialRun: RunManifest,
    {
        signal,
        intervalMs = 1000,
        onUpdate,
    }: {
        signal?: AbortSignal
        intervalMs?: number
        onUpdate?: (run: RunManifest) => void
    } = {},
) {
    let run = initialRun
    onUpdate?.(run)
    if (isRunActive(run)) {
        try {
            run = await waitForRunCompletionFromStream(api, run, { signal, onUpdate })
        } catch (caught) {
            if (signal?.aborted) {
                throw caught
            }
            run = await waitForRunCompletionByPolling(api, run, {
                signal,
                intervalMs,
                onUpdate,
            })
        }
    }
    if (run.status === "failed") {
        throw new Error(run.last_error || `${run.workflow_type} failed`)
    }
    return run
}

async function waitForRunCompletionFromStream(
    api: EclypteApiClient,
    initialRun: RunManifest,
    {
        signal,
        onUpdate,
    }: {
        signal?: AbortSignal
        onUpdate?: (run: RunManifest) => void
    },
) {
    let completed: RunManifest | null = null
    let latest = initialRun
    const streamController = new AbortController()
    let staleTimeout: ReturnType<typeof setTimeout> | undefined
    const abortStream = () => streamController.abort()
    const resetStaleTimeout = () => {
        if (staleTimeout !== undefined) {
            clearTimeout(staleTimeout)
        }
        staleTimeout = setTimeout(() => streamController.abort(), RUN_STREAM_STALE_TIMEOUT_MS)
    }
    signal?.addEventListener("abort", abortStream, { once: true })
    resetStaleTimeout()

    try {
        await api.streamRunUpdates({
            runId: initialRun.run_id,
            signal: streamController.signal,
            onMessage: (message) => {
                if (message.type === "run_event" && message.event.run_id === initialRun.run_id) {
                    resetStaleTimeout()
                    return
                }
                if (message.type !== "run_manifest" || message.run.run_id !== initialRun.run_id) {
                    return
                }
                resetStaleTimeout()
                latest = message.run
                onUpdate?.(latest)
                if (!isRunActive(latest)) {
                    completed = latest
                    streamController.abort()
                }
            },
        })
    } catch (caught) {
        if (completed) {
            return completed
        }
        throw caught
    } finally {
        signal?.removeEventListener("abort", abortStream)
        if (staleTimeout !== undefined) {
            clearTimeout(staleTimeout)
        }
    }

    if (completed) {
        return completed
    }
    if (!isRunActive(latest)) {
        return latest
    }
    throw new Error("Run update stream ended before completion")
}

async function waitForRunCompletionByPolling(
    api: EclypteApiClient,
    initialRun: RunManifest,
    {
        signal,
        intervalMs,
        onUpdate,
    }: {
        signal?: AbortSignal
        intervalMs: number
        onUpdate?: (run: RunManifest) => void
    },
) {
    let run = initialRun
    while (isRunActive(run)) {
        await delay(intervalMs, signal)
        run = await api.getRun(run.run_id, signal)
        onUpdate?.(run)
    }
    return run
}

export async function uploadToPresignedUrl(
    url: string,
    file: File,
    headers: Record<string, string>,
    signal?: AbortSignal,
) {
    const response = await fetch(url, {
        method: "PUT",
        headers,
        body: file,
        signal,
    })

    if (!response.ok) {
        throw new EclypteApiError(
            `Upload failed with status ${response.status}`,
            response.status,
        )
    }
}

export async function sha256File(file: File): Promise<string> {
    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer())
    return Array.from(new Uint8Array(digest))
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join("")
}

async function readErrorMessage(response: Response): Promise<string> {
    try {
        const body = await response.json()
        if (typeof body.detail === "string") {
            return body.detail
        }
        return JSON.stringify(body.detail ?? body)
    } catch {
        return `Request failed with status ${response.status}`
    }
}

export async function readJsonLineStream<T>(
    stream: ReadableStream<Uint8Array>,
    onMessage: (message: T) => void,
    signal?: AbortSignal,
) {
    const reader = stream.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    try {
        while (true) {
            if (signal?.aborted) {
                throw new DOMException("Aborted", "AbortError")
            }
            const { value, done } = await reader.read()
            if (done) {
                break
            }
            buffer += decoder.decode(value, { stream: true })
            const parsed = drainJsonLines(buffer)
            buffer = parsed.remainder
            for (const line of parsed.lines) {
                onMessage(JSON.parse(line) as T)
            }
        }
        buffer += decoder.decode()
        if (buffer.trim()) {
            onMessage(JSON.parse(buffer) as T)
        }
    } finally {
        reader.releaseLock()
    }
}

export function drainJsonLines(buffer: string) {
    const parts = buffer.split("\n")
    const remainder = parts.pop() ?? ""
    return {
        lines: parts.map((line) => line.replace(/\r$/, "")).filter(Boolean),
        remainder,
    }
}

function delay(ms: number, signal?: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
        if (signal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"))
            return
        }
        const timeout = setTimeout(resolve, ms)
        signal?.addEventListener(
            "abort",
            () => {
                clearTimeout(timeout)
                reject(new DOMException("Aborted", "AbortError"))
            },
            { once: true },
        )
    })
}
