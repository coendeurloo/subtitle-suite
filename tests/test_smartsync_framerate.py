import copy
import unittest

from resources.lib import smartsync


class Event(object):
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class Subs(object):
    def __init__(self, events):
        self.events = events

    def __deepcopy__(self, memo):
        return Subs([Event(event.start, event.end, event.text) for event in self.events])


def _reference_subs(count=180):
    events = []
    start = 0
    for index in range(count):
        duration = 900 + ((index * 137) % 950)
        events.append(Event(start, start + duration, 'Cue %d' % index))
        start += 2450 + ((index * 593) % 2100)
    return Subs(events)


def _target_from_reference(reference, ratio=1.0, offset=0, jitter=None, rhythm=False):
    events = []
    for index, event in enumerate(reference.events):
        extra_jitter = jitter(index) if jitter else 0
        if rhythm and index % 11 == 0:
            continue
        start = int(round((event.start * ratio) + offset + extra_jitter))
        end = int(round((event.end * ratio) + offset + extra_jitter))
        events.append(Event(max(0, start), max(1, end), event.text))
        if rhythm and index % 17 == 0:
            events.append(Event(max(0, end + 250), max(1, end + 850), 'Extra %d' % index))
    return Subs(events)


class SmartSyncFrameRateTests(unittest.TestCase):
    RATIO_23976_TO_25 = 23.976 / 25.0

    def test_framerate_pair_detects_and_corrects_ratio(self):
        reference = _reference_subs()
        target = _target_from_reference(reference, ratio=self.RATIO_23976_TO_25)

        detected = smartsync.detect_frame_rate_ratio(reference, target)
        result = smartsync.sync_local(reference, target)

        self.assertTrue(detected['applied'])
        self.assertEqual('23.976/25', detected['name'])
        self.assertGreater(detected['margin'], smartsync.FPS_RATIO_MARGIN_THRESHOLD)
        self.assertTrue(result['fps_applied'])
        self.assertGreaterEqual(result['confidence'], smartsync.LOW_CONFIDENCE_THRESHOLD)

    def test_reverse_framerate_pair_detects_reverse_ratio(self):
        reference = _reference_subs()
        target = _target_from_reference(reference, ratio=25.0 / 23.976)
        detected = smartsync.detect_frame_rate_ratio(reference, target)

        self.assertTrue(detected['applied'])
        self.assertEqual('25/23.976', detected['name'])

    def test_in_sync_and_plain_offset_do_not_apply_framerate_correction(self):
        reference = _reference_subs()
        for target in (copy.deepcopy(reference), _target_from_reference(reference, offset=-3500)):
            detected = smartsync.detect_frame_rate_ratio(reference, target)
            self.assertFalse(detected['applied'])

    def test_different_cue_rhythm_with_correct_timing_does_not_apply_ratio(self):
        reference = _reference_subs()
        target = _target_from_reference(reference, rhythm=True, jitter=lambda index: (index % 5) * 80)
        detected = smartsync.detect_frame_rate_ratio(reference, target)
        self.assertFalse(detected['applied'])

    def test_framerate_cases_remain_confident_after_prescaling(self):
        reference = _reference_subs()
        cases = [
            _target_from_reference(reference, ratio=self.RATIO_23976_TO_25),
            _target_from_reference(reference, ratio=25.0 / 23.976),
            _target_from_reference(reference, ratio=self.RATIO_23976_TO_25, offset=-4200),
            _target_from_reference(reference, ratio=self.RATIO_23976_TO_25, rhythm=True),
            _target_from_reference(
                _reference_subs(450),
                ratio=self.RATIO_23976_TO_25,
                jitter=lambda index: -500 if index % 2 else 500,
            ),
        ]
        references = [reference, reference, reference, reference, _reference_subs(450)]
        for reference_case, target in zip(references, cases):
            result = smartsync.sync_local(reference_case, target)
            self.assertTrue(result['fps_applied'])
            self.assertGreaterEqual(result['confidence'], smartsync.LOW_CONFIDENCE_THRESHOLD)
