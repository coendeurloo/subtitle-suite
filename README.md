# Dual Subtitles for Kodi - service.subtitles.dualsubtitles

Dual subtitle addon for Kodi, focused on speed and fewer clicks.

## Credits

- Original addon and core idea by **peno64**:
  - Original project: <https://github.com/peno64/service.subtitles.localsubtitle>
- This repository is a customized fork focused on dual subtitles and smarter selection behavior.

## Main Features

- Dual-subtitle workflow only:
  - `Choose Dual Subtitles...`
  - `Addon Settings...`
- Smart start folder for browsing subtitles:
  1. current video folder (or last used first, configurable)
  2. last used subtitle folder
  3. Kodi `special://subtitles`
  4. Kodi default browser root
- Automatic subtitle matching based on:
  - current video filename
  - preferred language 1
  - preferred language 2
- Optional AI translation for missing preferred subtitles:
  - if one or both preferred subtitles are missing, the addon can offer a translate popup
  - you can choose a source `.srt` from the current video folder before translation starts
  - if both preferred languages are missing, both can be translated from a single source subtitle
  - translated file is written next to the source subtitle (for example `Movie-ru.srt`)
- Smart Sync for large timing drift:
  - detects likely mismatch between selected subtitles
  - asks whether to run Smart Sync
  - lets you pick sync target and reference subtitle manually
  - reference can also be a non-preferred language `.srt` from the video folder
  - writes backup as `*.srt.bak` before replacing target subtitle
- Supports `.srt` and `.zip` (zip must contain `.srt`).
- Keeps advanced dual-sub rendering options:
  - top/bottom (or left-right) layout
  - font, colors, outline/shadow, margins
  - minimum display time and auto-shift sync

## Settings Overview

### Auto Match

- `Preferred Language 1` and `Preferred Language 2`
- `Match Strictness`
  - `Strict`: only exact patterns like `Movie.nl.srt`, `Movie-nl.srt`, `Movie_nl.srt`
  - `Relaxed`: also allows extra tokens like `Movie.forced.nl.srt`
- `Start Folder Priority`
  - `Video folder first`
  - `Last used folder first`

### Fallback

- `No Match Behavior`
  - Manual pick both subtitles
  - Pick first subtitle only
  - Stop with message
- `Partial Match Behavior` (only one preferred language found)
  - Ask confirmation
  - Auto use found subtitle and ask missing
  - Ignore auto match and pick both manually
- `Require second subtitle`
  - If enabled, loading stops when second subtitle is missing (dual-only mode)
  - If disabled, single subtitle fallback is allowed

### AI Translation

- `Offer AI translation when preferred subtitles are missing`
- `OpenAI API Key`
- `OpenAI Model`
- `Lines per translation request`
- `OpenAI timeout (seconds)`
- Notes:
  - translation is only offered when preferred subtitles are missing
  - a popup asks whether to continue without translation or translate from a selected source `.srt`
  - for two missing preferred languages, both translations can be generated from one source subtitle
  - subtitle text is sent to OpenAI
  - output is always a real `.srt` in the same folder as the source subtitle
  - existing translated target file may be overwritten to keep content in sync

### Layout

- `Subtitle Layout`
  - Bottom-Top
  - Bottom, Left-Right
  - Bottom-Bottom
- `Swap Bottom/Left - Top/Right Subtitles`

### Timing and Sync

- `Enable Smart Sync (large timing differences)`
- Smart Sync behavior:
  - runs only in dual-subtitle mode
  - uses local timing alignment first
  - if confidence is low, lets you apply local result, try AI fallback, or skip
  - AI fallback is optional and asks consent before sending subtitle text
- `Minimal Time (milliseconds) Subtitles on Screen`
- `Auto Shift`
- `Time Difference Threshold (milliseconds)`

### Bottom/Left Style

- Font, character set, font size, bold
- Color/background
- Shadow, outline, vertical margin

### Top/Right Style

- Font, character set, font size, bold
- Color/background
- Shadow, outline, vertical margin

## Runtime Notifications

The addon shows short messages during use, for example:

- both subtitles were auto-matched
- only one language match was found
- no match was found and fallback was used
- subtitles loaded successfully
- loading/preparation errors
