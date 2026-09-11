# -*- coding: utf-8 -*-
"""Kodi-independent prompt construction for AI subtitle translation."""

import json

from resources.lib.languages import normalize_language_code


LANGUAGE_DISPLAY_NAMES = {
  'af': 'Afrikaans', 'sq': 'Albanian', 'ar': 'Arabic', 'hy': 'Armenian', 'az': 'Azerbaijani',
  'eu': 'Basque', 'be': 'Belarusian', 'bn': 'Bengali', 'bs': 'Bosnian', 'bg': 'Bulgarian',
  'ca': 'Catalan', 'zh': 'Chinese', 'hr': 'Croatian', 'cs': 'Czech', 'da': 'Danish',
  'nl': 'Dutch', 'en': 'English', 'et': 'Estonian', 'fi': 'Finnish', 'fr': 'French',
  'gl': 'Galician', 'ka': 'Georgian', 'de': 'German', 'el': 'Greek', 'he': 'Hebrew',
  'hi': 'Hindi', 'hu': 'Hungarian', 'is': 'Icelandic', 'id': 'Indonesian', 'ga': 'Irish',
  'it': 'Italian', 'ja': 'Japanese', 'kk': 'Kazakh', 'ko': 'Korean', 'lv': 'Latvian',
  'lt': 'Lithuanian', 'mk': 'Macedonian', 'ms': 'Malay', 'no': 'Norwegian', 'fa': 'Persian',
  'pl': 'Polish', 'pt': 'Portuguese', 'ro': 'Romanian', 'ru': 'Russian', 'sr': 'Serbian',
  'sk': 'Slovak', 'sl': 'Slovenian', 'es': 'Spanish', 'sv': 'Swedish', 'ta': 'Tamil',
  'th': 'Thai', 'tr': 'Turkish', 'uk': 'Ukrainian', 'ur': 'Urdu', 'vi': 'Vietnamese',
  'cy': 'Welsh',
}


def _as_text(value):
  if value is None:
    return u''
  if isinstance(value, bytes):
    return value.decode('utf-8', 'replace')
  return u'%s' % (value,)


def _language_display_name(code):
  raw_code = _as_text(code).strip()
  if not raw_code:
    return ''
  normalized_code = normalize_language_code(raw_code)
  if normalized_code in ('', 'auto'):
    return normalized_code or raw_code
  return LANGUAGE_DISPLAY_NAMES.get(normalized_code, raw_code)


def _language_hint(code, fallback):
  raw_code = _as_text(code).strip()
  normalized_code = normalize_language_code(raw_code)
  if not raw_code or raw_code.lower() == 'auto':
    return fallback
  display_name = _language_display_name(raw_code)
  if normalized_code in LANGUAGE_DISPLAY_NAMES:
    return '%s (%s)' % (display_name, normalized_code)
  return raw_code


def _build_translation_prompt(lines, source_language_code, target_language_code, context=None):
  source_hint = _language_hint(
    source_language_code,
    'the subtitle source language (auto-detect)',
  )
  target_hint = _language_hint(target_language_code, 'the target language')

  if not context:
    return (
      'You are a subtitle translator. Return only valid JSON.',
      (
        'Translate subtitle lines from %s to %s.\n'
        'Return JSON only with this exact format: {"translations":["..."]}\n'
        'Rules:\n'
        '- Keep the same number of items and same order.\n'
        '- Keep \\N markers and formatting tags like {\\i1} unchanged when present.\n'
        '- Do not add notes or extra fields.\n'
        '\nLines JSON:\n%s'
      ) % (
        source_hint,
        target_hint,
        json.dumps(lines, ensure_ascii=False)
      )
    )

  context_lines = []
  for label in ('title', 'year', 'kind', 'show_title', 'season', 'episode', 'genre'):
    value = _as_text(context.get(label, '')).strip()
    if value:
      context_lines.append('%s: %s' % (label.replace('_', ' '), value))
  plot = _as_text(context.get('plot', '')).strip()[:300]
  if plot:
    context_lines.append('plot: %s' % (plot))
  cast = context.get('cast') or []
  if cast:
    context_lines.append('cast: %s' % (', '.join([_as_text(item) for item in cast[:5]])))
  previous_source = context.get('previous_source_lines') or []
  previous_translated = context.get('previous_translated_lines') or []
  if previous_source:
    context_lines.append('previous source lines: %s' % json.dumps(previous_source[-3:], ensure_ascii=False))
  if previous_translated:
    context_lines.append('previous translated lines: %s' % json.dumps(previous_translated[-2:], ensure_ascii=False))

  return (
    'You are a subtitle translator. Return only valid JSON.',
    (
      'Translate subtitle lines from %s to %s.\n'
      'Return JSON only with this exact format: {"translations":["..."]}\n'
      'Rules:\n'
      '- Write natural, idiomatic target-language subtitles.\n'
      '- Use the same register as the previous block.\n'
      '- Keep proper names unchanged and spelled exactly as given.\n'
      '- Keep the same number of items and same order.\n'
      '- Never reorder or merge lines.\n'
      '- Keep \\N markers and formatting tags like {\\i1} unchanged when present.\n'
      '- Do not add notes or extra fields.\n'
      '\nContext:\n%s\n'
      '\nLines JSON:\n%s'
    ) % (
      source_hint,
      target_hint,
      '\n'.join(context_lines),
      json.dumps(lines, ensure_ascii=False)
    )
  )
