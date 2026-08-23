import unittest

from resources.lib.lucky_pipeline import LuckyDeadline, LuckyDeadlineExceeded, lucky_decision_steps


class LuckyDeadlineTests(unittest.TestCase):
    def test_remaining_time_decreases_from_one_fixed_deadline(self):
        clock = [100.0]
        deadline = LuckyDeadline(90, now=lambda: clock[0])
        self.assertEqual(90.0, deadline.require_remaining())
        clock[0] = 189.5
        self.assertEqual(0.5, deadline.require_remaining())

    def test_expired_deadline_raises(self):
        clock = [0.0]
        deadline = LuckyDeadline(1, now=lambda: clock[0])
        clock[0] = 1.0
        with self.assertRaises(LuckyDeadlineExceeded):
            deadline.require_remaining()


class LuckyDecisionOrderTests(unittest.TestCase):
    def test_single_and_dual_use_the_same_step_order(self):
        single_steps = [step for step, _ in lucky_decision_steps(['nl'])]
        dual_steps = [step for step, _ in lucky_decision_steps(['nl', 'en'])]
        self.assertEqual(single_steps, dual_steps)
        self.assertEqual(['nl'], lucky_decision_steps(['nl'])[0][1])
        self.assertEqual(['nl', 'en'], lucky_decision_steps(['nl', 'en'])[0][1])
