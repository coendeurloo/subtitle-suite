# -*- coding: utf-8 -*-
"""Small cancellable worker primitive with no Kodi dependency."""

import threading


class JobCancelled(RuntimeError):
    pass


class CancellableJob(object):
    """Run one callable in a daemon thread and expose cooperative cancellation.

    The callable receives a ``threading.Event`` and must check it before any
    irreversible work.  Network clients cannot safely kill a Python thread;
    callers therefore use a bounded request timeout and discard a cancelled
    job's result.
    """

    def __init__(self, operation):
        self._operation = operation
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.result = None
        self.error = None
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True

    def start(self):
        self._thread.start()
        return self

    def cancel(self):
        self.cancel_event.set()

    def is_done(self):
        return self.done_event.is_set()

    def wait(self, seconds=0.0):
        self.done_event.wait(seconds)
        return self.is_done()

    def get_result(self):
        if not self.is_done():
            raise RuntimeError('Background job is not complete.')
        if self.cancel_event.is_set():
            raise JobCancelled()
        if self.error is not None:
            raise self.error
        return self.result

    def _run(self):
        try:
            if self.cancel_event.is_set():
                raise JobCancelled()
            value = self._operation(self.cancel_event)
            if self.cancel_event.is_set():
                raise JobCancelled()
            self.result = value
        except Exception as exc:
            self.error = exc
        finally:
            self.done_event.set()
