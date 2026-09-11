# -*- coding: utf-8 -*-

import unittest

from resources.lib.translation_prompt import _build_translation_prompt, _language_display_name


class TranslationPromptTests(unittest.TestCase):
    def test_context_fields_are_included_and_limited(self):
        long_plot = 'x' * 400
        system, prompt = _build_translation_prompt(
            ['You are late.'],
            'en',
            'nl',
            {
                'title': 'Example',
                'year': '2025',
                'kind': 'TV show',
                'show_title': 'Example Show',
                'season': '2',
                'episode': '3',
                'genre': 'Drama',
                'plot': long_plot,
                'cast': ['Alice', 'Bob', 'Carol', 'Dan', 'Eve', 'Ignored'],
                'previous_source_lines': ['one', 'two', 'three', 'ignored'],
                'previous_translated_lines': ['een', 'twee', 'ignored'],
            },
        )

        self.assertIn('natural, idiomatic', prompt)
        self.assertIn('Example Show', prompt)
        self.assertIn('season: 2', prompt)
        self.assertIn('episode: 3', prompt)
        self.assertIn('Alice, Bob, Carol, Dan, Eve', prompt)
        self.assertNotIn('Ignored', prompt)
        self.assertNotIn('x' * 301, prompt)
        self.assertIn('three', prompt)
        self.assertIn('twee', prompt)

    def test_without_context_keeps_legacy_prompt_shape(self):
        system, prompt = _build_translation_prompt(['Hello'], 'en', 'nl')

        self.assertEqual('You are a subtitle translator. Return only valid JSON.', system)
        self.assertIn('Translate subtitle lines from English (en) to Dutch (nl).', prompt)
        self.assertIn('Lines JSON:', prompt)
        self.assertNotIn('Context:', prompt)
        self.assertNotIn('natural, idiomatic', prompt)

    def test_language_display_names_cover_aliases_and_fallbacks(self):
        self.assertEqual('Dutch', _language_display_name('nl'))
        self.assertEqual('Dutch', _language_display_name('nl-NL'))
        self.assertEqual('Dutch', _language_display_name('nld'))
        self.assertEqual('Russian', _language_display_name('ru'))
        self.assertEqual('English', _language_display_name('en'))
        self.assertEqual('auto', _language_display_name('auto'))
        self.assertEqual('', _language_display_name(''))
        self.assertEqual('xx-YY', _language_display_name('xx-YY'))

    def test_auto_source_keeps_existing_wording_and_names_target(self):
        _, prompt = _build_translation_prompt(['Hello'], 'auto', 'nl')

        self.assertIn(
            'Translate subtitle lines from the subtitle source language (auto-detect) to Dutch (nl).',
            prompt,
        )

    def test_context_prompt_uses_language_names(self):
        _, prompt = _build_translation_prompt(['Hello'], 'nld', 'en', {})

        self.assertIn('Translate subtitle lines from Dutch (nl) to English (en).', prompt)
