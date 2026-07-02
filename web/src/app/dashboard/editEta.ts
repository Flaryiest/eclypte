import { useEffect, useState } from "react"
import type { EditJobStatus, EditJobStage } from "@/services/eclypteApi"

// Mirror of EDIT_STAGE_WEIGHTS in api/app.py — keep in sync. Approximate share of
// wall-clock per edit stage; used here only as a prior/ratio for the time-left
// estimate (the bar itself is weighted server-side).
export const EDIT_STAGE_WEIGHTS: Record<string, number> = {
    assets: 0.02,
    music: 0.15,
    video: 0.22,
    timeline: 0.2,
    render: 0.39,
    result: 0.02,
}
const ETA_DEFAULT_TOTAL_SEC = 150 // prior before any stage has produced a real timing
const ETA_MIN_CALIBRATION_SEC = 2 // ignore reused/instant stages when calibrating the run total
const ETA_LOCAL_RATE_MIN_PCT = 8 // below this, use the stage's expected duration, not its local rate
const ETA_SMOOTHING = 0.3 // EMA factor applied when a real progress update arrives

export function useNow(active: boolean) {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        if (!active) {
            return
        }
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [active])
    return now
}

type StageTiming = {
    id: string
    status: EditJobStage["status"]
    percent: number
    startMs: number | null
    durationSec: number | null
}

// Pure: remaining seconds = time left in the running stage + expected time for
// not-yet-started stages. Stage-local rate keeps it accurate within a stage (e.g.
// render's frame encode), so it never inherits the inflated cross-stage average.
function estimateRemainingSec(stages: StageTiming[], nowMs: number): number | null {
    // Calibrate the run total from stages that actually ran (skip reused/instant ones).
    let calibratedSec = 0
    let calibratedWeight = 0
    for (const stage of stages) {
        const weight = EDIT_STAGE_WEIGHTS[stage.id] ?? 0
        if (stage.durationSec !== null && stage.durationSec >= ETA_MIN_CALIBRATION_SEC && weight > 0) {
            calibratedSec += stage.durationSec
            calibratedWeight += weight
        }
    }
    const totalSec = calibratedWeight > 0 ? calibratedSec / calibratedWeight : ETA_DEFAULT_TOTAL_SEC

    let remaining = 0
    let hasOutstanding = false
    for (const stage of stages) {
        if (stage.status === "completed" || stage.status === "failed" || stage.status === "canceled") {
            continue
        }
        hasOutstanding = true
        const weight = EDIT_STAGE_WEIGHTS[stage.id] ?? 0
        if (stage.status === "running") {
            const elapsedInStage = stage.startMs !== null ? Math.max(0, (nowMs - stage.startMs) / 1000) : 0
            if (stage.percent >= ETA_LOCAL_RATE_MIN_PCT && stage.startMs !== null) {
                remaining += (elapsedInStage * (100 - stage.percent)) / stage.percent
            } else {
                remaining += Math.max(0, weight * totalSec - elapsedInStage)
            }
        } else {
            // pending — not started yet
            remaining += weight * totalSec
        }
    }
    return hasOutstanding ? remaining : null
}

type EtaState = {
    sig: string
    starts: Record<string, number>
    durations: Record<string, number>
    anchorEtaSec: number | null
    anchorNowMs: number
}

function emptyEtaState(nowMs: number): EtaState {
    return { sig: "inactive", starts: {}, durations: {}, anchorEtaSec: null, anchorNowMs: nowMs }
}

function stageSignature(job: EditJobStatus): string {
    return job.stages.map((stage) => `${stage.id}:${stage.status}:${stage.percent}`).join("|")
}

// Re-anchor when real progress arrives: record each stage's first-seen start and
// completion duration, recompute the estimate, and ease the anchor toward it (EMA).
// Between updates the displayed value just counts down from the anchor (see useRenderEta),
// so it never rises on a bare clock tick.
function nextEtaState(prev: EtaState, job: EditJobStatus, nowMs: number, sig: string): EtaState {
    const starts = { ...prev.starts }
    const durations = { ...prev.durations }
    const stages: StageTiming[] = job.stages.map((stage) => {
        if ((stage.status === "running" || stage.percent > 0) && starts[stage.id] === undefined) {
            starts[stage.id] = nowMs
        }
        if (stage.status === "completed" && durations[stage.id] === undefined) {
            durations[stage.id] =
                starts[stage.id] !== undefined ? Math.max(0, (nowMs - starts[stage.id]) / 1000) : 0
        }
        return {
            id: stage.id,
            status: stage.status,
            percent: stage.percent,
            startMs: starts[stage.id] ?? null,
            durationSec: durations[stage.id] ?? null,
        }
    })

    const raw = estimateRemainingSec(stages, nowMs)
    let anchorEtaSec = prev.anchorEtaSec
    if (raw !== null) {
        const shownNow =
            prev.anchorEtaSec === null
                ? null
                : Math.max(0, prev.anchorEtaSec - (nowMs - prev.anchorNowMs) / 1000)
        anchorEtaSec = shownNow === null ? raw : shownNow + ETA_SMOOTHING * (raw - shownNow)
    }
    return { sig, starts, durations, anchorEtaSec, anchorNowMs: nowMs }
}

// Phase-aware "time left". Stages carry no timestamps, so timing is tracked locally;
// state is adjusted during render only when the stage signature changes (the
// React-endorsed "store info from previous renders" pattern), and the shown value is
// derived purely from the anchor + elapsed so it counts down smoothly between updates.
export function useRenderEta(job: EditJobStatus, isActive: boolean, nowMs: number): number | null {
    const [state, setState] = useState<EtaState>(() => emptyEtaState(nowMs))

    const sig = isActive ? stageSignature(job) : "inactive"
    if (sig !== state.sig) {
        setState((prev) => (isActive ? nextEtaState(prev, job, nowMs, sig) : emptyEtaState(nowMs)))
    }

    if (!isActive || state.anchorEtaSec === null) {
        return null
    }
    return Math.max(0, state.anchorEtaSec - (nowMs - state.anchorNowMs) / 1000)
}
