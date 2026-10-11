# -*- coding: utf-8 -*-
"""Kodi-independent helpers for identifying the video being searched."""

import re
import struct


def clean_filename_title(value):
    """Keep the title, including short words and non-Latin text, before release tags."""
    text = str(value or '').strip()
    text = re.sub(r'\.(mkv|mp4|avi|mov|m4v|ts|m2ts|wmv)$', '', text, flags=re.I)
    text = text.replace('.', ' ').replace('_', ' ')
    boundary = re.search(
        r'(?i)\b(?:s\d{1,3}[ -]?e\d{1,3}|\d{1,2}x\d{1,3}|'
        r'\d{3,4}p|bluray|blu[ -]?ray|brrip|bdrip|web[ -]?dl|webrip|'
        r'hdtv|dvdrip|remux|x26[45]|h26[45]|hevc)\b', text)
    if boundary:
        text = text[:boundary.start()]
    # A year at the start may be part of the title (e.g. 2001: A Space Odyssey).
    for year in re.finditer(r'\b(?:19|20)\d{2}\b', text):
        if text[:year.start()].strip(' -[]()'):
            text = text[:year.start()]
            break
    return ' '.join(text.strip(' -[]()').split())


def hash_video_blocks(file_size, first, last):
    """OpenSubtitles hash: size plus 64-bit words from the first/last 64 KiB."""
    if file_size < 131072 or len(first) != 65536 or len(last) != 65536:
        raise ValueError('Incomplete video data for hashing')
    total = file_size
    for block in (first, last):
        if not isinstance(block, (bytes, bytearray)):
            raise ValueError('Video hashing requires binary data')
        total += sum(word[0] for word in struct.iter_unpack('<Q', block))
    return '%016x' % (total & 0xFFFFFFFFFFFFFFFF)


def search_cache_key(provider_name, context, language, candidate_limit):
    fields = ('video_path', 'video_hash', 'file_hash', 'file_size', 'query',
              'title', 'original_title', 'tvshow_title', 'imdb_id',
              'parent_imdb_id', 'year', 'season', 'episode', 'is_tvshow')
    return (provider_name, language.lower(), candidate_limit) + tuple(
        str(context.get(field, '')) for field in fields)
