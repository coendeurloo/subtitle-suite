# -*- coding: utf-8 -*-
"""Kodi-independent batching for AI subtitle translation."""


TRANSLATION_MAX_SOURCE_CHARACTERS = 6000


def _as_text(value):
  if value is None:
    return u''
  if isinstance(value, bytes):
    return value.decode('utf-8', 'replace')
  return u'%s' % (value,)


def _split_translation_lines(lines, batch_size, max_characters=TRANSLATION_MAX_SOURCE_CHARACTERS):
  batches = []
  current = []
  current_characters = 0
  for line in lines:
    text = _as_text(line)
    line_characters = len(text)
    if current and (
      len(current) >= int(batch_size)
      or current_characters + line_characters > int(max_characters)
    ):
      batches.append(current)
      current = []
      current_characters = 0
    current.append(line)
    current_characters += line_characters
  if current:
    batches.append(current)
  return batches
