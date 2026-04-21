import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from api.prototyping.edit.index.query import query_clips

_ENV_PATH = Path(__file__).resolve().parent / ".env"

MODEL = "gpt-5.4"
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
- The opening is the most important section. Invest the most creativity and pattern variety at the start: tight cuts on impacts, held beats, motion-driven transitions. This is what hooks the viewer.
- After the opening, plain cut transitions are fine. You do not need to apply creative patterns to every shot — the rest of the edit should carry the story, not show off.
- Cover the full narrative arc of the source (or as much of it as fits the song), not just a cluster of high-energy moments.
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


def _create(client: OpenAI, *, previous_response_id: str | None = None, input_):
    kwargs = {
        "model": MODEL,
        "input": input_,
        "tools": TOOLS,
        "tool_choice": "auto",
        "reasoning": {"effort": REASONING_EFFORT},
        "text": {"verbosity": VERBOSITY},
    }
    if previous_response_id is None:
        kwargs["instructions"] = SYSTEM_PROMPT
    else:
        kwargs["previous_response_id"] = previous_response_id
    return client.responses.create(**kwargs)


def run_synthesis_loop(
    video_filename: str,
    instructions: str,
    song: dict | None = None,
    openai_api_key: str = None,
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

    user_content = instructions
    if song is not None:
        user_content = _format_song_context(song) + "\n\nUser brief:\n" + instructions

    print(f"Agent thinking (loop 1)...")
    response = _create(client, input_=user_content)

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
                result = query_clips(args["query"], video_filename, args.get("top_k", 5))
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
