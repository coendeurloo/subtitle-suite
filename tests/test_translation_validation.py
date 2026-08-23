# -*- coding: utf-8 -*-

import unittest

from resources.lib.translation_validation import (
    TranslationValidationError,
    translate_block_with_one_retry,
    validate_translation_block,
)


class TranslationValidationTests(unittest.TestCase):
    def test_valid_translated_block_is_accepted(self):
        source = ['Hello there', 'How are you?']
        translated = ['Hallo daar', 'Hoe gaat het?']

        self.assertEqual(translated, validate_translation_block(source, translated))

    def test_missing_translation_is_rejected(self):
        with self.assertRaises(TranslationValidationError) as error:
            validate_translation_block(['Hello there', 'How are you?'], ['Hallo daar'])

        self.assertIn('count mismatch', str(error.exception))

    def test_unchanged_meaningful_block_is_rejected(self):
        with self.assertRaises(TranslationValidationError) as error:
            validate_translation_block(['Hello there', 'How are you?'], ['Hello there', 'How are you?'])

        self.assertIn('source-language response detected', str(error.exception))

    def test_mostly_unchanged_meaningful_block_is_rejected(self):
        source = ['Hello there', 'How are you?', 'Good evening', 'See you tomorrow', 'Thank you']
        translated = ['Hello there', 'How are you?', 'Good evening', 'See you tomorrow', 'Dank je']

        with self.assertRaises(TranslationValidationError):
            validate_translation_block(source, translated)

    def test_short_unchanged_labels_do_not_reject_a_translated_block(self):
        source = ['OK', 'Hello there']
        translated = ['OK', 'Hallo daar']

        self.assertEqual(translated, validate_translation_block(source, translated))

    def test_short_name_and_number_block_skips_echo_check(self):
        source = ['John!', '42', 'No!']
        self.assertEqual(source, validate_translation_block(source, list(source)))

    def test_cross_script_echo_is_rejected_by_script_comparison(self):
        source = ['Hello there', 'How are you?']
        with self.assertRaises(TranslationValidationError) as error:
            validate_translation_block(source, list(source), 'en', 'ru')

        self.assertIn('retained the source script', str(error.exception))

    def test_cross_script_translation_is_not_compared_as_identical_text(self):
        source = ['Hello there', 'How are you?']
        translated = ['Привет там', 'Как дела?']
        self.assertEqual(translated, validate_translation_block(source, translated, 'en', 'ru'))

    def test_source_echo_is_retried_once_before_a_valid_response_is_applied(self):
        source = ['Hello there', 'How are you?']
        responses = [list(source), ['Hallo daar', 'Hoe gaat het?']]
        failures = []

        def request_translation():
            return responses.pop(0)

        translated = translate_block_with_one_retry(
            source,
            request_translation,
            lambda attempt, error: failures.append((attempt, str(error))),
        )

        self.assertEqual(['Hallo daar', 'Hoe gaat het?'], translated)
        self.assertEqual(1, len(failures))
        self.assertEqual(1, failures[0][0])

    def test_source_echo_fails_loudly_after_the_single_retry(self):
        source = ['Hello there', 'How are you?']
        attempts = []

        with self.assertRaises(TranslationValidationError):
            translate_block_with_one_retry(
                source,
                lambda: list(source),
                lambda attempt, error: attempts.append(attempt),
            )

        self.assertEqual([1, 2], attempts)
