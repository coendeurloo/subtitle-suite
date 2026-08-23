# -*- coding: utf-8 -*-
"""Kodi-independent validation for OpenAI subtitle translation batches."""

import re

SOURCE_ECHO_RETRY_RATIO = 0.80
MIN_MEANINGFUL_WORDS_FOR_ECHO_CHECK = 5

LANGUAGE_SCRIPT = {
    'ru': 'cyrillic', 'uk': 'cyrillic', 'bg': 'cyrillic', 'sr': 'cyrillic',
    'el': 'greek', 'ar': 'arabic', 'he': 'hebrew', 'fa': 'arabic',
    'hi': 'devanagari', 'bn': 'bengali', 'ja': 'cjk', 'ko': 'hangul',
    'zh': 'cjk',
}


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


def _meaningful_word_count(lines):
    count = 0
    for line in lines:
        visible = _as_text(line).replace('\\N', ' ')
        visible = re.sub(r'\{\\[^}]*\}', ' ', visible)
        visible = re.sub(r'<[^>]+>', ' ', visible)
        for word in re.findall(r'\w+', visible, flags=re.UNICODE):
            if sum(1 for character in word if character.isalpha()) >= 2:
                count += 1
    return count


def _language_script(language_code):
    code = _as_text(language_code).lower().split('-', 1)[0]
    return LANGUAGE_SCRIPT.get(code, 'latin')


def _dominant_script(value):
    counts = {
        'latin': 0, 'cyrillic': 0, 'greek': 0, 'arabic': 0,
        'hebrew': 0, 'devanagari': 0, 'bengali': 0, 'cjk': 0, 'hangul': 0,
    }
    for character in _visible_normalized_text(value):
        point = ord(character)
        if 0x0041 <= point <= 0x024F:
            counts['latin'] += 1
        elif 0x0400 <= point <= 0x052F:
            counts['cyrillic'] += 1
        elif 0x0370 <= point <= 0x03FF:
            counts['greek'] += 1
        elif 0x0600 <= point <= 0x06FF:
            counts['arabic'] += 1
        elif 0x0590 <= point <= 0x05FF:
            counts['hebrew'] += 1
        elif 0x0900 <= point <= 0x097F:
            counts['devanagari'] += 1
        elif 0x0980 <= point <= 0x09FF:
            counts['bengali'] += 1
        elif 0xAC00 <= point <= 0xD7AF:
            counts['hangul'] += 1
        elif 0x3040 <= point <= 0x30FF or 0x3400 <= point <= 0x9FFF:
            counts['cjk'] += 1
    script, count = max(counts.items(), key=lambda item: item[1])
    return script if count else ''


def _echo_error(message):
    error = TranslationValidationError(message)
    error.source_echo_check_fired = True
    return error


def validate_translation_block(source_lines, translated_lines, source_language_code='', target_language_code=''):
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

    if _meaningful_word_count(source) < MIN_MEANINGFUL_WORDS_FOR_ECHO_CHECK:
        return translated

    source_script = _language_script(source_language_code)
    target_script = _language_script(target_language_code)
    compare_scripts = source_script != target_script
    meaningful_count = 0
    unchanged_count = 0
    for source_line, translated_line in zip(source, translated):
        normalized_source = _visible_normalized_text(source_line)
        normalized_translation = _visible_normalized_text(translated_line)
        letter_count = sum(1 for character in normalized_source if character.isalpha())
        if letter_count < 4:
            continue
        meaningful_count += 1
        if compare_scripts:
            # For cross-script translation, text equality is not a useful
            # signal.  An echoed block instead retains the source script.
            if _dominant_script(source_line) == _dominant_script(translated_line):
                unchanged_count += 1
        elif normalized_source == normalized_translation:
            unchanged_count += 1

    if meaningful_count and (float(unchanged_count) / meaningful_count) >= SOURCE_ECHO_RETRY_RATIO:
        comparison = 'retained the source script' if compare_scripts else 'were unchanged'
        raise _echo_error(
            'source-language response detected: %d/%d meaningful lines %s'
            % (unchanged_count, meaningful_count, comparison)
        )

    return translated


def translate_block_with_one_retry(source_lines, request_translation, on_attempt_failure=None, source_language_code='', target_language_code=''):
    """Request and validate a block, retrying exactly once on any failure."""
    for attempt in range(1, 3):
        try:
            return validate_translation_block(
                source_lines,
                request_translation(),
                source_language_code=source_language_code,
                target_language_code=target_language_code,
            )
        except Exception as exc:
            if on_attempt_failure is not None:
                try:
                    on_attempt_failure(attempt, exc)
                except Exception:
                    pass
            if attempt == 2:
                raise
