"""Thread-safe progress for timing work; percentages follow completed work."""

import threading


STAGE_RANGES = {
    'load_reference': (2, 5),
    'load_target': (5, 10),
    'prepare': (10, 12),
    'speed': (12, 30),
    'shift': (30, 50),
    'sections': (50, 78),
    'adjust': (78, 84),
    'check': (84, 88),
    'ai_wait': (88, 90),
    'ai_adjust': (90, 93),
    'ai_check': (93, 95),
}


class SmartSyncProgress(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._state = ('load_reference', 2, 0, 1)

    def report(self, stage, completed=0, total=1):
        low, high = STAGE_RANGES[stage]
        total = max(1, total)
        completed = max(0, min(completed, total))
        percent = int(low + (high - low) * completed / total)
        with self._lock:
            self._state = (stage, max(self._state[1], percent), completed, total)

    def snapshot(self):
        with self._lock:
            return self._state
