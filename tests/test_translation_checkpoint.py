import os
import tempfile
import unittest

from resources.lib.translation_checkpoint import TranslationCheckpoint


class TranslationCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.source = os.path.join(self.work.name, 'source.srt')
        with open(self.source, 'w') as source:
            source.write('Original subtitle')

    def checkpoint(self, target='nl', model='model'):
        return TranslationCheckpoint(self.work.name, self.source, '/movie.en.srt', 'en', target, model)

    def test_round_trip_and_clear(self):
        checkpoint = self.checkpoint()
        self.assertEqual([], checkpoint.load())
        checkpoint.save(['Hallo', 'Hoe gaat het?'])
        self.assertEqual(['Hallo', 'Hoe gaat het?'], self.checkpoint().load())
        checkpoint.clear()
        self.assertEqual([], checkpoint.load())

    def test_source_language_model_or_content_changes_do_not_reuse_translations(self):
        self.checkpoint().save(['Hallo'])
        self.assertEqual([], self.checkpoint(target='ru').load())
        self.assertEqual([], self.checkpoint(model='other').load())
        with open(self.source, 'w') as source:
            source.write('Changed subtitle')
        self.assertEqual([], self.checkpoint().load())

    def test_corrupt_checkpoint_is_ignored(self):
        checkpoint = self.checkpoint()
        for data in ('incomplete json', '{"translations":[null]}', '[]'):
            with open(checkpoint.path, 'w') as source:
                source.write(data)
            self.assertEqual([], checkpoint.load())

    def test_replacing_checkpoint_preserves_unicode(self):
        checkpoint = self.checkpoint()
        checkpoint.save(['Hallo'])
        checkpoint.save(['Hallo', 'Спасибо'])
        self.assertEqual(['Hallo', 'Спасибо'], checkpoint.load())
        self.assertFalse(any(name.startswith('.translation-') for name in os.listdir(self.work.name)))
