"""Share network status with Kodi's main thread without touching the UI."""

import threading
import time


class TranslationRequestProgress:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._status = {'phase': 'waiting', 'attempt': 1, 'started_at': clock()}

    def attempt_started(self, attempt):
        self.report('waiting', attempt=attempt)

    def report(self, phase, **details):
        with self._lock:
            if phase != self._status['phase'] or phase == 'waiting':
                self._status['started_at'] = self._clock()
            self._status.update(details, phase=phase)

    def snapshot(self):
        with self._lock:
            result = self._status.copy()
        elapsed = max(0, self._clock() - result.pop('started_at'))
        result['elapsed'] = int(elapsed)
        result['remaining'] = max(0, int(result.get('delay', 0) - elapsed + 0.999))
        return result
