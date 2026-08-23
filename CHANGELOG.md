# Changelog

## 2.9.17 — Unreleased

### Kodi subtitle-menu reliability

- Removed the non-subtitle Settings row from Kodi's subtitle-result list. Kodi tried to download that row after saving settings and showed a false "Subtitle download failed" notification.
- Documented Kodi's built-in settings route for Subtitle Suite.

## 2.9.16 — Unreleased

### Clearer settings

- Removed the unused legacy Lucky setting that some Kodi versions displayed as an untitled setting row.
- Reworded setting categories and Lucky options in plain language, including an explanation that a disabled One Subtitle language uses the first subtitle language.

## 2.9.15 — Unreleased

- Added conservative, sampled frame-rate ratio detection before local SmartSync alignment, with an opt-out setting enabled by default.
- Added frame-rate decision/timing metrics and pure synthetic SmartSync regression tests, including irregular cue rhythm and ±500 ms jitter.
- Reduced local overlap-loop overhead by caching interval lengths; see `docs/SMARTSYNC-PROFILE.md` for the measured development-machine profile.

## 2.9.14 — Unreleased

- Single Lucky now activates its acquired subtitle directly; only Dual Lucky uses the existing ASS merge path.

## 2.9.13 — Unreleased

- Routed Single and Dual Lucky through one target-slot acquisition pipeline; their final single/dual presentation paths remain separate.

## 2.9.12 — Unreleased

### Intentional Lucky Single behaviour changes

- Single Lucky now uses the target-slot auto-match path used by Dual Lucky for local subtitle discovery.
- Single Lucky now checks an available English reference before SmartSync, like Dual Lucky. `lucky_strict_english_preview` defaults to enabled and can disable this extra preview.

### Reliability and diagnostics

- The AI source-echo guard skips blocks with fewer than five meaningful words and uses script comparison for cross-script translations; every guard hit logs its block number.
- Added a CoreELEC on-device timing and regression checklist.

## 2.9.11 — Unreleased

- Moved provider searches and per-block OpenAI translation requests to cancellable worker jobs; enabled provider searches now start in parallel.
- Capped OpenSubtitles request retries at two attempts.
- Remembered and preselected the last download language; retained the last main action without changing menu structure.

## 2.9.10 — Unreleased

- Made the 90-second Lucky search budget propagate to English-reference and risky-candidate searches/downloads, in addition to trusted candidate searches.
- Documented and regression-tested the shared one-language/two-language Lucky decision order.

## 2.9.9 — Unreleased

- Reused one action-scoped video context for playback metadata, file hashing, directory listings, filename language detection, subtitle samples, and provider searches.

## 2.9.8 — Unreleased

- Added an opt-in `Log timings` debug setting for menu, full-action, provider, SmartSync, and AI translation-block timings.
- Deferred loading `chardet` and `charset_normalizer` until subtitle encoding detection is actually needed.

## 2.9.7 — Unreleased

- Restoring a subtitle backup now stages and parses the replacement before an atomic swap, so a failed restore leaves the original subtitle untouched.
- AI translation now retries an invalid translation block once and stops with the block number if the response is incomplete or substantially echoes the source language.
- A stale temporary-directory cleanup failure is logged but no longer stops an add-on action.
