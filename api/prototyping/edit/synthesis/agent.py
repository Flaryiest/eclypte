import json
import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

from api.prototyping.edit import skills
from api.prototyping.edit.index.query import query_clips
from api.prototyping.edit.synthesis.rhythm import pacing_bands_for
from api.prototyping.edit.synthesis.system_prompt import SYSTEM_PROMPT

_ENV_PATH = Path(__file__).resolve().parent / ".env"

MODEL = "gpt-5.5"
REASONING_EFFORT = "high"
VERBOSITY = "low"
MAX_LOOPS = 10

# SYSTEM_PROMPT is the canonical baseline prompt imported from system_prompt.py
# (the single source of truth). It is the fallback used only when run_synthesis_loop
# is called without an explicit system_prompt; production passes the active prompt
# version's text. Re-export it here so existing `from ...agent import SYSTEM_PROMPT`
# call sites keep working.

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
                                "description": "Optional transition into this shot (default cut). 'flash' is a subtle brightness bloom, not a white strobe — use at most once per edit, on the single hardest drop.",
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
                "overlays": {
                    "type": "array",
                    "description": (
                        "Optional text/mask overlay layers composited over the reel. "
                        "Omit entirely if none. Use sparingly."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill_id": {
                                "type": "string",
                                "enum": sorted(skills.ids()),
                                "description": "Which overlay skill to apply.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text content for text.* skills (ignored by mask.* skills).",
                            },
                            "start_time": {"type": "number", "description": "Overlay start time in seconds"},
                            "end_time": {"type": "number", "description": "Overlay end time in seconds"},
                        },
                        "required": ["skill_id", "start_time", "end_time"],
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


def _format_pacing_context(song: dict) -> str | None:
    """Section-aware pacing targets, derived from tempo + segment labels.

    Returned as per-run user content (not baked into the system prompt) so it
    applies regardless of the user's active prompt version. The adapter's
    rhythm engine enforces a backstop on fast sections; this guidance is what
    lets the agent hit the bands on its own.
    """
    segments = song.get("segments", []) or []
    if not segments:
        return None
    bands = pacing_bands_for(song.get("tempo_bpm"))
    lines = ["Pacing targets (shot lengths per song section):"]
    for seg in segments:
        try:
            start = float(seg["start_sec"])
            end = float(seg["end_sec"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(seg.get("label", "")).lower()
        lo, hi = bands.get(label, bands["default"])
        lines.append(
            f"- {label or 'section'} ({start:.1f}s-{end:.1f}s): aim for {lo:.1f}-{hi:.1f}s shots"
        )
    if len(lines) == 1:
        return None
    lines.append(
        "Cut faster in high-energy sections (chorus/drop) and let shots breathe "
        "in verses. Each query_clips result may include `motion` (0-1 scene "
        "motion), `camera` (camera movement), and `impact_near` (a visual hit "
        "lands there) — prefer high-motion, impact_near moments for high-energy "
        "sections and calmer footage for quiet ones."
    )
    return "\n".join(lines)


SHORT_EDIT_MAX_SEC = 40.0


def _format_short_edit_context(song_duration_sec: float) -> str:
    return (
        f"This is a short-form reel ({song_duration_sec:.0f}s). Completion and rewatch "
        f"rate decide its reach: hook instantly (strongest moment first, first cut "
        f"within ~1.5s, no slow intro), keep every shot earning its place, and aim "
        f"for an ending that loops cleanly back into the opening."
    )


def _format_overlay_skills() -> str:
    lines = [
        "Available overlay skills (optional text/mask layers added via the "
        "`overlays` field of finish_edit):"
    ]
    for entry in skills.agent_catalog():
        lines.append(f"- {entry['id']}: {entry['description']}")
    lines.append(
        "Do not add any overlay by default — most edits should ship with NO "
        "overlays at all. Only add a text overlay when the user's brief "
        "explicitly asks for on-screen text. When you do, keep it short and "
        "legible and give each overlay a start_time/end_time inside the song "
        "duration. text.* skills need a `text` value; mask.* skills do not."
    )
    return "\n".join(lines)


def _format_source_context(source_duration_sec: float) -> str:
    d = float(source_duration_sec)
    return (
        f"Source video: {d:.0f} seconds long.\n"
        f"Span the FULL content from start to end regardless of song length: your "
        f"earliest shots should come from near the start of the action and your latest "
        f"from near the end of the content. A shorter song means fewer, more spread-out "
        f"shots — NOT a smaller slice of the film. You may still dwell on or revisit a "
        f"standout moment (a climax, a key scene); coverage need not be even, but do not "
        f"leave the back half of the source unrepresented.\n"
        f"IMPORTANT — END CREDITS: the source's opening and closing stretches are usually a "
        f"black/logo intro and an end-credits roll, and those credits OFTEN play over a "
        f"COLORED (non-black) background, so they are NOT always auto-trimmed from the usable "
        f"source. Any frame dominated by on-screen text — rolling names, cast/crew lists, a "
        f"title card — is credits, not content, no matter how bright or colorful it is. Be "
        f"especially careful with your CLOSING shot: keep its source_timestamp on unmistakable "
        f"story content, pulled back from the very end of the source; if the tail might still "
        f"be credits, choose an earlier moment. Better to close on a strong mid-content beat "
        f"than to risk a credits frame. (Filling the song to its full duration is about the "
        f"audio timeline; it does NOT require your final shot to come from the literal last "
        f"seconds of the source.)"
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

    Returns the agent output:
      {
        "shots": [{"start_time": float, "end_time": float, "source_timestamp": float}, ...],
        "overlays": [{"skill_id": str, "text"?: str, "start_time": float, "end_time": float}, ...],
      }
    """
    load_dotenv(_ENV_PATH)
    client = OpenAI(api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"))
    active_system_prompt = system_prompt or SYSTEM_PROMPT
    clip_query = query_clips_fn or query_clips

    context_blocks: list[str] = []
    if song is not None:
        context_blocks.append(_format_song_context(song))
        pacing_block = _format_pacing_context(song)
        if pacing_block:
            context_blocks.append(pacing_block)
    if source_duration_sec is not None and float(source_duration_sec) > 0:
        context_blocks.append(_format_source_context(source_duration_sec))
    song_duration = float((song or {}).get("source", {}).get("duration_sec", 0.0) or 0.0)
    if 0.0 < song_duration <= SHORT_EDIT_MAX_SEC:
        context_blocks.append(_format_short_edit_context(song_duration))
    context_blocks.append(_format_overlay_skills())
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
                return {"shots": args["timeline"], "overlays": args.get("overlays") or []}

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
