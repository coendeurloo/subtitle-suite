# -*- coding: utf-8 -*-

import json
import time

from .base import (
    SubtitleProviderBase,
    ProviderAuthError,
    ProviderRequestError,
    _as_text,
    _to_int,
    _to_float,
    _extract_subtitle_bytes,
    _retry_sleep,
)

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError


class OpenSubtitlesProvider(SubtitleProviderBase):
    name = 'opensubtitles'
    display_name = 'OpenSubtitles'
    api_root = 'https://api.opensubtitles.com/api/v1'

    def __init__(self, config, logger=None):
        self.enabled = bool(config.get('enabled'))
        self.username = (config.get('username') or '').strip()
        self.password = (config.get('password') or '').strip()
        self.api_key = (config.get('api_key') or '').strip()
        self.user_agent = (config.get('user_agent') or 'DualSubtitles')
        self.timeout_seconds = int(config.get('timeout_seconds') or 45)
        self._token = ''
        self._base_url = self.api_root
        self._log = logger

    def _safe_log(self, message):
        if self._log is None:
            return
        try:
            self._log('[providers/%s] %s' % (self.name, message))
        except Exception:
            pass

    def is_enabled(self):
        return self.enabled

    def validate_config(self):
        if not self.enabled:
            return False
        if not self.api_key or not self.username or not self.password:
            raise ProviderAuthError('OpenSubtitles credentials are missing.')
        return True

    def _headers(self, token=''):
        headers = {
            'Api-Key': self.api_key,
            'User-Agent': self.user_agent,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if token:
            headers['Authorization'] = 'Bearer %s' % token
        return headers

    def _build_url(self, path, query_params=None):
        base_url = (self._base_url or self.api_root or '').rstrip('/')
        target_path = (path or '').strip()
        if target_path.startswith('http://') or target_path.startswith('https://'):
            url = target_path
        else:
            if not target_path.startswith('/'):
                target_path = '/%s' % target_path
            url = '%s%s' % (base_url, target_path)
        if query_params:
            url = '%s?%s' % (url, urlencode(query_params))
        return url

    def _is_retryable_status(self, status_code):
        try:
            return int(status_code) in [429, 500, 502, 503, 504]
        except Exception:
            return False

    def _request_json(self, method, path, payload=None, token='', query_params=None):
        url = self._build_url(path, query_params=query_params)
        attempt = 0
        while True:
            attempt += 1
            request_data = None
            if payload is not None:
                request_data = json.dumps(payload).encode('utf-8')
            request = Request(url, data=request_data)
            request.get_method = lambda: method

            for header_key, header_value in self._headers(token).items():
                request.add_header(header_key, header_value)

            try:
                response = urlopen(request, timeout=self.timeout_seconds)
                body = response.read()
                return json.loads(body.decode('utf-8', 'replace'))
            except HTTPError as exc:
                body = ''
                try:
                    body = exc.read().decode('utf-8', 'replace')
                except Exception:
                    pass
                status_code = int(getattr(exc, 'code', 0) or 0)
                lowered_body = body.lower()
                if status_code in [401, 403]:
                    raise ProviderAuthError('OpenSubtitles authentication failed (%s).' % getattr(exc, 'code', 'unknown'))
                if status_code == 400 and ('invalid username' in lowered_body or 'invalid username/password' in lowered_body):
                    raise ProviderAuthError('OpenSubtitles authentication failed (%s).' % getattr(exc, 'code', 'unknown'))
                if self._is_retryable_status(status_code) and attempt < 4:
                    self._safe_log('retrying json request after HTTP %s for %s %s (attempt %d)' % (status_code, method, path, attempt))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles request failed (%s): %s' % (getattr(exc, 'code', 'unknown'), body[:180]))
            except URLError as exc:
                if attempt < 4:
                    self._safe_log('retrying json request after network error for %s %s (attempt %d): %s' % (method, path, attempt, exc))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles network error: %s' % exc)
            except ValueError as exc:
                raise ProviderRequestError('OpenSubtitles invalid JSON response: %s' % exc)
            except Exception as exc:
                if attempt < 3:
                    self._safe_log('retrying json request after unexpected error for %s %s (attempt %d): %s' % (method, path, attempt, exc))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles request error: %s' % exc)

    def _request_binary(self, link):
        attempt = 0
        while True:
            attempt += 1
            request = Request(link)
            request.add_header('User-Agent', self.user_agent)
            request.add_header('Accept', '*/*')
            try:
                response = urlopen(request, timeout=self.timeout_seconds)
                return response.read()
            except HTTPError as exc:
                status_code = int(getattr(exc, 'code', 0) or 0)
                if self._is_retryable_status(status_code) and attempt < 4:
                    self._safe_log('retrying binary download after HTTP %s (attempt %d)' % (status_code, attempt))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles download request failed (%s).' % getattr(exc, 'code', 'unknown'))
            except URLError as exc:
                if attempt < 4:
                    self._safe_log('retrying binary download after network error (attempt %d): %s' % (attempt, exc))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles download request failed: %s' % exc)
            except Exception as exc:
                if attempt < 3:
                    self._safe_log('retrying binary download after unexpected error (attempt %d): %s' % (attempt, exc))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles download request failed: %s' % exc)

    def _login(self):
        if self._token:
            return self._token

        self.validate_config()
        payload = self._request_json(
            'POST',
            '/login',
            payload={
                'username': self.username,
                'password': self.password,
            },
            token='',
            query_params=None,
        )
        token = payload.get('token')
        if not token:
            raise ProviderAuthError('OpenSubtitles login did not return a token.')
        base_url = (payload.get('base_url') or '').strip()
        if base_url:
            if not base_url.startswith('http://') and not base_url.startswith('https://'):
                base_url = 'https://%s' % base_url.lstrip('/')
            self._base_url = '%s/api/v1' % base_url.rstrip('/')
        self._token = token
        return self._token

    def search(self, context, language_code, max_results):
        token = self._login()

        query = (context.get('query') or '').strip()
        if not query:
            query = (context.get('video_basename') or '').strip()
        if not query:
            raise ProviderRequestError('Search query is empty.')

        payload = self._request_json(
            'GET',
            '/subtitles',
            payload=None,
            token=token,
            query_params={
                'query': query,
                'languages': language_code,
                'order_by': 'download_count',
                'order_direction': 'desc',
            },
        )

        data = payload.get('data') or []
        normalized = []
        for item in data:
            attributes = item.get('attributes') or {}
            files = attributes.get('files') or []
            if not files:
                continue
            file_item = files[0] or {}
            file_id = file_item.get('file_id')
            if not file_id:
                continue

            download_count = _to_int(attributes.get('download_count'))
            ratings = _to_float(attributes.get('ratings'))
            provider_score = int(min(100, (download_count / 80.0) * 65.0 + ratings * 7.0))

            release_name = attributes.get('release') or ''
            if not release_name:
                release_name = file_item.get('file_name') or ''
            if not release_name:
                feature_details = attributes.get('feature_details') or {}
                release_name = feature_details.get('title') or 'subtitle'

            normalized.append({
                'provider': self.display_name,
                'provider_key': self.name,
                'file_id': int(file_id),
                'language': (attributes.get('language') or language_code or '').lower(),
                'release_name': release_name,
                'hearing_impaired': bool(attributes.get('hearing_impaired')),
                'provider_score': provider_score,
                'download_count': download_count,
                'rating': ratings,
                'provider_sync_tier': 'exact' if bool(attributes.get('moviehash_match', False)) else '',
                '_provider_ref': self,
            })

        normalized.sort(key=lambda item: (-item.get('provider_score', 0), -item.get('download_count', 0), item.get('release_name', '').lower()))
        return normalized[:max_results]

    def download(self, result):
        token = self._login()
        file_id = result.get('file_id')
        if not file_id:
            raise ProviderRequestError('Missing file id for download.')

        payload = self._request_json(
            'POST',
            '/download',
            payload={'file_id': int(file_id)},
            token=token,
            query_params=None,
        )

        link = payload.get('link')
        if not link:
            remaining = payload.get('remaining')
            if remaining == 0:
                raise ProviderRequestError('OpenSubtitles download limit reached.')
            raise ProviderRequestError('Download link missing in provider response.')

        raw_data = self._request_binary(link)
        subtitle_bytes = _extract_subtitle_bytes(
            raw_data,
            provider_name=self.display_name,
            filename=payload.get('file_name', ''),
        )
        return {
            'content_bytes': subtitle_bytes,
            'extension': 'srt',
        }
