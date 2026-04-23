# Subtitle Suite - Beta 0.9.3 (Kodi.tv forum update)

Hi all,

This update is focused on reliability and polish rather than adding a brand-new feature. The main goal was to make Subtitle Suite behave more predictably in real Kodi use, especially around menu opening, local subtitle matching, and settings consistency.

One visible improvement is that the subtitle provider menu now opens faster. In earlier builds, Kodi could sit on "Searching for subtitles" longer than expected even when Subtitle Suite only needed to show its menu. In **Beta 0.9.3**, the heavy runtime pieces are loaded lazily, so the plain menu path is lighter.

I also fixed an edge case with filenames that end in a dot before the extension, such as `S03E03 - I.F.T..mkv`. Those names could confuse local subtitle matching when files like `..en.srt` or `..nl.srt` were present. Matching is now more defensive and consistent.

Another cleanup in this build is settings alignment. A few Lucky options already existed in code but were not exposed clearly in the settings screen. Those toggles are now visible, so what Kodi shows is much closer to what the addon is actually using at runtime.

### What changed

- Faster menu open in the Kodi subtitle search screen by deferring heavy runtime bootstrap.
- Fixed local subtitle matching for trailing-dot filenames like `S03E03 - I.F.T..mkv`.
- Added visible Lucky settings for single-target language and Lucky behavior toggles.
- Improved manual ZIP subtitle extraction with safer temp handling and size limits.
- Improved Kodi compatibility: explicit `xbmc.python` dependency, safer profile cache I/O, and better file hash handling through `xbmcvfs`.

### Versioning

- Beta label: `0.9.3`
- Kodi addon version: `2.9.5`

Keep sharing weird filename cases, provider failures, and playback-specific issues. Those real-world edge cases are exactly what shaped this update.
