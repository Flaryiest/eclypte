| id | task | status | notes |
| --- | --- | --- | --- |
| A1 | Autopilot renders fill-frame (reels_9_16) | completed | |
| A2 | Chorus lead-in 5s -> 1.5s | completed | |
| A3 | Loop-friendly tail fade for short reels | completed | no renderer change needed (both paths skip zero fades) |
| A4 | Niche-register captions, <=5 fandom hashtags | completed | |
| A5 | Strip release junk from media-derived names | completed | cut-at-first-junk-token heuristic |
| A6 | Overlap-aware trim-window dedupe | completed | used_windows state field, >40% overlap rejected |
| A7 | edit_focus - moment-focused edits for autopilot | completed | threaded app -> workflows -> agent; frontend type updated |
| A8 | First-shot hook telemetry | completed | first_shot in timeline_sync_report |
| A9 | Docs, full suite, deploy checklist | completed | operator: redeploy eclypte-render-r2 (no Modal token in this env) |
| B0 | Operator setup + live probes (CHECKPOINT) | blocked | needs Meta app + token (operator); audio-offset question open |
| B1 | Graph API client (containers, canary, insights, audio search) | completed | api/instagram_graph.py, probe-tolerant shapes |
| B2 | Public poster copy for cover_url | completed | shared _copy_version_to_public helper |
| B3 | Provider switch + send_post_via_graph | completed | ECLYPTE_PUBLISH_PROVIDER, 409 copyright veto, reused provider field |
| B3b | Attached licensed audio (CONDITIONAL) | blocked | gated on B0 audio-offset probe |
| B4 | Slot-spaced auto-publish for graph provider | completed | graph_slot_due, 86400/daily_target spacing |
| B5 | Graph-side status + metrics refresh | completed | fetch_graph_metrics dispatch + refresh-status route branch |
| B5b | Audio attribution verification (CONDITIONAL) | blocked | requires B3b |
| B6 | Frontend + docs + deploy | completed | provider-aware ReviewSheet, usePublishingConfig, runbook in COMMANDS.md |
