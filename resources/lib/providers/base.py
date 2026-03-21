# -*- coding: utf-8 -*-

import gzip
import io
import time
import zipfile


class SubtitleProviderError(Exception):
    pass


class ProviderAuthError(SubtitleProviderError):
    pass


class ProviderRequestError(SubtitleProviderError):
    pass


class SubtitleProviderBase(object):
    name = 'provider'

    def is_enabled(self):
        return False

    def validate_config(self):
        return True

    def search(self, context, language_code, max_results):
        raise NotImplementedError

    def download(self, result):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Shared utility functions
# All providers should use these instead of maintaining their own copies.
# ---------------------------------------------------------------------------

def _as_text(value):
    """Safely convert any value to a unicode string."""
    if value is None:
        return ''
    try:
        if isinstance(value, bytes):
            return value.decode('utf-8', 'replace')
    except Exception:
        pass
    try:
        return str(value)
    except Exception:
        return ''


def _to_int(value):
    """Safely convert a value to int, returning 0 on failure."""
    try:
        return int(value)
    except Exception:
        return 0


def _to_float(value):
    """Safely convert a value to float, returning 0.0 on failure."""
    try:
        return float(value)
    except Exception:
        return 0.0


def _extract_subtitle_bytes(raw_data, provider_name='', filename=''):
    """
    Detect and unpack subtitle payload bytes.

    Handles:
    - gzip by magic bytes (\\x1f\\x8b)
    - zip (PK header) — extracts first .srt entry
    - gzip by filename extension as fallback
    - plain bytes (passed through unchanged)

    Raises ProviderRequestError on empty input or extraction failure.
    """
    if not raw_data:
        label = ('%s ' % provider_name) if provider_name else ''
        raise ProviderRequestError('%sdownload payload is empty.' % label)

    if raw_data[:2] == b'\x1f\x8b':
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw_data)) as gz_file:
                return gz_file.read()
        except Exception as exc:
            label = ('%s ' % provider_name) if provider_name else ''
            raise ProviderRequestError('%sgzip extraction failed: %s' % (label, exc))

    if raw_data[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(raw_data)) as zip_file:
                candidate_name = ''
                for file_name in zip_file.namelist():
                    if file_name.lower().endswith('.srt'):
                        candidate_name = file_name
                        break
                if not candidate_name:
                    label = ('%s ' % provider_name) if provider_name else ''
                    raise ProviderRequestError('%szip does not contain an .srt file.' % label)
                return zip_file.read(candidate_name)
        except ProviderRequestError:
            raise
        except Exception as exc:
            label = ('%s ' % provider_name) if provider_name else ''
            raise ProviderRequestError('%szip extraction failed: %s' % (label, exc))

    # Fallback: treat as gzip if the provider-supplied filename says so
    if filename and filename.lower().endswith('.gz'):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw_data)) as gz_file:
                return gz_file.read()
        except Exception:
            pass

    return raw_data


def _retry_sleep(attempt_index):
    """Exponential-ish back-off sleep between retry attempts (capped at 2.5 s)."""
    delay = min(2.5, 0.45 * max(1, int(attempt_index)))
    try:
        time.sleep(delay)
    except Exception:
        pass
