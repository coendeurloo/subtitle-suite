# SmartSync local profiling (development machine)

This is a local development-machine measurement, not a CoreELEC result. The
fixture contains 360 irregular cues with a 23.976/25 frame-rate mismatch.
Each number is the median of seven fresh `sync_local` runs.

| Variant | Median wall time | Notes |
| --- | ---: | --- |
| Before interval-length hoist (2.9.14 source) | 443.1 ms | Baseline implementation |
| After hoist, frame-rate correction disabled | 382.1 ms | 61.0 ms / 13.8% faster core sync |
| After hoist, frame-rate correction enabled | 537.4 ms | Includes ratio detection and correction |
| Ratio detection only | 163.7 ms | Median of five detection-only runs |

The optimisation claim applies only to the core local sync with correction
disabled: **443.1 ms → 382.1 ms** on this fixture and machine. It must not be
used as an on-device CoreELEC estimate.

## Remaining profile after the hoist

`cProfile` for one correction-enabled run recorded 0.600 CPU seconds.

| Function | Cumulative time | Calls | Interpretation |
| --- | ---: | ---: | --- |
| `_interval_overlap_score` | 0.582 s | 9,282 | Dominant remaining cost: overlap scans used by ratio ranking, global offset, and local windows. |
| `_scan_best_global_offset` | 0.386 s | 10 | Most of the detection ranking cost. |
| `detect_frame_rate_ratio` | 0.174 s | 1 | Sampled nine-ratio ranking pass. |
| `_estimate_global_offset` | 0.220 s | 1 | Existing global offset calculation. |
| `_build_offset_knots` | 0.198 s | 1 | Existing local window refinement. |

No further optimisation was performed after this profile. The intended next
step, if needed, is to review this profile on the actual CoreELEC hardware.
