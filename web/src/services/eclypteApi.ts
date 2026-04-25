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

export type RunStatus = "created" | "running" | "blocked" | "failed" | "completed"

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
}

export type AssetState = "uploaded" | "analyzing" | "ready" | "failed"

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
}

export type RunSummary = RunManifest

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

export type DownloadUrlResponse = {
    download_url: string
    expires_in: number
}

export const ECLYPTE_API_BASE_URL =
    process.env.NEXT_PUBLIC_ECLYPTE_API_BASE_URL || "http://127.0.0.1:8000"

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
        return this.request<{ ok: boolean }>("/healthz", { signal })
    }

    async listAssets(kind?: ArtifactKind, signal?: AbortSignal) {
        const query = kind ? `?kind=${encodeURIComponent(kind)}` : ""
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

    async getRun(runId: string, signal?: AbortSignal) {
        return this.request<RunManifest>(`/v1/runs/${runId}`, { signal })
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
    const [reservation, sha256] = await Promise.all([
        api.createUpload(
            {
                kind,
                filename: file.name,
                content_type: contentType,
                size_bytes: file.size,
            },
            signal,
        ),
        sha256File(file),
    ])
    onStatus?.("Uploading to R2")
    await uploadToPresignedUrl(reservation.upload_url, file, reservation.required_headers, signal)
    onStatus?.("Completing upload")
    await api.completeUpload(reservation.upload_id, sha256, signal)
    return {
        file_id: reservation.file_id,
        version_id: reservation.version_id,
    }
}

export function assetState(asset: AssetSummary): AssetState {
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

export async function waitForRunCompletion(
    api: EclypteApiClient,
    initialRun: RunManifest,
    {
        signal,
        intervalMs = 3000,
        onUpdate,
    }: {
        signal?: AbortSignal
        intervalMs?: number
        onUpdate?: (run: RunManifest) => void
    } = {},
) {
    let run = initialRun
    onUpdate?.(run)
    while (isRunActive(run)) {
        await delay(intervalMs, signal)
        run = await api.getRun(run.run_id, signal)
        onUpdate?.(run)
    }
    if (run.status === "failed") {
        throw new Error(run.last_error || `${run.workflow_type} failed`)
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
