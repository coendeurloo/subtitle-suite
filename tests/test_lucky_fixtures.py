import json
import os
import unittest

from resources.lib.lucky_pipeline import lucky_decision_steps


class LuckyFixtureTests(unittest.TestCase):
    def _fixture(self, name):
        path = os.path.join(os.path.dirname(__file__), 'fixtures', name)
        with open(path, 'r') as fixture_file:
            return json.load(fixture_file)

    def test_recorded_single_fixture_matches_the_documented_order(self):
        fixture = self._fixture('lucky_single.json')
        actual = [step for step, _ in lucky_decision_steps(fixture['target_languages'])]
        self.assertEqual(fixture['expected_steps'], actual)

    def test_recorded_dual_fixture_matches_the_documented_order(self):
        fixture = self._fixture('lucky_dual.json')
        actual = [step for step, _ in lucky_decision_steps(fixture['target_languages'])]
        self.assertEqual(fixture['expected_steps'], actual)

    def test_single_and_dual_have_the_same_acquisition_order(self):
        single = self._fixture('lucky_single.json')
        dual = self._fixture('lucky_dual.json')
        self.assertEqual(single['expected_steps'][:-1], dual['expected_steps'][:-1])
