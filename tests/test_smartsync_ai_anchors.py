import unittest

from resources.lib import smartsync


class Event(object):
    def __init__(self, start):
        self.start = start
        self.end = start + 1000
        self.text = 'Subtitle cue'


class Subs(object):
    def __init__(self, starts):
        self.events = [Event(start) for start in starts]


class SmartSyncAIAnchorTests(unittest.TestCase):
    def setUp(self):
        self.reference = Subs([1000, 4000, 7000, 10000, 13000])
        self.target = Subs([2000, 5000, 8000, 11000, 14000])

    def test_ordered_distinct_anchors_align_subtitles(self):
        pairs = [{'target_id': index, 'reference_id': index} for index in (0, 2, 4)]
        result = smartsync.sync_from_anchor_pairs(self.reference, self.target, pairs)
        self.assertFalse(result['low_confidence'])
        self.assertEqual(1000, result['synced_subs'].events[0].start)

    def test_reordered_anchors_are_rejected(self):
        pairs = [
            {'target_id': 0, 'reference_id': 0},
            {'target_id': 2, 'reference_id': 4},
            {'target_id': 4, 'reference_id': 2},
        ]
        with self.assertRaises(RuntimeError):
            smartsync.sync_from_anchor_pairs(self.reference, self.target, pairs)

    def test_sparse_anchors_are_rejected(self):
        pairs = [{'target_id': index, 'reference_id': index} for index in (0, 4)]
        with self.assertRaises(RuntimeError):
            smartsync.sync_from_anchor_pairs(self.reference, self.target, pairs)

    def test_large_anchor_jump_is_marked_low_confidence(self):
        reference = Subs([1000, 4000, 100000, 103000, 106000])
        pairs = [{'target_id': index, 'reference_id': index} for index in (0, 2, 4)]
        result = smartsync.sync_from_anchor_pairs(reference, self.target, pairs)
        self.assertTrue(result['low_confidence'])
        self.assertGreater(result['knot_max_jump_ms'], smartsync.KNOT_JUMP_LOW_CONFIDENCE_MS)


if __name__ == '__main__':
    unittest.main()
