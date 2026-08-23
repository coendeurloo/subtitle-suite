# CoreELEC on-device test checklist

Do not use the Mac timing numbers as a target. On CoreELEC, first enable
**Addon settings → Debug → Log timings**, then reproduce one case at a time
and inspect Kodi's log (normally `/storage/.kodi/temp/kodi.log`). Search for
lines beginning with `timing event=`.

## What timing lines mean

| Log line | Healthy result | Investigate when |
| --- | --- | --- |
| `timing event=interpreter_start_to_first_menu_item` | A normal menu should appear promptly; establish your own baseline over three cold opens. | It is consistently above 200 ms, or more than twice your baseline. |
| `timing event=menu_build` | Usually only a few milliseconds. | It is consistently above 50 ms. |
| `timing event=provider_query ... provider=... status=...` | Each enabled provider completes, fails clearly, or reports `cache_hit`. | A provider repeatedly consumes most of the 90-second Lucky budget or has unexpected retries. |
| `timing event=smartsync_run` | Finishes with a visible completion/low-confidence decision. | It is unexpectedly slow for a small SRT, or it stalls without a matching error. |
| `timing event=translation_block ... block=N attempts=N` | One attempt for a normal block; two only after a rejected response. | Repeated two-attempt blocks, a failed block, or an `ai translation source-echo check fired` line for ordinary dialogue. |
| `timing event=full_action action=...` | Provides the end-to-end number for comparison between runs. | It is consistently much higher than a known-good run with the same film. |

## Test cases

### Lucky Dual: Dutch + Russian, film with good subtitles

1. Start playback, open Subtitle Suite, and choose **I Feel Lucky (Dual)**.
2. Check `provider_query` lines for both language searches and a final
   `full_action action=ifeelluckydual` line.
3. Healthy: both targets are found or explicitly identified as local,
   SmartSync is either skipped as already close or completes, and the final
   active subtitle is the merged dual output. There must be no unexpected
   risky-candidate prompt.

### Known out-of-sync Russian subtitle

1. Keep a known-good English reference available and run Lucky Dual.
2. Look for `timing event=smartsync_run` and for the SmartSync confidence log.
3. Healthy: SmartSync either applies a correction or clearly reports why it
   was skipped; inspect playback to confirm the Russian cue now follows the
   English reference.

### No Russian subtitle: AI translation fallback

1. Enable AI translation and configure a valid OpenAI key; run Lucky Dual
   with no usable Russian subtitle.
2. Look for `timing event=translation_block` once per translation batch.
3. Healthy: every block has `attempts=1` (or a clearly logged single retry),
   the output is Russian rather than source text, and a failed/cancelled block
   leaves the previous subtitle file untouched. With no API key, the action
   must stay usable and report that translation was skipped.

### Cancel during provider search

1. Start a Lucky or manual provider search and press **Cancel** in the
   progress dialog while providers are still running.
2. Look for `provider_query` entries with `status=cancelled` or a clear
   cancellation message; there must be no subsequent `downloaded subtitle`
   line for the cancelled action.
3. Healthy: the dialog closes promptly, no subtitle file is written, and a
   late provider result is discarded.

### Restore Subtitle Backup

1. Restore a known valid backup, then repeat with a deliberately invalid or
   empty backup only if you have a safe test copy.
2. Look for a successful restore log or a parsing/staging failure.
3. Healthy: a valid backup replaces the target; an invalid backup reports the
   failure and leaves the existing target subtitle unchanged. No timing line
   is currently emitted specifically for restore, so use the action log and
   verify the target file itself.

## SmartSync knot span

`knot_span_ms` is logged in the Lucky low-confidence diagnostic line:
`lucky smart sync local low confidence: ... knot_span_ms=...`.
It is the timeline span covered by the alignment knots. A value above `90000`
(90 seconds) means SmartSync is warping across a very long portion of the
film; treat the result as lower confidence and verify it manually in playback.
