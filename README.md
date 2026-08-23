# Subtitle Suite

Kodi subtitle addon for **download, SmartSync, dual subtitles, and AI translation**.

Subtitle Suite is built for real-world libraries where subtitle quality is mixed.  
The goal is simple: **fewer clicks, safer automation, better sync outcomes**.

## What It Does

- Multi-provider subtitle download (OpenSubtitles, SubDL, Podnadpisi, optional BSPlayer).
- Sync-likelihood ranking for results (`Exact`, `Likely`, `Unknown`).
- One-click automation with:
  - `I Feel Lucky (Single Subtitle)...`
  - `I Feel Lucky (Dual Subtitles)...`
- SmartSync that aligns a target subtitle against a known good reference subtitle.
- Dual subtitle playback for language learning and bilingual setups.
- AI translation fallback when target language subtitles are missing.
- Safe file strategy with backups in `DualSubtitles`.

## Main Menu Actions

- `Find & Download Subtitles...`
- `I Feel Lucky: One Subtitle...`
- `I Feel Lucky: Two Subtitles...`
- `Choose Two Subtitle Files...`
- `Fix Subtitle Timing (Manual)...`
- `Translate Subtitle (Manual)...`
- `Restore Previous Subtitle...`

### Opening settings

The subtitle search window treats every result as a subtitle file. To avoid a
misleading download-failed message, Subtitle Suite's settings are opened through
Kodi itself: open the context menu on **Subtitle Suite** in the subtitle service
list and choose **Settings**, or use **Add-ons** → **My add-ons** → **Subtitle
services** → **Subtitle Suite** → **Configure**.

## How Lucky Works

### Single Subtitle Lucky

1. Try local exact match.
2. Try provider download with strict trusted tiers (`Exact`, `Likely`).
3. Find English reference (`Exact`/`Likely`) and optionally preview-check it.
4. SmartSync against the English reference if needed.
5. AI fallback from English if target is still missing.
6. If still unresolved, show a **Top 3 risky candidates** prompt (explicit user choice).

### Dual Subtitle Lucky

1. Try local exact matches for both preferred languages.
2. Strict provider download for missing languages (`Exact`, `Likely` only).
3. Find English reference and optional sync preview.
4. SmartSync target subtitles to English reference when needed.
5. AI fallback from English for remaining missing language(s).
6. If still unresolved, show **Top 3 risky candidates** per missing language.

### Shared Lucky decision order

The Lucky engine receives an explicit list of target languages.  A single
subtitle action passes one language; a dual action passes two.  The decision
order is deliberately the same:

| Order | Single target | Dual targets |
| --- | --- | --- |
| 1 | Find a local match | Find local matches for both targets |
| 2 | Download trusted `Exact`/`Likely` result | Download trusted `Exact`/`Likely` result for each missing target |
| 3 | Find trusted English reference | Find one trusted English reference |
| 4 | Offer English sync preview when applicable | Offer English sync preview when applicable |
| 5 | SmartSync target to English reference | SmartSync each available target to English reference |
| 6 | Offer AI translation for a still-missing target | Offer AI translation for each still-missing target |
| 7 | Offer risky candidates only after explicit consent | Offer risky candidates per still-missing target only after explicit consent |
| 8 | Finalize one subtitle | Finalize the two subtitles |

The 90-second Lucky search budget is monotonic and is passed to each provider
search and download as its remaining timeout.  AI translation remains a
separate, explicitly confirmed step after the search phase.

Both Lucky actions now execute the same acquisition pipeline with one or two
target-language slots. Their presentation remains separate: one target is
activated as a single subtitle, while two targets use the existing dual
subtitle finalization path.

## Safe No-Match Behavior

Lucky does **not** silently pick bad unknown subtitles anymore.

When no reliable candidate exists:

- It first tries English-first fallback.
- Then it can present up to 3 risky candidates with clear reasons (title mismatch, low confidence, etc.).
- You choose to try or skip.
- If unresolved, Lucky stops clearly and offers recovery actions:
  - open manual download
  - run manual AI translate

## SmartSync

SmartSync works best when one subtitle is known to be in sync (usually English).

- Manual mode lets you pick target + reference explicitly.
- Lucky mode can apply SmartSync automatically after a trusted English reference is found.
- Replace mode creates a backup before overwrite. Restore stages and parses the backup before atomically replacing the original, so a failed restore keeps the existing subtitle untouched.
- SmartSync can correct common subtitle frame-rate conversions before aligning.
  `Correct common subtitle frame-rate differences` is enabled by default and
  can be disabled in settings when troubleshooting. The correction only runs
  when a known ratio clearly beats the runner-up candidate.

## AI Translation

AI translation is optional and manual key-based.

- Requires OpenAI API key and model in settings.
- Used as fallback in Lucky flows or directly via manual action.
- Progress now shows explicit direction (for example: `Translating English to Dutch using AI...`).
- Each response block must contain a complete translation. Invalid or source-echoed blocks retry once; a second failure stops the translation without changing an existing subtitle file.
- Playback is paused during translation steps and resumed afterward.

## Settings (Quick View)

- Your subtitle languages: choose the first and second languages you normally want.
- Language for One Subtitle mode: used only by `I Feel Lucky: One Subtitle`. Leave it disabled to use your first subtitle language.
- Downloader provider toggles and credentials/API keys.
- Lucky behavior toggles (download, SmartSync, AI fallback, English preview).
- SmartSync and timing controls.
- Dual subtitle layout and style controls.

## Performance Diagnostics

In `Addon Settings...` → `Debug`, enable `Log timings` only while measuring. The Kodi log then records elapsed milliseconds for the first menu item, menu build, the complete action, each subtitle-provider query, each SmartSync run, and each AI translation block. Disable it afterwards to keep normal logs quiet.

Each playback action also reuses one video context, avoiding repeated video hashing and folder/sample reads while it finds, downloads, syncs, or translates subtitles.

Provider searches now run in parallel worker threads. The progress dialog stays cancellable; cancellation discards late results and prevents a cancelled translation from replacing a subtitle. OpenSubtitles is capped at two attempts per request.

The last download language is remembered and preselected in the language picker. The last main-menu action is retained as the `subtitle_suite_last_used=true` list-item property for compatible skins. It currently marks the matching item for skins that choose to read it; Kodi's standard subtitle-search directory API does not provide a safe portable way to force focus to that item without changing the menu.

## File/Backup Policy

- Final selectable subtitle files stay in the video folder.
- Backups and generated helper artifacts are stored in `DualSubtitles`.
- `Restore Subtitle Backup...` stages and validates the latest backup before atomically restoring it.

## Credits

- Original addon and core idea by **peno64**: <https://github.com/peno64/service.subtitles.localsubtitle>
- Subtitle Suite is a heavily extended and redesigned fork focused on safe automation and modern subtitle workflows.
