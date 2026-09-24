# -*- coding: utf-8 -*-
"""Select subtitle pairs belonging to the video currently playing."""

import os
import re

from resources.lib.languages import ISO3_TO_ISO2, KNOWN_LANGUAGE_CODES


EPISODE_PATTERN = re.compile(r'(?i)(?:s(\d{1,3})[.\-_ ]?e(\d{1,3})|\b(\d{1,2})x(\d{1,3})\b)')
YEAR_PATTERN = re.compile(r'^(?:19|20)\d{2}$')
RELEASE_TOKENS = set([
    '2160p', '1080p', '720p', '576p', '480p', '4k', 'web', 'webdl',
    'webrip', 'bluray', 'bdrip', 'brrip', 'hdtv', 'dvdrip', 'remux',
    'x264', 'x265', 'h264', 'h265', 'hevc', 'hdr', 'hdr10', 'dovi',
])
SUBTITLE_SUFFIX_TOKENS = set(['translated', 'smartsync', 'proper', 'repack', 'forced', 'sdh', 'cc'])
LANGUAGE_TOKENS = KNOWN_LANGUAGE_CODES.union(set(ISO3_TO_ISO2.keys()))


def _stem(value):
    name = os.path.basename(value)
    if name.lower().endswith(('.srt', '.mkv', '.mp4', '.avi', '.mov', '.m4v')):
        return os.path.splitext(name)[0]
    return name


def _episode(value):
    match = EPISODE_PATTERN.search(_stem(value))
    if not match:
        return None
    season = match.group(1) or match.group(3)
    episode = match.group(2) or match.group(4)
    return int(season), int(episode), match.start()


def _title_tokens(value):
    tokens = re.findall(r'[a-z0-9]+', _stem(value).lower())
    title = []
    for token in tokens:
        if title and (YEAR_PATTERN.match(token) or token in RELEASE_TOKENS):
            break
        title.append(token)
    while len(title) > 1 and (title[-1] in LANGUAGE_TOKENS or title[-1] in SUBTITLE_SUFFIX_TOKENS):
        title.pop()
    return title


def subtitle_matches_video(video_basename, subtitle_path):
    """Require the same episode, or the same movie title and compatible year."""
    subtitle_name = os.path.basename(subtitle_path)
    if not subtitle_name.lower().endswith('.srt'):
        return False
    if subtitle_name.lower().endswith('.dual.srt') or subtitle_name.lower().startswith('smartsync-'):
        return False

    video_episode = _episode(video_basename)
    subtitle_episode = _episode(subtitle_name)
    if video_episode:
        if not subtitle_episode or video_episode[:2] != subtitle_episode[:2]:
            return False
        video_series = set(re.findall(r'[a-z0-9]+', _stem(video_basename)[:video_episode[2]].lower()))
        subtitle_series = set(re.findall(r'[a-z0-9]+', _stem(subtitle_name)[:subtitle_episode[2]].lower()))
        video_series.difference_update(('the', 'a', 'an'))
        subtitle_series.difference_update(('the', 'a', 'an'))
        return not video_series or not subtitle_series or subtitle_series.issubset(video_series)

    if subtitle_episode:
        return False
    video_years = set(token for token in re.findall(r'[a-z0-9]+', _stem(video_basename).lower()) if YEAR_PATTERN.match(token))
    subtitle_years = set(token for token in re.findall(r'[a-z0-9]+', _stem(subtitle_name).lower()) if YEAR_PATTERN.match(token))
    if video_years and subtitle_years and not video_years.intersection(subtitle_years):
        return False
    video_title = _title_tokens(video_basename)
    subtitle_title = _title_tokens(subtitle_name)
    return bool(video_title and subtitle_title and video_title == subtitle_title)


def build_subtitle_pairs(entries, preferred_codes=()):
    """Return distinct-language pairs with preferred languages shown first."""
    preferred = [str(code).lower() for code in preferred_codes if code]

    def sort_key(entry):
        code = str(entry.get('code') or 'unk').lower()
        rank = preferred.index(code) if code in preferred else len(preferred)
        return rank, code == 'unk', code, os.path.basename(entry['path']).lower()

    ordered = sorted(entries, key=sort_key)
    pairs = []
    for first_index, first in enumerate(ordered):
        for second in ordered[first_index + 1:]:
            first_code = str(first.get('code') or 'unk').lower()
            second_code = str(second.get('code') or 'unk').lower()
            if first_code != 'unk' and first_code == second_code:
                continue
            pairs.append((first, second))
    return pairs
