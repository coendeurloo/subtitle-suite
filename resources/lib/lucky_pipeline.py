# -*- coding: utf-8 -*-
"""Kodi-independent building blocks for the I Feel Lucky action."""

import time


class LuckyDeadlineExceeded(RuntimeError):
    """Raised when the fixed Lucky search budget has been consumed."""


class LuckyDeadline(object):
    """A monotonic, fixed action budget that can be passed to blocking work."""

    def __init__(self, seconds, now=None):
        self._clock = now or time.monotonic
        self.started_at = self._clock()
        self.deadline_at = self.started_at + float(seconds)

    def remaining_seconds(self):
        return max(0.0, self.deadline_at - self._clock())

    def require_remaining(self):
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise LuckyDeadlineExceeded()
        return remaining


def lucky_decision_steps(target_languages):
    """Return the shared Lucky decision order for one or more target languages.

    The caller supplies the explicit target-language list.  Every language
    receives the same per-target stages; the English-reference stages run once
    for the action.
    """
    languages = [language for language in (target_languages or []) if language]
    steps = ['local_match', 'trusted_download', 'english_reference', 'sync_preview', 'smartsync', 'ai_translation', 'risky_candidate_prompt', 'finalize']
    return [(step, list(languages)) for step in steps]
