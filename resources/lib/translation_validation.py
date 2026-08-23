# -*- coding: utf-8 -*-
"""Kodi-independent validation for OpenAI subtitle translation batches."""

import re

SOURCE_ECHO_RETRY_RATIO = 0.80


class TranslationValidationError(RuntimeError):
    """Raised when a translation response is unsafe to apply."""


def _as_text(value):
    if value is None:
        return u''
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return u'%s' % (value,)


def _visible_normalized_text(value):
    text = _as_text(value)
    text = text.replace('\\N', ' ')
    text = re.sub(r'\{\\[^}]*\}', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[^\w]+', '', text, flags=re.UNICODE)
    return text.casefold()


def validate_translation_block(source_lines, translated_lines):
    """Return safe translations or raise before any subtitle cue is changed.

    A response must have exactly one item per requested source line.  The
    validation also rejects a meaningful block that is substantially echoed
    back unchanged, which is the failure mode that previously wrote
    source-language text into a successful-looking translation file.  Short
    labels, numbers, and names can legitimately remain unchanged, so they do
    not independently fail a batch.
    """
    source = [_as_text(item) for item in source_lines]
    translated = [_as_text(item) for item in translated_lines]
    if len(translated) != len(source):
        raise TranslationValidationError(
            'translation count mismatch: got=%d expected=%d' % (len(translated), len(source))
        )

    meaningful_count = 0
    unchanged_count = 0
    for source_line, translated_line in zip(source, translated):
        normalized_source = _visible_normalized_text(source_line)
        normalized_translation = _visible_normalized_text(translated_line)
        letter_count = sum(1 for character in normalized_source if character.isalpha())
        if letter_count < 4:
            continue
        meaningful_count += 1
        if normalized_source == normalized_translation:
            unchanged_count += 1

    if meaningful_count and (float(unchanged_count) / meaningful_count) >= SOURCE_ECHO_RETRY_RATIO:
        raise TranslationValidationError(
            'source-language response detected: %d/%d meaningful lines were unchanged'
            % (unchanged_count, meaningful_count)
        )

    return translated


def translate_block_with_one_retry(source_lines, request_translation, on_attempt_failure=None):
    """Request and validate a block, retrying exactly once on any failure."""
    for attempt in range(1, 3):
        try:
            return validate_translation_block(source_lines, request_translation())
        except Exception as exc:
            if on_attempt_failure is not None:
                try:
                    on_attempt_failure(attempt, exc)
                except Exception:
                    pass
            if attempt == 2:
                raise
