# -*- coding: utf-8 -*-

import unittest

from resources.lib.translation_batches import (
    TRANSLATION_MAX_SOURCE_CHARACTERS,
    _split_translation_lines,
)


class TranslationBatchTests(unittest.TestCase):
  def test_nine_hundred_lines_are_split_without_reordering(self):
    lines = ['Line %d with enough subtitle text.' % (index) for index in range(900)]
    batches = _split_translation_lines(lines, 60)

    self.assertGreaterEqual(len(batches), 15)
    self.assertEqual(lines, [line for batch in batches for line in batch])
    self.assertTrue(all(batch for batch in batches))
    self.assertTrue(all(len(batch) <= 60 for batch in batches))
    self.assertTrue(all(
      sum(len(line) for line in batch) <= TRANSLATION_MAX_SOURCE_CHARACTERS
      for batch in batches
    ))
