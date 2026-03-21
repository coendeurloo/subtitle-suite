# -*- coding: utf-8 -*-

import re
import time

from .base import (
    SubtitleProviderBase,
    ProviderRequestError,
    _as_text,
    _to_int,
    _to_float,
    _extract_subtitle_bytes,
)
from ..languages import ISO2_TO_ISO3, ISO3_TO_ISO2

try:
    import xml.etree.ElementTree as ET
except Exception:
    ET = None

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError


class BSPlayerProvider(SubtitleProviderBase):
    name = 'bsplayer'
    display_name = 'BSPlayer'
    _subdomains = [1, 2, 3, 4, 5, 6, 7, 8, 101, 102, 103, 104, 105, 106, 107, 108, 109]
    _soap_template = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
          'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
          'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
          'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
          'xmlns:ns1="{url}">'
          '<SOAP-ENV:Body SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            '<ns1:{action}>{params}</ns1:{action}>'
          '</SOAP-ENV:Body>'
        '</SOAP-ENV:Envelope>'
    )

    def __init__(self, config, logger=None):
        self.enabled = bool(config.get('enabled'))
        self.timeout_seconds = int(config.get('timeout_seconds') or 20)
        self.user_agent = (config.get('user_agent') or 'BSPlayer/2.x (SubtitleSuite)')
        self._log = logger
        self._subdomain_seed = int(time.time()) % len(self._subdomains)

    def is_enabled(self):
        return self.enabled

    def validate_config(self):
        if not self.enabled:
            return False
        if ET is None:
            raise ProviderRequestError('BSPlayer XML parser is unavailable.')
        return True

    def _endpoint(self):
        index = self._subdomain_seed % len(self._subdomains)
        self._subdomain_seed += 1
        return 'http://s%s.api.bsplayer-subtitles.com/v1.php' % self._subdomains[index]

    def _request_soap(self, action, params_xml, retry_on_failure=True):
        endpoint = self._endpoint()
        payload = self._soap_template.format(url=endpoint, action=action, params=params_xml)
        request = Request(endpoint, data=payload.encode('utf-8'))
        request.add_header('User-Agent', self.user_agent)
        request.add_header('Content-Type', 'text/xml; charset=utf-8')
        request.add_header('Connection', 'close')
        request.add_header('SOAPAction', '"%s#%s"' % (endpoint, action))

        try:
            response = urlopen(request, timeout=self.timeout_seconds)
            body = response.read()
        except HTTPError as exc:
            status_code = int(getattr(exc, 'code', 0) or 0)
            if retry_on_failure and status_code >= 500:
                time.sleep(0.8)
                return self._request_soap(action, params_xml, retry_on_failure=False)
            raise ProviderRequestError('BSPlayer request failed (%s).' % getattr(exc, 'code', 'unknown'))
        except URLError as exc:
            if retry_on_failure:
                time.sleep(0.8)
                return self._request_soap(action, params_xml, retry_on_failure=False)
            raise ProviderRequestError('BSPlayer network error: %s' % exc)
        except Exception as exc:
            if retry_on_failure:
                time.sleep(0.8)
                return self._request_soap(action, params_xml, retry_on_failure=False)
            raise ProviderRequestError('BSPlayer request error: %s' % exc)

        try:
            root = ET.fromstring(_as_text(body))
        except Exception as exc:
            raise ProviderRequestError('BSPlayer invalid XML response: %s' % exc)

        return_node = root.find('.//return')
        if return_node is None:
            raise ProviderRequestError('BSPlayer response did not include SOAP return node.')
        return return_node

    def _request_binary(self, url, retry_on_failure=True):
        request = Request(url)
        request.add_header('User-Agent', self.user_agent)
        try:
            response = urlopen(request, timeout=self.timeout_seconds)
            return response.read()
        except HTTPError as exc:
            status_code = int(getattr(exc, 'code', 0) or 0)
            if retry_on_failure and status_code >= 500:
                time.sleep(0.6)
                return self._request_binary(url, retry_on_failure=False)
            raise ProviderRequestError('BSPlayer download failed (%s).' % getattr(exc, 'code', 'unknown'))
        except Exception as exc:
            if retry_on_failure:
                time.sleep(0.6)
                return self._request_binary(url, retry_on_failure=False)
            raise ProviderRequestError('BSPlayer download failed: %s' % exc)

    def _login(self):
        params_xml = (
            '<username></username>'
            '<password></password>'
            '<AppID>BSPlayer v2.72</AppID>'
        )
        response = self._request_soap('logIn', params_xml)
        status_code = _soap_status_code(response)
        if status_code != '200':
            raise ProviderRequestError('BSPlayer login failed (%s).' % (status_code or 'unknown'))

        token = _node_text(response.find('data')).strip()
        if not token:
            raise ProviderRequestError('BSPlayer login token is missing.')
        return token

    def _logout(self, token):
        token_value = _as_text(token).strip()
        if not token_value:
            return
        try:
            self._request_soap('logOut', '<handle>%s</handle>' % token_value, retry_on_failure=False)
        except Exception:
            pass

    def search(self, context, language_code, max_results):
        self.validate_config()
        token = self._login()
        try:
            imdb_id = _normalize_imdb_numeric(context.get('imdb_id', ''))
            lang_ids = _bsplayer_language_ids(language_code)
            file_hash = _as_text(context.get('file_hash') or '').strip().lower()
            file_size = _to_int(context.get('file_size') or 0)
            params_xml = (
                '<handle>{token}</handle>'
                '<movieHash>{movie_hash}</movieHash>'
                '<movieSize>{movie_size}</movieSize>'
                '<languageId>{language_id}</languageId>'
                '<imdbId>{imdb_id}</imdbId>'
            ).format(
                token=token,
                movie_hash=file_hash or '0',
                movie_size=str(file_size if file_size > 0 else 0),
                language_id=','.join(lang_ids),
                imdb_id=imdb_id or '0',
            )

            response = self._request_soap('searchSubtitles', params_xml)
            status_code = _soap_status_code(response)
            if status_code not in ['200', '402']:
                return []

            items = response.findall('data/item')
            if not items:
                return []

            requested_language = _normalize_language_code(language_code)
            normalized = []
            for item in items:
                file_name = _node_text(item.find('subName')).strip()
                if not file_name:
                    file_name = _node_text(item.find('subFileName')).strip()
                if not file_name:
                    continue

                download_url = _node_text(item.find('subDownloadLink')).strip()
                if not download_url:
                    continue

                provider_rating = _to_float(_node_text(item.find('subRating')))
                provider_score = int(max(0, min(100, round(provider_rating * 10.0))))
                raw_language = _node_text(item.find('subLang')).strip().lower()
                normalized_language = _normalize_result_language(raw_language, requested_language)

                if file_hash:
                    sync_tier = 'exact'
                elif imdb_id:
                    sync_tier = 'likely'
                else:
                    sync_tier = ''

                normalized.append({
                    'provider': self.display_name,
                    'provider_key': self.name,
                    'file_id': '%s:%s' % (download_url, file_name),
                    'language': normalized_language,
                    'release_name': file_name,
                    'hearing_impaired': False,
                    'provider_score': provider_score,
                    'download_count': 0,
                    'provider_sync_tier': sync_tier,
                    'download_url': download_url,
                    '_provider_ref': self,
                })

            normalized.sort(key=lambda item: (-int(item.get('provider_score', 0)), item.get('release_name', '').lower()))
            return normalized[:max_results]
        finally:
            self._logout(token)

    def download(self, result):
        url = _as_text(result.get('download_url') or '').strip()
        if not url:
            raise ProviderRequestError('BSPlayer download URL is missing.')

        raw_data = self._request_binary(url)
        subtitle_bytes = _extract_subtitle_bytes(raw_data, provider_name=self.display_name)
        return {
            'content_bytes': subtitle_bytes,
            'extension': 'srt',
        }


def _soap_status_code(response_node):
    status_node = response_node.find('result/result')
    if status_node is not None and _node_text(status_node).strip():
        return _node_text(status_node).strip()
    status_node = response_node.find('result')
    if status_node is not None:
        return _node_text(status_node).strip()
    return ''


def _normalize_imdb_numeric(value):
    imdb_id = _as_text(value).strip().lower()
    if not imdb_id:
        return ''
    if imdb_id.startswith('tt'):
        imdb_id = imdb_id[2:]
    return re.sub(r'[^0-9]', '', imdb_id)


def _normalize_language_code(value):
    return _as_text(value).strip().lower().split('-')[0]


def _bsplayer_language_ids(language_code):
    code = _normalize_language_code(language_code)
    if code in ISO2_TO_ISO3:
        return [ISO2_TO_ISO3[code]]
    if len(code) == 3:
        return [code]
    return ['eng']


def _normalize_result_language(raw_language, fallback_language):
    raw = _as_text(raw_language).strip().lower()
    if not raw:
        return fallback_language or 'en'
    if len(raw) == 2:
        return raw
    if len(raw) == 3 and raw in ISO3_TO_ISO2:
        return ISO3_TO_ISO2[raw]
    return fallback_language or raw


def _node_text(node):
    if node is None:
        return ''
    text = getattr(node, 'text', '')
    return _as_text(text) if text is not None else ''
