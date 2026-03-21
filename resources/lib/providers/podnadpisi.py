# -*- coding: utf-8 -*-

import difflib
import json
import re
import time

from .base import (
    SubtitleProviderBase,
    ProviderRequestError,
    _as_text,
    _to_int,
    _extract_subtitle_bytes,
)
from ..languages import ISO3_TO_ISO2

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError


class PodnadpisiProvider(SubtitleProviderBase):
    name = 'podnadpisi'
    display_name = 'Podnadpisi'
    api_url = 'https://www.podnapisi.net/subtitles/search/advanced'
    download_root = 'https://www.podnapisi.net/subtitles'

    def __init__(self, config, logger=None):
        self.enabled = bool(config.get('enabled'))
        self.timeout_seconds = int(config.get('timeout_seconds') or 45)
        self.user_agent = (config.get('user_agent') or 'DualSubtitles')
        self._log = logger

    def is_enabled(self):
        return self.enabled

    def validate_config(self):
        return bool(self.enabled)

    def _request_json(self, params, retry_on_failure=True):
        # Inspired by a4kSubtitles provider flow, re-implemented for DualSubtitles.
        query_string = urlencode(params, doseq=True)
        url = '%s?%s' % (self.api_url, query_string)

        request = Request(url)
        request.add_header('Accept', 'application/json')
        request.add_header('User-Agent', self.user_agent)

        try:
            response = urlopen(request, timeout=self.timeout_seconds)
            body = response.read()
        except HTTPError as exc:
            body = ''
            try:
                body = exc.read().decode('utf-8', 'replace')
            except Exception:
                pass
            status_code = int(getattr(exc, 'code', 0) or 0)
            if retry_on_failure and status_code >= 500:
                time.sleep(0.7)
                return self._request_json(params, retry_on_failure=False)
            if status_code == 429:
                # Podnadpisi rate-limits aggressively; treat as empty result instead of hard failure.
                return {'status': 'too-many-requests', 'data': []}
            raise ProviderRequestError('Podnadpisi request failed (%s): %s' % (getattr(exc, 'code', 'unknown'), body[:180]))
        except URLError as exc:
            if retry_on_failure:
                time.sleep(0.7)
                return self._request_json(params, retry_on_failure=False)
            raise ProviderRequestError('Podnadpisi network error: %s' % exc)
        except Exception as exc:
            if retry_on_failure:
                time.sleep(0.7)
                return self._request_json(params, retry_on_failure=False)
            raise ProviderRequestError('Podnadpisi request error: %s' % exc)

        try:
            return json.loads(body.decode('utf-8', 'replace'))
        except Exception as exc:
            raise ProviderRequestError('Podnadpisi invalid JSON response: %s' % exc)

    def _request_binary(self, url, retry_on_failure=True):
        request = Request(url)
        request.add_header('User-Agent', self.user_agent)
        try:
            response = urlopen(request, timeout=self.timeout_seconds)
            return response.read()
        except HTTPError as exc:
            status_code = int(getattr(exc, 'code', 0) or 0)
            if retry_on_failure and status_code >= 500:
                time.sleep(0.5)
                return self._request_binary(url, retry_on_failure=False)
            raise ProviderRequestError('Podnadpisi download failed (%s).' % getattr(exc, 'code', 'unknown'))
        except Exception as exc:
            if retry_on_failure:
                time.sleep(0.5)
                return self._request_binary(url, retry_on_failure=False)
            raise ProviderRequestError('Podnadpisi download failed: %s' % exc)

    def search(self, context, language_code, max_results):
        query = (context.get('query') or '').strip()
        if not query:
            query = (context.get('video_basename') or '').strip()
        if not query:
            raise ProviderRequestError('Podnadpisi search query is empty.')

        params = {'keywords': query, 'page': 1}

        season = (context.get('season') or '').strip()
        episode = (context.get('episode') or '').strip()
        year = (context.get('year') or '').strip()
        if season and episode:
            params['movie_type'] = ['tv-series', 'mini-series']
            params['seasons'] = str(int(season))
            params['episodes'] = str(int(episode))
        else:
            params['movie_type'] = ['movie']
        if year:
            params['year'] = year

        payload = self._request_json(params)
        if _as_text(payload.get('status', '')).lower() == 'too-many-requests':
            if self._log:
                try:
                    self._log('podnadpisi provider rate-limited (429); provider skipped for this run.')
                except Exception:
                    pass
            return []

        data = payload.get('data') or []
        video_basename = (context.get('video_basename') or '').strip()
        target_language = _normalize_language_code(language_code)
        normalized = []

        for item in data:
            publish_id = item.get('publish_id')
            if not publish_id:
                continue

            releases = item.get('custom_releases') or []
            release_name = _pick_release_name(video_basename, releases, item)
            language = _normalize_language_code(item.get('language') or language_code or '')
            if target_language and language and language != target_language:
                continue
            flags = item.get('flags') or []
            hearing_impaired = 'hearing_impaired' in flags
            downloads = _to_int(item.get('downloads') or item.get('download_count'))
            votes = _to_int(item.get('votes'))
            provider_score = int(min(100, (downloads / 80.0) * 75.0 + (votes / 40.0) * 25.0))
            sync_exact = _has_exact_release_match(video_basename, releases)

            normalized.append({
                'provider': self.display_name,
                'provider_key': self.name,
                'file_id': _as_text(publish_id),
                'language': language,
                'release_name': release_name,
                'hearing_impaired': bool(hearing_impaired),
                'provider_score': provider_score,
                'download_count': downloads,
                'provider_sync_tier': 'exact' if sync_exact else '',
                'download_url': '%s/%s/download' % (self.download_root, _as_text(publish_id)),
                '_provider_ref': self,
            })

        normalized.sort(key=lambda item: (-int(item.get('provider_score', 0)), -int(item.get('download_count', 0)), item.get('release_name', '').lower()))
        return normalized[:max_results]

    def download(self, result):
        url = result.get('download_url')
        if not url:
            file_id = _as_text(result.get('file_id', ''))
            if not file_id:
                raise ProviderRequestError('Podnadpisi missing download id.')
            url = '%s/%s/download' % (self.download_root, file_id)

        raw_data = self._request_binary(url)
        subtitle_bytes = _extract_subtitle_bytes(raw_data, provider_name=self.display_name)
        return {
            'content_bytes': subtitle_bytes,
            'extension': 'srt',
        }


def _normalize_release_name(value):
    text = _as_text(value).strip().lower()
    return re.sub(r'[^a-z0-9]+', '', text)


def _pick_release_name(video_basename, releases, payload_item):
    best_name = ''
    best_score = -1.0
    video_name = _as_text(video_basename).lower()

    for release_name in releases:
        candidate = _as_text(release_name).strip()
        if not candidate:
            continue
        score = difflib.SequenceMatcher(None, video_name, candidate.lower()).ratio()
        if score > best_score:
            best_score = score
            best_name = candidate

    if best_name:
        return best_name

    title = _as_text(payload_item.get('title') or payload_item.get('name') or '').strip()
    if title:
        return title
    return video_basename or 'subtitle'


def _has_exact_release_match(video_basename, releases):
    if not video_basename:
        return False
    normalized_video = _normalize_release_name(video_basename)
    if not normalized_video:
        return False
    return any(
        _normalize_release_name(r) == normalized_video
        for r in releases
        if _normalize_release_name(r)
    )


def _normalize_language_code(value):
    language = _as_text(value).strip().lower().split('-')[0]
    if not language:
        return ''
    if len(language) == 2:
        return language
    if len(language) == 3:
        return ISO3_TO_ISO2.get(language, language)
    return language
