# Autonomous pairing & posting — design

Date: 2026-07-27
Status: approved by Eric (brainstorm session); ready for implementation planning.

## Problem

Autopilot today automates everything *between* two manual moments: Eric must
(1) log in and queue each film+song pair, and (2) approve each ready package
before it goes to Buffer/Instagram. The goal is zero-login operation: the
system picks pairs, produces ~2 reels per day, and they post to Instagram on
schedule — while keeping a way to kill a bad reel before it goes out.

## Decisions made during brainstorming

- **Veto-window posting, timed by Buffer.** Ready packages are auto-sent to
  Buffer's *queue* immediately; Buffer's channel posting schedule (Eric
  configures 2 slots/day once, in Buffer) decides when each actually posts.
  The gap until the next slot is the review/veto window. No artificial
  N-hour delay in Eclypte.
- **Pairing = rotation + dedupe.** Least-recently-used film × least-recently-
  used song, skipping exhausted combos. No LLM matchmaker, no analysis-driven
  pairing scores (variety already comes from energy-ranked trim windows and
  agent variability).
- **Recycle after cooldown.** When every pairing is exhausted, reuse the
  least-recently-paired combo (clearing its window dedupe) rather than
  halting. Surface a note in the Home feed when recycling is active.
- **Approach A: extend the existing tick.** No new workers/crons; the two new
  behaviors are steps inside `run_autopilot_tick`'s state machine.

## Non-goals

- Editing a caption after a post is queued in Buffer (veto = cancel; the
  render stays in the Library for manual re-post).
- Smart/LLM pairing, posting-time optimization, YouTube publishing.
- Multi-user/multi-channel concerns beyond the current single-replica model.

## Architecture

Two independent booleans on autopilot settings, both default **off** (current
behavior unchanged until enabled):

- `auto_pair` — the tick synthesizes queue items itself.
- `auto_publish` — the tick sends ready auto-created packages to Buffer.

Tick order (new steps marked):

```
advance in-flight items      (unchanged)
auto-send ready packages     (new; auto_publish)
replenish queue              (new; auto_pair)
start new work               (unchanged — consumes synthesized items
                              exactly like manually queued ones)
```

Cadence model: `daily_target` (existing knob, set to 2) caps *production*
per day; Buffer's channel schedule caps *posting*. Backstop: auto-send is
skipped while more than `2 × daily_target` posts sit in `queued`, so the
Buffer queue cannot grow without bound if the Buffer schedule is paused.

Required refactor: extract the send-to-Buffer flow (public R2 media copy →
`create_video_post` → mark `queued`) out of the `/v1/publishing/posts/{id}/
send-buffer` route in `api/app.py` into a shared `send_post_to_buffer(...)`
in `api/publishing.py`. The route and the tick call the same function.

## State model (all additive, defaulted — old persisted state loads as-is)

`AutopilotState`:
- `auto_pair: bool = False`
- `auto_publish: bool = False`
- `last_paired_at: dict[str, str] = {}` — file_id → ISO timestamp, for LRU
  ordering of films and songs. Entries for assets no longer in the library
  are pruned opportunistically during replenish.
- `exhausted_pairs: list[str] = []` — `"{video_file_id}::{song_file_id}"`
  keys, appended when an item fails with the existing "no unused trim
  window" outcome.
- `recycling: bool = False` / `waiting_for_library: bool = False` — stamped
  by each replenish run (not computed at read time), so the status route
  needs no asset listing to report the feed notes.

`AutopilotItem`:
- `auto_paired: bool = False` — feed labeling.

## Replenish algorithm (auto_pair)

Runs when: `auto_pair` on, autopilot enabled, not halted, no `pending`
items, and `in_flight + packaged_today < daily_target`.

1. List non-archived `source_video` and `song_audio` assets (via the repo the
   tick already holds).
2. If either list is empty: no-op; status response reports
   `waiting_for_library: true`. Never a halt.
3. Order films and songs by `last_paired_at` (missing → oldest).
4. Walk candidate pairings in LRU order; skip pairs in `exhausted_pairs`.
5. First viable pairing becomes a normal `AutopilotItem` (`auto_paired=True`,
   empty creative brief); stamp both assets in `last_paired_at`.
6. **Recycle**: if every pairing is exhausted, pick the least-recently-paired
   one, remove its entries from `used_combos` and `exhausted_pairs`, and pair
   it. Status response reports `recycling: true` for the feed note
   ("recycling your library — add films or songs for fresh combos").

One item per tick at most (capacity re-checked next tick), which naturally
paces production across the day.

## Auto-send (auto_publish)

Runs when `auto_publish` is on. Targets posts with `status == "ready"` AND
`auto_created == true` only — manually created packages (Library "Post"
action) remain review-gated.

- Send via `send_post_to_buffer(post, mode="queue")`; success → `queued`
  (identical to a manual "Add to queue").
- Failure → record `last_error`, leave `ready`, retry on later ticks with a
  backoff: skip the post if its `updated_at` is under 30 minutes old.
- Send failures never count toward the 3-consecutive-failures halt (a Buffer
  outage must not stop reel production).
- Skipped entirely while `count(status == "queued") > 2 × daily_target`
  (all of the user's queued posts, not just auto-created ones — every queued
  post occupies a Buffer slot regardless of origin).

## Veto

- `BufferClient` gains `delete_post(buffer_post_id)` (GraphQL delete
  mutation; exact mutation name confirmed during implementation against
  Buffer's schema).
- The existing cancel endpoint extends: if the post is `queued`/`scheduled`
  and has a `buffer_post_id`, delete it in Buffer first, then mark the local
  record `canceled`. Unsent posts cancel locally exactly as today.
- Buffer delete failure: surface the error in the sheet's error slot; the
  post stays `queued` (stuck-visible beats silently half-canceled).

## Error handling summary

| Condition | Behavior |
| --- | --- |
| Library empty (no films or no songs) | Replenish no-ops; `waiting_for_library` note; no halt |
| All pairings exhausted | Recycle least-recently-paired combo; `recycling` note |
| Analysis/edit failures | Existing 3-failure halt, unchanged; halt also stops replenish |
| Buffer send failure | Per-post `last_error`; retry with ≥30-min backoff; isolated from halt |
| Buffer delete (veto) failure | Error in sheet; post stays `queued` |
| Toggle flipped off | That half of the automation stops next tick; degrades to today's flow |

## API & frontend

- `PATCH /v1/autopilot` accepts `auto_pair` / `auto_publish`.
- `GET /v1/autopilot` (status response) carries both flags plus
  `recycling` and `waiting_for_library`.
- Home feed: two switches beside the existing enable/daily-target controls
  ("Pick pairs for me", "Post without review"); an "auto-paired" chip on
  synthesized items; queued cards say "posts at your next Buffer slot —
  cancel to veto"; Cancel wired to the extended endpoint.
- `web/src/services/eclypteApi.ts` types updated to match.

## Testing

Against the existing in-memory fakes (no live R2/Buffer/Modal):

- Replenish: LRU order; exhausted-pair skip; recycle path clears
  `used_combos`; empty-library no-op; halt stops replenish; one item/tick.
- Auto-send: only `ready` + `auto_created`; queue-mode payload; failure sets
  `last_error` and backs off; queued-count backstop; manual packages
  untouched.
- Veto: Buffer delete called for queued posts; local-only cancel for unsent;
  delete failure leaves the post queued.
- API: settings round-trip; status response flags (`test_api_v1.py`).
- Refactor: route and tick share `send_post_to_buffer` (behavior parity
  covered by existing send-buffer tests continuing to pass).

## Operational assumptions

- Eric configures the Buffer channel's posting schedule to 2 slots/day (one
  time, in Buffer's dashboard).
- `daily_target` set to 2 in the dashboard.
- `ECLYPTE_AUTOPILOT=1` stays set on Railway (always-on tick loop).
- Docs to update with the new fields/flow: CLAUDE.md, AGENTS.md,
  ARCHITECTURE.md, api/COMMANDS.md.
