import unittest

from resources.lib.translation_progress import TranslationRequestProgress


class TranslationRequestProgressTests(unittest.TestCase):
    def test_retry_countdown_and_new_attempt_reset_waiting_time(self):
        now = [100.0]
        progress = TranslationRequestProgress(clock=lambda: now[0])
        now[0] += 12
        self.assertEqual(12, progress.snapshot()['elapsed'])
        progress.report('retry_wait', delay=5, next_attempt=2)
        now[0] += 1.2
        self.assertEqual(4, progress.snapshot()['remaining'])
        now[0] += 8
        self.assertEqual(0, progress.snapshot()['remaining'])
        progress.attempt_started(2)
        self.assertEqual('waiting', progress.snapshot()['phase'])
        self.assertEqual(0, progress.snapshot()['elapsed'])
        self.assertEqual(2, progress.snapshot()['attempt'])

    def test_response_updates_preserve_phase_start_and_snapshots_are_independent(self):
        now = [100.0]
        progress = TranslationRequestProgress(clock=lambda: now[0])
        progress.report('receiving', response_bytes=0)
        now[0] += 2
        progress.report('receiving', response_bytes=2048)
        state = progress.snapshot()
        self.assertEqual(2, state['elapsed'])
        self.assertEqual(2048, state['response_bytes'])
        state['phase'] = 'changed'
        self.assertEqual('receiving', progress.snapshot()['phase'])
        progress.report('checking')
        self.assertEqual(0, progress.snapshot()['elapsed'])
