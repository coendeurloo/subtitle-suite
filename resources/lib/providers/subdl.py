# -*- coding: utf-8 -*-

import re

from .base import (
    SubtitleProviderBase,
    ProviderAuthError,
    ProviderRequestError,
    _as_text,
    _to_int,
    _to_float,
    _extract_subtitle_bytes,
)

try:
    import json
except ImportError:
    import simplejson as json

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError


class SubDLProvider(SubtitleProviderBase):
    name = 'subdl'
    display_name = 'SubDL'
    api_url = 'https://api.subdl.com/api/v1/subtitles'
    download_root = 'https://dl.subdl.com'

    def __init__(self, config, logger=None):
        self.enabled = bool(config.get('enabled'))
        self.api_key = (config.get('api_key') or '').strip()
        self.timeout_seconds = int(config.get('timeout_seconds') or 45)
        self.user_agent = (config.get('user_agent') or 'DualSubtitles')
        self._log = logger

    def is_enabled(self):
        return self.enabled

    def validate_config(self):
        if not self.enabled:
            return False
        if not self.api_key:
            raise ProviderAuthError('SubDL API key is missing.')
        return True

    def _request_json(self, params):
        query_string = urlencode(params, doseq=True)
        url = '%s?%s' % (self.api_url, query_string)

        request = Request(url)
        request.add_header('User-Agent', self.user_agent)
        request.add_header('Accept', 'application/json')

        try:
            response = urlopen(request, timeout=self.timeout_seconds)
            body = response.read()
        except HTTPError as exc:
            body = ''
            try:
                body = exc.read().decode('utf-8', 'replace')
            except Exception:
                pass
            if int(getattr(exc, 'code', 0)) in [401, 403]:
                raise ProviderAuthError('SubDL authentication failed (%s).' % getattr(exc, 'code', 'unknown'))
            raise ProviderRequestError('SubDL request failed (%s): %s' % (getattr(exc, 'code', 'unknown'), body[:180]))
        except URLError as exc:
            raise ProviderRequestError('SubDL network error: %s' % exc)
        except Exception as exc:
            raise ProviderRequestError('SubDL request error: %s' % exc)

        try:
            return json.loads(body.decode('utf-8', 'replace'))
        except Exception as exc:
            raise ProviderRequestError('SubDL invalid JSON response: %s' % exc)

    def _request_binary(self, url):
        request = Request(url)
        request.add_header('User-Agent', self.user_agent)
        try:
            response = urlopen(request, timeout=self.timeout_seconds)
            return response.read()
        except HTTPError as exc:
            raise ProviderRequestError('SubDL download failed (%s).' % getattr(exc, 'code', 'unknown'))
        except Exception as exc:
            raise ProviderRequestError('SubDL download failed: %s' % exc)

    def search(self, context, language_code, max_results):
        self.validate_config()

        query = (context.get('query') or '').strip()
        if not query:
            query = (context.get('video_basename') or '').strip()
        if not query:
            raise ProviderRequestError('SubDL search query is empty.')

        video_basename = (context.get('video_basename') or query).strip()
        season = (context.get('season') or '').strip()
        episode = (context.get('episode') or '').strip()
        year = (context.get('year') or '').strip()
        imdb_id = _normalize_imdb_id(context.get('imdb_id') or '')

        aggregated = []
        seen = {}
        candidates = _build_query_candidates(query, video_basename)
        if imdb_id and not (season and episode):
            candidates = [''] + candidates

        for candidate in candidates:
            params = {
                'api_key': self.api_key,
                'languages': language_code,
                'subs_per_page': max(10, min(30, int(max_results) * 3)),
            }

            if season and episode:
                params.update({
                    'type': 'tv',
                    'film_name': candidate,
                    'file_name': video_basename,
                    'season_number': str(int(season)),
                    'episode_number': str(int(episode)),
                })
            else:
                params.update({'type': 'movie'})
                if imdb_id:
                    params['imdb_id'] = imdb_id
                elif candidate:
                    params['film_name'] = candidate
                else:
                    continue
            if year:
                params['year'] = year

            payload = self._request_json(params)
            if not isinstance(payload, dict):
                raise ProviderRequestError('SubDL response payload was not an object.')

            if not payload.get('status', False):
                message = _as_text(payload.get('message') or payload.get('error') or '').strip()
                if not message:
                    message = 'Unknown SubDL error.'
                lowered = message.lower()
                if 'api key' in lowered and ('invalid' in lowered or 'expired' in lowered or 'required' in lowered):
                    raise ProviderAuthError(message)
                if "can't find movie or tv" in lowered or 'cannot find movie or tv' in lowered:
                    continue
                raise ProviderRequestError(message)

            subtitles = payload.get('subtitles') or []
            if not subtitles:
                continue

            for item in self._normalize_subtitles(subtitles, language_code):
                key = _as_text(item.get('file_id', ''))
                if not key or key in seen:
                    continue
                seen[key] = True
                aggregated.append(item)

            if len(aggregated) >= max_results:
                break

        if not aggregated:
            return []

        aggregated.sort(key=lambda item: (-int(item.get('provider_score', 0)), -int(item.get('download_count', 0)), item.get('release_name', '').lower()))
        return aggregated[:max_results]

    def _normalize_subtitles(self, subtitles, language_code):
        normalized = []
        for item in subtitles:
            download_url = _as_text(item.get('url') or item.get('subtitle_url') or '').strip()
            if not download_url:
                continue

            release_name = _as_text(item.get('release_name') or item.get('name') or 'subtitle').strip() or 'subtitle'
            language = _as_text(item.get('language') or language_code or '').strip().lower()
            hearing_impaired = bool(item.get('hi') or item.get('hearing_impaired'))

            rating = _to_float(item.get('rating') or item.get('score'))
            download_count = _to_int(item.get('downloads') or item.get('download_count'))
            provider_score = int(min(100, (rating * 12.0) + (download_count / 120.0) * 45.0 + 20.0))

            sync_tier = ''
            raw_sync = item.get('sync')
            if raw_sync in [True, 1, '1', 'true', 'True', 'yes']:
                sync_tier = 'likely'

            normalized.append({
                'provider': self.display_name,
                'provider_key': self.name,
                'file_id': download_url,
                'language': language,
                'release_name': release_name,
                'hearing_impaired': hearing_impaired,
                'provider_score': provider_score,
                'download_count': download_count,
                'provider_sync_tier': sync_tier,
                'download_url': download_url,
                '_provider_ref': self,
            })
        return normalized

    def download(self, result):
        url = _as_text(result.get('download_url') or '').strip()
        if not url:
            raise ProviderRequestError('SubDL download URL is missing.')

        if not url.startswith('http://') and not url.startswith('https://'):
            if not url.startswith('/'):
                url = '/' + url
            url = self.download_root + url

        raw_data = self._request_binary(url)
        subtitle_bytes = _extract_subtitle_bytes(raw_data, provider_name=self.display_name)
        return {
            'content_bytes': subtitle_bytes,
            'extension': 'srt',
        }


def _build_query_candidates(query, video_basename):
    candidates = []
    options = [
        query,
        _clean_query_for_search(query),
        _clean_query_for_search(video_basename),
        _strip_year_token(_clean_query_for_search(query)),
        _strip_year_token(_clean_query_for_search(video_basename)),
    ]
    for option in options:
        normalized = _as_text(option).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in candidates:
            continue
        candidates.append(lowered)
    return candidates


def _clean_query_for_search(value):
    tokens = re.findall(r'[a-z0-9]+', _as_text(value).lower())
    if not tokens:
        return _as_text(value).strip()

    ignore_tokens = {
        '1080p', '720p', '2160p', '480p', 'x264', 'x265', 'h264', 'h265', 'hevc', 'bluray', 'brrip',
        'webdl', 'webrip', 'web', 'hdr', 'dv', 'aac', 'dts', 'ddp5', 'atmos', 'proper', 'repack', 'yts',
        'am', 'yify', 'rarbg',
    }

    filtered = []
    for token in tokens:
        if token in ignore_tokens:
            continue
        if re.match(r'^\d{3,4}p$', token):
            continue
        if len(token) <= 2 and not re.match(r'^\d{4}$', token):
            continue
        filtered.append(token)

    if not filtered:
        filtered = tokens
    return ' '.join(filtered[:8])


def _strip_year_token(value):
    tokens = re.findall(r'[a-z0-9]+', _as_text(value).lower())
    if not tokens:
        return _as_text(value).strip()
    stripped = [t for t in tokens if not re.match(r'^(19\d{2}|20\d{2})$', t)]
    return ' '.join(stripped or tokens)


def _normalize_imdb_id(value):
    imdb_id = _as_text(value).strip().lower()
    if not imdb_id:
        return ''
    if imdb_id.startswith('tt'):
        digits = re.sub(r'[^0-9]', '', imdb_id[2:])
        return ('tt%s' % digits) if digits else ''
    digits = re.sub(r'[^0-9]', '', imdb_id)
    return ('tt%s' % digits) if digits else ''
