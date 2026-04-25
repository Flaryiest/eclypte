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

export type DownloadUrlResponse = {
    download_url: string
    expires_in: number
}

const DEFAULT_API_BASE_URL =
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

    constructor({ baseUrl = DEFAULT_API_BASE_URL, userId }: ApiClientOptions) {
        this.baseUrl = baseUrl.replace(/\/+$/, "")
        this.userId = userId
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
