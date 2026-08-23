# Changelog

## 2.9.9 — Unreleased

- Reused one action-scoped video context for playback metadata, file hashing, directory listings, filename language detection, subtitle samples, and provider searches.

## 2.9.8 — Unreleased

- Added an opt-in `Log timings` debug setting for menu, full-action, provider, SmartSync, and AI translation-block timings.
- Deferred loading `chardet` and `charset_normalizer` until subtitle encoding detection is actually needed.

## 2.9.7 — Unreleased

- Restoring a subtitle backup now stages and parses the replacement before an atomic swap, so a failed restore leaves the original subtitle untouched.
- AI translation now retries an invalid translation block once and stops with the block number if the response is incomplete or substantially echoes the source language.
- A stale temporary-directory cleanup failure is logged but no longer stops an add-on action.
