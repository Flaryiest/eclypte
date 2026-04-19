"""
Consolidate all ingested reference JSONs into `knowledge/references.md`
via a single LLM call.

The LLM's job is qualitative synthesis: turn per-reference metrics into
pattern-weight suggestions and free-form observations, formatted as three
fixed H2 sections. If the output doesn't validate, the existing
references.md is left untouched and a non-zero exit signals the failure.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..patterns import registry

log = logging.getLogger(__name__)

H2_HEADERS = ("## Discovered Patterns", "## Weighted Annotations", "## Correlations")
DEFAULT_MODEL = "gpt-5.2"


class ConsolidationValidationError(RuntimeError):
    pass


def consolidate(
    store_dir: Path,
    references_md_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
) -> Path:
    store_dir = Path(store_dir)
    references_md_path = Path(references_md_path)

    references = _load_references(store_dir)
    pattern_ids = registry.ids(registry.load())

    if not references:
        content = _empty_stub(pattern_ids)
        if dry_run:
            log.info("dry-run: would write empty stub to %s", references_md_path)
            return references_md_path
        return _atomic_write_with_backup(references_md_path, content)

    instructions, user_input = _build_prompt(references, pattern_ids)

    if dry_run:
        log.info("dry-run: prompt built, LLM call skipped")
        log.info("instructions: %d chars, input: %d chars",
                 len(instructions), len(user_input))
        return references_md_path

    text = _call_llm(instructions, user_input, model=model)
    _validate_markdown(text, pattern_ids)
    return _atomic_write_with_backup(references_md_path, text)


def _load_references(store_dir: Path) -> list[dict]:
    if not store_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(store_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("skipping unreadable reference %s: %s", p, exc)
    return out


def _build_prompt(
    refs: list[dict],
    pattern_ids: set[str],
) -> tuple[str, str]:
    slim_refs = [_slim(r) for r in refs]
    input_payload = {
        "known_pattern_ids": sorted(pattern_ids),
        "references": slim_refs,
    }

    instructions = _INSTRUCTIONS_TEMPLATE.format(
        pattern_ids=", ".join(sorted(pattern_ids)) or "(none)",
        headers="\n".join(H2_HEADERS),
    )
    return instructions, json.dumps(input_payload, indent=2)


def _slim(ref: dict) -> dict:
    """Drop the raw music/video dicts — only metrics + meta go to the LLM."""
    return {
        "ref_id": ref.get("ref_id"),
        "meta": ref.get("meta", {}),
        "metrics": ref.get("metrics", {}),
    }


def _call_llm(instructions: str, user_input: str, *, model: str) -> str:
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=user_input,
    )
    return response.output_text


def _validate_markdown(text: str, pattern_ids: set[str]) -> None:
    positions = []
    for h in H2_HEADERS:
        idx = text.find(h)
        if idx < 0:
            raise ConsolidationValidationError(f"missing H2 header: {h!r}")
        positions.append(idx)
    if positions != sorted(positions):
        raise ConsolidationValidationError(
            f"H2 headers out of order: expected {H2_HEADERS}, got "
            f"positions {positions}"
        )

    annotations_block = _extract_section(text, "## Weighted Annotations")
    for line in annotations_block.splitlines():
        m = _ANNOTATION_LINE.match(line.strip())
        if not m:
            continue
        pid = m.group("pid")
        if pid not in pattern_ids:
            log.warning("annotation references unknown pattern_id %r", pid)


def _extract_section(text: str, header: str) -> str:
    start = text.find(header)
    if start < 0:
        return ""
    start = text.find("\n", start) + 1
    rest = text[start:]
    next_h2 = re.search(r"^## ", rest, flags=re.MULTILINE)
    if next_h2:
        return rest[: next_h2.start()]
    return rest


def _atomic_write_with_backup(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_suffix(path.suffix + f".bak.{ts}")
        backup.write_bytes(path.read_bytes())
        log.info("backed up previous %s → %s", path.name, backup.name)

    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    log.info("wrote %s", path)
    return path


def _empty_stub(pattern_ids: Iterable[str]) -> str:
    return (
        "# Eclypte AMV Reference Knowledge\n\n"
        "schema_version: 1\n"
        f"consolidated_at: {datetime.now(timezone.utc).isoformat()}\n"
        "n_references: 0\n\n"
        "No references have been ingested yet. Run "
        "`python -m api.prototyping.edit.reference ingest --url <yt> "
        "--likes N --views N` to add references, then re-run consolidate.\n\n"
        "## Discovered Patterns\n\n_(none yet — no references ingested.)_\n\n"
        "## Weighted Annotations\n\n_(none yet — no references ingested.)_\n\n"
        "## Correlations\n\n_(none yet — no references ingested.)_\n"
    )


_ANNOTATION_LINE = re.compile(
    r"^- (?P<pid>[a-z_]+\.[a-z0-9_]+): weight_multiplier=(?P<w>\d+\.\d+)"
)


_INSTRUCTIONS_TEMPLATE = """\
You are analysing objective metrics extracted from viral AMVs (anime music
videos) to produce editing-pattern guidance for a deterministic AMV
planner. The planner already has a catalog of patterns with hand-seeded
weights; your job is to propose WEIGHT MULTIPLIERS based on evidence from
the reference AMVs, plus qualitative observations.

Output a single markdown document with EXACTLY these three H2 headers,
in this order, and nothing above the first header except a brief
front-matter block (title, schema_version: 1, consolidated_at, n_references):

{headers}

Under `## Discovered Patterns`: prose describing recurring editing
behaviours you see in the metrics — e.g. "cuts consistently land 40-60 ms
before the downbeat in high-view chorus sections". Cite specific ref_ids
and metric values. Do not propose new pattern IDs — only reference
existing ones. 2-4 short paragraphs.

Under `## Weighted Annotations`: one bullet per pattern you want to
re-weight, STRICTLY in this line shape:

- <pattern_id>: weight_multiplier=<float> (n=<int>, evidence=<short summary>)

Rules:
- pattern_id MUST be one of the known ids: {pattern_ids}
- weight_multiplier MUST be a float in [0.5, 1.5]. A multiplier of 1.0
  is a no-op; use it only if the evidence is neutral. Values outside the
  range will be clamped by the consumer.
- n is the number of reference AMVs supporting the annotation.
- evidence is a 1-line justification ("cuts-on-downbeat fraction median
  0.81 across n=5 chorus sections" etc.).

Under `## Correlations`: short prose on cross-pattern or
cross-section relationships ("high-like refs use tighter cuts in chorus
AND slower shots in bridge"). 1-3 paragraphs.

Input format (JSON):
- `known_pattern_ids`: list[str]
- `references`: list[{{ref_id, meta, metrics}}], where metrics has
  `cut_offsets_to_downbeats` (histogram, mean, median, stdev),
  `cut_density_per_section` (per allin1 label: cuts_per_downbeat),
  `motion_at_cuts`, `impact_to_cut_lag`, `shot_duration_per_section`.

Do NOT output JSON, YAML, or code fences around the whole document. Just
the markdown. Do NOT include any prose between H2 sections and their
first bullet/paragraph beyond what's specified.
"""
