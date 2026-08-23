# Lucky acquisition comparison (current 2.9.11)

This table records the currently executed decision order before any merge of
the two orchestrators.  “Target” means a configured output language/slot.

| # | Single Lucky (one target) | Dual Lucky (two targets) | Classification |
| --- | --- | --- | --- |
| 1 | Validate video and build one configured target slot. | Validate video and build two configured target slots. | Differs only by the number of target languages |
| 2 | Look up an exact local match with `_pick_best_exact_local_language_match`. | Run `_auto_match_subtitles` and copy its two slots when present. | **Genuinely different** |
| 3 | Download an `Exact`/`Likely` result if the target is missing. | Do the same for every missing target. | Differs only by the number of target languages |
| 4 | Find one trusted English reference if the target is still missing. | Find one trusted English reference if any target is still missing. | Differs only by the number of target languages |
| 5 | Offer English sync preview only when the target is missing or has origin `download_unknown`. | Offer English sync preview whenever an English reference is available. | **Genuinely different** |
| 6 | SmartSync the available target to the trusted English reference. | SmartSync every available target to the trusted English reference. | Differs only by the number of target languages |
| 7 | Collect unknown-tier candidates for the missing target. | Collect unknown-tier candidates for every missing target. | Differs only by the number of target languages |
| 8 | Offer AI translation for the missing target only when it has no risky candidates. | Offer AI translation for every missing target with no risky candidates. | Differs only by the number of target languages |
| 9 | Offer the risky-candidate picker for the one remaining target, then optionally SmartSync it. | Offer the same picker per remaining target, then optionally SmartSync each chosen result. | Differs only by the number of target languages |
| 10 | Activate the selected subtitle. | Merge the two selected subtitles through `resources/lib/dualsubs.py`, then activate the merged output. | **Genuinely different** |

## Stop condition

There are two genuine acquisition differences before the final display/merge
step: the local-match algorithm (#2) and the eligibility rule for the English
sync preview (#5).  Merging the current functions as-is would either change
one mode’s behaviour or encode mode-specific branches in the supposed shared
acquisition function.  Per the requested stop rule, no merge code has been
written.

## Approved behaviour normalization

The approved implementation will use the target-slot form of
`_auto_match_subtitles` for Single Lucky and will check an available English
reference in both modes when `lucky_strict_english_preview` is enabled. The
setting defaults to enabled; turning it off skips that preview when its extra
playback time is not wanted.
