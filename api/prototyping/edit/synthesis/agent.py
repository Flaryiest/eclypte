import json
import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

from api.prototyping.edit.index.query import query_clips

_ENV_PATH = Path(__file__).resolve().parent / ".env"

MODEL = "gpt-5.5"
REASONING_EFFORT = "high"
VERBOSITY = "low"
MAX_LOOPS = 10

SYSTEM_PROMPT = """
You are an expert AMV editor. You must construct a video timeline based on the user's instructions.
You have access to a semantic search tool `query_clips` which lets you find timestamps in the source video matching text queries.

Steps:
1. Analyze the provided song metadata (duration, tempo, section structure) and the user's instructions.
2. Use `query_clips` to find the best source timestamps for the moments you need.
3. Construct the timeline by matching shots to the song's sections and pacing. The total timeline MUST span the full song duration.
4. Call `finish_edit` with the final timeline.

Editorial guidelines (baseline — follow unless the user's instructions override):
- Fit the full song. The final shot's end_time MUST equal the song duration (within ~0.5s). Do not stop early.
- Pace shots against the sections. Denser cuts in high-energy sections (chorus, drop); longer holds in low-energy sections (intro, verse, bridge).
- The opening is the most important section. The first 1.5 seconds decide whether a viewer stays: open on the single most visually striking moment you can find (an impact frame, a burst of motion, an iconic character moment) — never a slow establishing shot — and land the first cut within ~1.5s. Invest the most creativity at the start; this is what hooks the viewer.
- Each timeline item may optionally set "transition_in" ("cut" | "flash" | "crossfade") and "effect" ("freeze" | "punch_in"). Use flash on hard musical impacts (a drop or a downbeat slam), punch_in to add life to a longer held shot, and freeze for a dramatic stop on a final hit. Use them sparingly — a few per edit, at musical moments.
- After the opening, plain cut transitions are fine. You do not need to apply creative patterns to every shot — the rest of the edit should carry the story, not show off.
- Span the full source from beginning to end regardless of song length: the edit must reach the ending of the source, not just a cluster of early or high-energy moments. A shorter song means fewer, more spread-out shots — not a smaller slice of the film. You may still dwell on or revisit a standout moment.
- Pick shots mostly in chronological order from the source video. Small re-orderings for pacing are OK, but the overall progression should move forward through the source.
- CRITICAL: every `source_timestamp` in your final `finish_edit` call MUST be DISTINCT from every other `source_timestamp` (differ by more than 1 second). The adapter will drop any duplicates — repeated shots will be silently removed, shortening your AMV. This is the most common failure mode; double-check before calling `finish_edit`.

Your timeline MUST be continuous without overlapping clips.
"""

REMINDER_TEXT = (
    "Reminder before your next turn: all `source_timestamp` values in your "
    "final timeline must be unique (differ by >1s). Shots should also move "
    "roughly forward through the source (earlier source timestamps first, "
    "later ones later)."
)

TOOLS = [
    {
        "type": "function",
        "name": "query_clips",
        "description": "Finds the top K timestamps in the source video that match the semantic description.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Visual description of what to search for (e.g. 'person falling', 'explosion')",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "finish_edit",
        "description": "Submits the final timeline and ends the synthesis loop.",
        "parameters": {
            "type": "object",
            "properties": {
                "timeline": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_time": {"type": "number", "description": "Start time in seconds"},
                            "end_time": {"type": "number", "description": "End time in seconds"},
                            "source_timestamp": {"type": "number", "description": "Timestamp from query_clips"},
                            "transition_in": {
                                "type": "string",
                                "enum": ["cut", "flash", "crossfade"],
                                "description": "Optional transition into this shot (default cut). Use flash on hard musical impacts.",
                            },
                            "effect": {
                                "type": "string",
                                "enum": ["freeze", "punch_in"],
                                "description": "Optional effect on this shot: freeze (hold the first frame) or punch_in (slow zoom over the shot).",
                            },
                        },
                        "required": ["start_time", "end_time", "source_timestamp"],
                    },
                },
            },
            "required": ["timeline"],
        },
    },
]


def _format_song_context(song: dict) -> str:
    duration = float(song.get("source", {}).get("duration_sec", 0.0))
    tempo = song.get("tempo_bpm")
    segments = song.get("segments", []) or []

    lines = [
        "Song metadata:",
        f"- Duration: {duration:.2f} seconds (the final shot's end_time MUST equal this, within ~0.5s)",
    ]
    if tempo:
        lines.append(f"- Tempo: {float(tempo):.1f} BPM")
    if segments:
        lines.append("- Structure:")
        for i, seg in enumerate(segments, 1):
            start = float(seg["start_sec"])
            end = float(seg["end_sec"])
            label = seg.get("label", "?")
            lines.append(f"  {i}. {label}: {start:.2f}s – {end:.2f}s ({end - start:.2f}s)")
    return "\n".join(lines)


SHORT_EDIT_MAX_SEC = 40.0


def _format_short_edit_context(song_duration_sec: float) -> str:
    return (
        f"This is a short-form reel ({song_duration_sec:.0f}s). Completion and rewatch "
        f"rate decide its reach: hook instantly (strongest moment first, first cut "
        f"within ~1.5s, no slow intro), keep every shot earning its place, and aim "
        f"for an ending that loops cleanly back into the opening."
    )


def _format_source_context(source_duration_sec: float) -> str:
    d = float(source_duration_sec)
    return (
        f"Source video: {d:.0f} seconds long.\n"
        f"Span the FULL source from start to end regardless of song length: your "
        f"earliest shots should come from near 0s and your latest from near {d:.0f}s. "
        f"A shorter song means fewer, more spread-out shots — NOT a smaller slice of "
        f"the film. You may still dwell on or revisit a standout moment (a climax, a "
        f"key scene); coverage need not be even, but do not leave the back half or "
        f"ending of the source unrepresented."
    )


def _create(
    client: OpenAI,
    *,
    previous_response_id: str | None = None,
    input_,
    system_prompt: str = SYSTEM_PROMPT,
):
    kwargs = {
        "model": MODEL,
        "input": input_,
        "tools": TOOLS,
        "tool_choice": "auto",
        "reasoning": {"effort": REASONING_EFFORT},
        "text": {"verbosity": VERBOSITY},
    }
    if previous_response_id is None:
        kwargs["instructions"] = system_prompt
    else:
        kwargs["previous_response_id"] = previous_response_id
    return client.responses.create(**kwargs)


def run_synthesis_loop(
    video_filename: str,
    instructions: str,
    song: dict | None = None,
    openai_api_key: str | None = None,
    system_prompt: str | None = None,
    query_clips_fn: Callable[[str, str, int], list[dict]] | None = None,
    source_duration_sec: float | None = None,
) -> list[dict]:
    """
    Runs an LLM agent loop to construct an AMV timeline based on instructions.
    Uses OpenAI's Responses API with reasoning_effort=high for the planning
    task. The agent calls `query_clips` to find timestamps and `finish_edit`
    to submit the final timeline.

    If `song` is provided (song_analysis.json dict), its duration, tempo, and
    sections are formatted into the prompt so the agent sizes and paces the
    edit to the music.

    Returns the final list of timeline events:
      [{"start_time": float, "end_time": float, "source_timestamp": float}, ...]
    """
    load_dotenv(_ENV_PATH)
    client = OpenAI(api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"))
    active_system_prompt = system_prompt or SYSTEM_PROMPT
    clip_query = query_clips_fn or query_clips

    context_blocks: list[str] = []
    if song is not None:
        context_blocks.append(_format_song_context(song))
    if source_duration_sec is not None and float(source_duration_sec) > 0:
        context_blocks.append(_format_source_context(source_duration_sec))
    song_duration = float((song or {}).get("source", {}).get("duration_sec", 0.0) or 0.0)
    if 0.0 < song_duration <= SHORT_EDIT_MAX_SEC:
        context_blocks.append(_format_short_edit_context(song_duration))
    if context_blocks:
        user_content = "\n\n".join(context_blocks) + "\n\nUser brief:\n" + instructions
    else:
        user_content = instructions

    print(f"Agent thinking (loop 1)...")
    response = _create(client, input_=user_content, system_prompt=active_system_prompt)

    for loop_i in range(MAX_LOOPS):
        tool_calls = [it for it in response.output if getattr(it, "type", None) == "function_call"]

        if not tool_calls:
            text_out = getattr(response, "output_text", None)
            if text_out:
                print(f"Agent response: {text_out}")
            print(f"Agent thinking (loop {loop_i + 2})...")
            response = _create(
                client,
                previous_response_id=response.id,
                input_=[{
                    "type": "message",
                    "role": "user",
                    "content": "Please output your timeline using the finish_edit tool.",
                }],
            )
            continue

        tool_outputs: list[dict] = []
        issued_query = False
        for tc in tool_calls:
            args = json.loads(tc.arguments)
            print(f"Agent called tool: {tc.name} with args: {args}")

            if tc.name == "query_clips":
                result = clip_query(args["query"], video_filename, args.get("top_k", 5))
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": json.dumps(result),
                })
                issued_query = True
            elif tc.name == "finish_edit":
                print("Agent finished editing.")
                return args["timeline"]

        next_input: list[dict] = list(tool_outputs)
        if issued_query:
            next_input.append({
                "type": "message",
                "role": "user",
                "content": REMINDER_TEXT,
            })

        print(f"Agent thinking (loop {loop_i + 2})...")
        response = _create(
            client,
            previous_response_id=response.id,
            input_=next_input,
        )

    raise RuntimeError("Synthesis loop exceeded max iterations without calling finish_edit.")
