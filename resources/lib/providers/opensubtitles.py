# -*- coding: utf-8 -*-

import json
import time
import re

from ..languages import normalize_language_code
from ..subtitle_search import clean_filename_title

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
        self.user_agent = (config.get('user_agent') or 'SubtitleSuite')
        self.timeout_seconds = int(config.get('timeout_seconds') or 45)
        self.max_request_attempts = max(1, int(config.get('max_request_attempts') or 2))
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
            raise ProviderAuthError('OpenSubtitles setup is incomplete. Enter username, password, and API key.')
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

            timeout = self.timeout_seconds
            deadline = getattr(self, '_search_deadline', None)
            cancel_event = getattr(self, '_search_cancel_event', None)
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderRequestError('OpenSubtitles search cancelled.')
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderRequestError('OpenSubtitles search timed out.')
                timeout = min(timeout, remaining)
            try:
                response = urlopen(request, timeout=timeout)
                try:
                    body = response.read()
                finally:
                    response.close()
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
                    raise ProviderAuthError('OpenSubtitles login failed. Use your OpenSubtitles username (not email), password, and API key.')
                if status_code == 400 and ('invalid username' in lowered_body or 'invalid username/password' in lowered_body):
                    raise ProviderAuthError('OpenSubtitles login failed. Use your OpenSubtitles username (not email), not your email address.')
                if self._is_retryable_status(status_code) and attempt < self.max_request_attempts:
                    self._safe_log('retrying json request after HTTP %s for %s %s (attempt %d)' % (status_code, method, path, attempt))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles request failed (%s): %s' % (getattr(exc, 'code', 'unknown'), body[:180]))
            except URLError as exc:
                if attempt < self.max_request_attempts:
                    self._safe_log('retrying json request after network error for %s %s (attempt %d): %s' % (method, path, attempt, exc))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles network error: %s' % exc)
            except ValueError as exc:
                raise ProviderRequestError('OpenSubtitles invalid JSON response: %s' % exc)
            except Exception as exc:
                if attempt < self.max_request_attempts:
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
                if self._is_retryable_status(status_code) and attempt < self.max_request_attempts:
                    self._safe_log('retrying binary download after HTTP %s (attempt %d)' % (status_code, attempt))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles download request failed (%s).' % getattr(exc, 'code', 'unknown'))
            except URLError as exc:
                if attempt < self.max_request_attempts:
                    self._safe_log('retrying binary download after network error (attempt %d): %s' % (attempt, exc))
                    _retry_sleep(attempt)
                    continue
                raise ProviderRequestError('OpenSubtitles download request failed: %s' % exc)
            except Exception as exc:
                if attempt < self.max_request_attempts:
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

    @staticmethod
    def _flag(value):
        return value is True or str(value).lower() in ('1', 'true', 'yes')

    @staticmethod
    def _api_language(language_code):
        language = str(language_code or '').strip().lower().replace('_', '-')
        if language in ('pt-br', 'pt-pt', 'zh-cn', 'zh-tw'):
            return language
        language = normalize_language_code(language)
        return {'pt': 'pt-pt', 'zh': 'zh-cn'}.get(language, language)

    @staticmethod
    def _imdb_number(value):
        value = str(value or '').strip().lower()
        return value[2:] if re.match(r'^tt\d{7,10}$', value) else (
            value if re.match(r'^\d{7,10}$', value) else '')

    @staticmethod
    def _movie_title_key(value):
        title = re.sub(r'(?i)\.(?:srt|ass|ssa|sub|vtt)$', '', _as_text(value).strip())
        title = re.sub(r'^(?:19|20)\d{2}\s*[-:]\s*', '', title)
        title = clean_filename_title(title)
        return ''.join(character for character in title.casefold() if character.isalnum())

    @staticmethod
    def _feature_imdb_number(value):
        digits = _as_text(value).strip().lower()
        if digits.startswith('tt'):
            digits = digits[2:]
        return int(digits) if digits.isdigit() else 0

    def _movie_matches_context(self, attributes, context, filename, hash_match=False):
        """An API text search may return other films, even with title and year set."""
        if hash_match:
            return True

        feature = attributes.get('feature_details') or {}
        feature_type = _as_text(feature.get('feature_type')).strip().lower()
        if feature_type and feature_type != 'movie':
            return False

        expected_imdb = self._feature_imdb_number(context.get('imdb_id'))
        feature_imdb = self._feature_imdb_number(feature.get('imdb_id'))
        if expected_imdb and feature_imdb:
            return expected_imdb == feature_imdb

        expected_titles = set()
        for candidate in (context.get('original_title'), context.get('title'),
                          context.get('query'), context.get('video_basename')):
            key = self._movie_title_key(candidate)
            if key:
                expected_titles.add(key)
        if not expected_titles:
            return False

        feature_title = feature.get('title') or feature.get('movie_name')
        candidate_title = feature_title or attributes.get('release') or filename
        if self._movie_title_key(candidate_title) not in expected_titles:
            return False

        expected_year = _as_text(context.get('year')).strip()
        feature_year = _as_text(feature.get('year')).strip()
        if (re.match(r'^(?:19|20)\d{2}$', expected_year) and
                re.match(r'^(?:19|20)\d{2}$', feature_year) and
                expected_year != feature_year):
            return False
        return True

    def _search_plans(self, context):
        """Keep file, title-ID and text lookups separate, as in the official addon."""
        plans = []
        moviehash = context.get('video_hash') or context.get('file_hash')
        if moviehash:
            plans.append(('hash', {'moviehash': moviehash, 'moviehash_match': 'only'}))
        is_tvshow = bool(context.get('is_tvshow'))
        media_type = 'episode' if is_tvshow else 'movie'
        episode_filters = {}
        if is_tvshow:
            for source, target in [('season', 'season_number'), ('episode', 'episode_number')]:
                value = str(context.get(source, '')).strip()
                if value.isdigit():
                    episode_filters[target] = int(value)
        imdb_id = self._imdb_number(context.get('imdb_id'))
        parent_id = self._imdb_number(context.get('parent_imdb_id'))
        if parent_id and len(episode_filters) == 2:
            plans.append(('identity', dict(episode_filters, parent_imdb_id=parent_id, type='episode')))
        if imdb_id:
            plans.append(('identity', {'imdb_id': imdb_id, 'type': media_type}))
            # Kodi scrapers may supply the series ID instead of the episode ID.
            if is_tvshow and imdb_id != parent_id and len(episode_filters) == 2:
                plans.append(('identity', dict(episode_filters, parent_imdb_id=imdb_id, type='episode')))
        title = (context.get('tvshow_title') if is_tvshow else
                 context.get('original_title') or context.get('query') or context.get('title')) or context.get('query')
        if title:
            params = dict(episode_filters, query=str(title).strip(), type=media_type)
            year = str(context.get('year') or '')
            if not is_tvshow and re.match(r'^(19|20)\d{2}$', year):
                plans.append(('text', dict(params, year=year)))
            plans.append(('text', params))
        # A translated title may be all the player knows. Try the other title if needed.
        alternate = context.get('title') if not is_tvshow else ''
        if alternate and alternate != title:
            plans.append(('text', {'query': alternate, 'type': media_type}))
        return plans

    def _normalize_search_results(self, data, context, language, hash_lookup=False):
        normalized = []
        for item in data:
            attributes = item.get('attributes') or {}
            result_language = self._api_language(attributes.get('language') or language)
            if result_language != language:
                continue
            feature = attributes.get('feature_details') or {}
            # A full subtitle search should not offer just the foreign dialogue.
            if self._flag(attributes.get('foreign_parts_only')):
                continue
            if context.get('is_tvshow'):
                # Drop a known different episode, even if a broad lookup returned it.
                wrong_episode = False
                for source, field in [('season', 'season_number'), ('episode', 'episode_number')]:
                    expected, actual = context.get(source), feature.get(field)
                    if str(expected).isdigit() and actual is not None and str(actual).isdigit():
                        if int(expected) != int(actual):
                            wrong_episode = True
                if wrong_episode:
                    continue
            downloads = _to_int(attributes.get('download_count'))
            ratings = _to_float(attributes.get('ratings'))
            hash_match = hash_lookup and self._flag(attributes.get('moviehash_match'))
            for file_item in attributes.get('files') or []:
                file_id = _to_int(file_item.get('file_id'))
                if file_id <= 0:
                    continue
                filename = file_item.get('file_name') or ''
                if not context.get('is_tvshow') and not self._movie_matches_context(
                        attributes, context, filename, hash_match=hash_match):
                    continue
                release = attributes.get('release') or filename or feature.get('title') or 'subtitle'
                # Distinguish discs/files belonging to one release in the picker.
                if len(attributes.get('files') or []) > 1 and filename:
                    release = filename
                normalized.append({
                    'provider': self.display_name,
                    'provider_key': self.name,
                    'file_id': file_id,
                    'file_name': filename,
                    'language': result_language,
                    'release_name': release,
                    'hearing_impaired': self._flag(attributes.get('hearing_impaired')),
                    'provider_score': int(min(100, (downloads / 80.0) * 65.0 + ratings * 7.0)),
                    'download_count': downloads,
                    'rating': ratings,
                    'from_trusted': self._flag(attributes.get('from_trusted')),
                    'ai_translated': self._flag(attributes.get('ai_translated')),
                    'machine_translated': self._flag(attributes.get('machine_translated')),
                    'hash_match': hash_match,
                    'provider_sync_tier': 'exact' if hash_match else '',
                    '_provider_ref': self,
                })
        return normalized

    def search(self, context, language_code, max_results):
        language = self._api_language(language_code)
        plans = self._search_plans(context)
        if not plans:
            raise ProviderRequestError('Search query is empty.')
        self._search_deadline = time.monotonic() + self.timeout_seconds
        if context.get('deadline_at') is not None:
            self._search_deadline = min(self._search_deadline, context['deadline_at'])
        self._search_cancel_event = context.get('cancel_event')
        try:
            token = self._login()
            found = {}
            identity_found = False
            text_found = False
            requests = 0
            successful_requests = 0
            last_error = None
            for strategy, lookup in plans:
                if strategy == 'identity' and identity_found:
                    continue
                if strategy == 'text' and (identity_found or text_found):
                    continue
                # Fetch a whole page before ranking locally; do not keep only the
                # first 12 popular releases. Limit extra pages and fallback calls.
                for page in range(1, 3):
                    if (requests >= 6 or len(found) >= max_results or
                            time.monotonic() >= self._search_deadline or
                            (self._search_cancel_event is not None and self._search_cancel_event.is_set())):
                        break
                    params = dict(lookup, languages=language, page=page,
                                  order_by='download_count', order_direction='desc',
                                  foreign_parts_only='exclude')
                    requests += 1
                    try:
                        payload = self._request_json('GET', '/subtitles', token=token, query_params=params)
                    except ProviderAuthError:
                        raise
                    except ProviderRequestError as exc:
                        last_error = exc
                        self._safe_log('search %s page %d failed: %s' % (strategy, page, exc))
                        break
                    successful_requests += 1
                    page_items = payload.get('data') or []
                    matches = self._normalize_search_results(page_items, context, language,
                                                             hash_lookup=strategy == 'hash')
                    if matches and strategy == 'identity':
                        identity_found = True
                    if matches and strategy == 'text':
                        text_found = True
                    for result in matches:
                        previous = found.get(result['file_id'])
                        if previous is None or (result['hash_match'] and not previous['hash_match']):
                            found[result['file_id']] = result
                    self._safe_log('search %s page %d: %d candidates' % (strategy, page, len(matches)))
                    # The API can fill a page with unrelated films. A later
                    # page may still contain the title we actually searched for.
                    if not page_items or page >= _to_int(payload.get('total_pages') or 1):
                        break
            if not found and last_error is not None and successful_requests == 0:
                raise last_error
            # The caller ranks this pool against the playing release before
            # applying the user's display limit. Preserve verified file matches.
            return list(found.values())
        finally:
            self._search_deadline = None
            self._search_cancel_event = None

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
