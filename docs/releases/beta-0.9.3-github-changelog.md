# Subtitle Suite - Beta 0.9.3

Release date: 2026-04-23

## Highlights

- Faster Kodi subtitle menu open by deferring heavy runtime imports until an action actually runs.
- Fixed local subtitle matching for filenames with trailing dots, including cases like `S03E03 - I.F.T..mkv`.
- Lucky settings are now exposed in the settings UI, so Kodi-visible configuration matches runtime behavior.
- Manual ZIP subtitle extraction is now safer and more defensive.
- Improved Kodi compatibility for dependency metadata, profile cache I/O, and file-hash handling on Kodi paths.

## Files

- Addon version bumped to `2.9.5` for Kodi update/install flow.
- Install zip: `service.subtitles.subtitlesuite-beta-0.9.3.zip`
- Versioned zip: `service.subtitles.subtitlesuite-2.9.5.zip`
