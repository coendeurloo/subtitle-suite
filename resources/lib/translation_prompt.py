# -*- coding: utf-8 -*-
"""Kodi-independent prompt construction for AI subtitle translation."""

import json


def _as_text(value):
  if value is None:
    return u''
  if isinstance(value, bytes):
    return value.decode('utf-8', 'replace')
  return u'%s' % (value,)


def _build_translation_prompt(lines, source_language_code, target_language_code, context=None):
  source_hint = source_language_code
  if not source_hint or source_hint == 'auto':
    source_hint = 'the subtitle source language (auto-detect)'

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
        target_language_code,
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
      target_language_code,
      '\n'.join(context_lines),
      json.dumps(lines, ensure_ascii=False)
    )
  )
