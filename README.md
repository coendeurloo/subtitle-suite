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

- `Search & Download Subtitles...`
- `I Feel Lucky (Single Subtitle)...`
- `I Feel Lucky (Dual Subtitles)...`
- `Choose Dual Subtitles...`
- `Run Smart Sync (manual)...`
- `Translate Subtitle (manual)...`
- `Restore Subtitle Backup...`
- `Addon Settings...`

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
- Replace mode creates backup before overwrite.

## AI Translation

AI translation is optional and manual key-based.

- Requires OpenAI API key and model in settings.
- Used as fallback in Lucky flows or directly via manual action.
- Progress now shows explicit direction (for example: `Translating English to Dutch using AI...`).
- Playback is paused during translation steps and resumed afterward.

## Settings (Quick View)

- Preferred languages (`Preferred Language 1`, `Preferred Language 2`).
- Single-mode Lucky target language.
- Downloader provider toggles and credentials/API keys.
- Lucky behavior toggles (download, SmartSync, AI fallback, English preview).
- SmartSync and timing controls.
- Dual subtitle layout and style controls.

## File/Backup Policy

- Final selectable subtitle files stay in the video folder.
- Backups and generated helper artifacts are stored in `DualSubtitles`.
- `Restore Subtitle Backup...` restores latest backup safely.

## Credits

- Original addon and core idea by **peno64**: <https://github.com/peno64/service.subtitles.localsubtitle>
- Subtitle Suite is a heavily extended and redesigned fork focused on safe automation and modern subtitle workflows.
