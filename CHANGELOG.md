# Changelog

## 2.9.27 — 2026-11-11

- **I Feel Lucky is quicker.** It checks subtitles you already have, skips the long scan when a track clearly lines up, and remembers combinations that worked. It checks again if the video or any of the subtitle files change.
- **Better timing across the whole episode.** SmartSync checks the beginning, middle, and end. It can fix subtitles that gradually drift, adjust timing at a clear edit, and remove an extra recap when the rest of the episode lines up.
- **Better subtitle choices.** Lucky uses the series ID when available and can try another download if a track does not fit. It also rejects tracks labelled Russian that contain a large amount of dialogue in another language.
- **More useful previews.** The opening preview skips common credits and adverts. When timing is uncertain, Lucky shows the part that needs checking.
- **Progress and originals.** Automatic sync shows its progress and can be cancelled. It saves the corrected version separately so a new attempt can start from the original.
- **Smoother dual subtitle playback.** Kodi loads the combined track once, so its subtitle delay control can move both languages together.

## 2.9.26 — 2026-10-11

- Subtitle searches now hide results for other movies. OpenSubtitles can return unrelated films that share a year or words in the title.
- Subtitle Suite checks the movie ID first. When there is no ID to compare, it checks the title and year.
- If a page contains only other movies, the search still checks the next page. If no matching Dutch subtitle exists, it shows no results.

## 2.9.25 — 2026-10-11

- AI translation now shows the languages, current block, completed lines and elapsed time.
- The window explains when it is waiting for AI, receiving an answer, checking the translation or saving the subtitle.
- Connection retries show a countdown. An incomplete translation shows a separate retry message.
- The block counter stays correct when continuing a saved translation or retrying smaller blocks.
- The percentage counts completed text and reaches 100% after the subtitle is saved.

## 2.9.24 — 2026-10-11

- Fixing subtitle timing now shows what it is doing, with completed checks and elapsed time.
- The progress bar moves during playback-speed checks, timing comparisons and line adjustments.
- Cancel works during timing calculations and while waiting for AI.
- The progress window closes before asking how to save the result.

## 2.9.23 — 2026-10-11

- Subtitle search now uses the movie or episode ID and recognises matching video files.
- Series searches use the show name, season and episode, with a title search as a backup.
- More candidates are checked before the best results are shown, including a second page from OpenSubtitles.
- Matching video files come first; equally suitable subtitles favour human translations and trusted uploaders.
- Short titles such as **It** and **Up**, and titles in other alphabets, are kept intact.
- Searches skip subtitles containing only the foreign-language dialogue and include all files in a release.

## 2.9.22 — 2026-10-10

- Kodi stays awake while an AI subtitle translation is running.
- The progress window shows how many lines are done and how long it has waited.
- Cancel works while the plugin is waiting for a reply.
- If the connection fails, the next try continues where it stopped.
- A connection problem no longer starts many extra retries.

## 2.9.21 — 2026-09-24

- Added **Change subtitle pair...** for quickly choosing two available subtitle files for the current movie or episode.
- Improved AI translation validation, recovery from failed batches, and progress reporting.
- Removed the fixed overall deadline for an active AI translation request; stalled network operations still time out and retry.
- Added stricter checks for AI SmartSync anchor points.

## 2.9.20 — 2026-09-23

### Easier menu and subtitle position settings

- The actions you choose most often now move to the top of the menu.
- Open Subtitle Suite settings from the context menu on any action.
- The subtitle position settings now explain how positive and negative numbers move the text.

### More reliable AI translation

- Translation sends smaller blocks and retries temporary connection or server errors.
- If a block still fails, translation stops safely and does not save a mixed-language subtitle.
- A brief Kodi progress display issue no longer cancels a translation request.

## Earlier changes

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
