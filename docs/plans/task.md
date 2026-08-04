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
| A9 | Docs, full suite, deploy checklist | completed | full suite 561 passed; 1 pre-existing env failure (sandbox ffmpeg lacks drawtext); operator: redeploy eclypte-render-r2 |
