# -*- coding: utf-8 -*-

import os
import re
import sys
import json
import difflib
import struct
import time
import xbmc
import xbmcaddon
import xbmcgui,xbmcplugin
import xbmcvfs
import shutil

import uuid

try:
  import chardet
except Exception:
  chardet = None

try:
  from resources.lib.charset_normalizer.api import from_bytes
except Exception:
  from_bytes = None

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from resources.lib.dualsubs import mergesubs
from resources.lib import smartsync
from resources.lib.providers.registry import (
  get_enabled_subtitle_providers,
  ProviderAuthError,
  ProviderRequestError,
)
try:
  from resources.lib.downloadpicker import DownloadPickerDialog
except Exception:
  DownloadPickerDialog = None
# TODO: LuckyPreviewDialog is a planned feature; luckypreview.py does not exist yet.
LuckyPreviewDialog = None

__addon__ = xbmcaddon.Addon()
__author__     = __addon__.getAddonInfo('author')
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')
__version__    = __addon__.getAddonInfo('version')
__language__   = __addon__.getLocalizedString
LEGACY_ADDON_IDS = ['service.subtitles.dualsubtitles']
LEGACY_PROFILE_MIGRATION_SETTING = 'legacy_profile_migrated_from'

LANGUAGE_CODE_REGEX = re.compile(r'\(([a-z]{2,3}(?:-[a-z0-9]{2,8})?)\)\s*$', re.IGNORECASE)
LANGUAGE_SUFFIX_REGEX = re.compile(r'[._-]([a-z]{2,3}(?:-[a-z0-9]{2,8})?)$', re.IGNORECASE)
LANGUAGE_TOKEN_REGEX = re.compile(r'[._\-\s\[\]\(\)]+')
NOTIFY_INFO = getattr(xbmcgui, 'NOTIFICATION_INFO', '')
NOTIFY_WARNING = getattr(xbmcgui, 'NOTIFICATION_WARNING', '')
NOTIFY_ERROR = getattr(xbmcgui, 'NOTIFICATION_ERROR', '')
LOG_DEBUG = getattr(xbmc, 'LOGDEBUG', 0)
LOG_INFO = getattr(xbmc, 'LOGINFO', getattr(xbmc, 'LOGNOTICE', 1))
LOG_WARNING = getattr(xbmc, 'LOGWARNING', 2)
LOG_ERROR = getattr(xbmc, 'LOGERROR', 4)
OPENAI_CHAT_ENDPOINT = 'https://api.openai.com/v1/chat/completions'
DOWNLOAD_TIMEOUT_SECONDS = 45
# Keep AI translation stable by using fixed request sizing/timeouts.
# These are intentionally not user-configurable in addon settings.
OPENAI_TRANSLATION_BATCH_SIZE = 20
OPENAI_REQUEST_TIMEOUT_SECONDS = 180
FENCED_JSON_REGEX = re.compile(r'^```(?:json)?\s*(.*?)\s*```$', re.DOTALL)
# Language code data lives in resources/lib/languages.py — imported below.
from resources.lib.languages import (
  ISO3_TO_ISO2 as ISO3_TO_ISO2_LANGUAGE_CODES,
  LANGUAGE_CODE_ALIASES,
  KNOWN_LANGUAGE_CODES as KNOWN_SUBTITLE_LANGUAGE_CODES,
)
DOWNLOAD_PROVIDER_WARNING_SHOWN = {}
DOWNLOAD_PROVIDER_RUNTIME_DISABLED = {}
SYNC_TIER_PRIORITY = {
  'unknown': 0,
  'likely': 1,
  'exact': 2,
}
RELEASE_SOURCE_GROUPS = {
  'web': set(['web', 'webdl', 'webrip', 'webcap', 'webdlrip']),
  'bluray': set(['bluray', 'bdrip', 'brrip', 'bdrip', 'bdremux', 'remux', 'uhdbluray', 'uhdbdrip']),
  'dvd': set(['dvd', 'dvdrip', 'dvdscr', 'dvd5', 'dvd9']),
  'hdtv': set(['hdtv', 'pdtv']),
}
RELEASE_CODEC_GROUPS = {
  'h264': set(['x264', 'h264', '264', 'avc']),
  'h265': set(['x265', 'h265', '265', 'hevc']),
  'av1': set(['av1']),
  'xvid': set(['xvid', 'divx']),
}
RELEASE_HDR_GROUPS = {
  'hdr': set(['hdr', 'hdr10', 'hdr10plus', 'dv', 'dovi', 'dolbyvision', 'vision']),
  'sdr': set(['sdr', '8bit']),
}
RELEASE_AUDIO_TOKENS = set([
  'dts', 'dtshd', 'aac', 'ac3', 'dd', 'ddp', 'ddp5', 'dd5', 'atmos', 'truehd', 'eac3'
])
RELEASE_NOISE_TOKENS = set([
  'the', 'and', 'for', 'sub', 'subs', 'subtitle', 'subtitles', 'srt', 'proper', 'repack'
])
DOWNLOAD_PROVIDER_COLORS = {
  'opensubtitles': 'springgreen',
  'podnadpisi': 'orange',
  'subdl': 'deepskyblue',
  'bsplayer': 'gold',
}
LANGUAGE_FLAG_EMOJI = {
  'en': u'\U0001F1EC\U0001F1E7',
  'nl': u'\U0001F1F3\U0001F1F1',
  'ru': u'\U0001F1F7\U0001F1FA',
  'de': u'\U0001F1E9\U0001F1EA',
  'fr': u'\U0001F1EB\U0001F1F7',
  'es': u'\U0001F1EA\U0001F1F8',
  'it': u'\U0001F1EE\U0001F1F9',
  'pt': u'\U0001F1F5\U0001F1F9',
  'ja': u'\U0001F1EF\U0001F1F5',
  'ko': u'\U0001F1F0\U0001F1F7',
  'zh': u'\U0001F1E8\U0001F1F3',
  'ar': u'\U0001F1F8\U0001F1E6',
  'tr': u'\U0001F1F9\U0001F1F7',
  'sv': u'\U0001F1F8\U0001F1EA',
  'no': u'\U0001F1F3\U0001F1F4',
  'da': u'\U0001F1E9\U0001F1F0',
  'fi': u'\U0001F1EB\U0001F1EE',
  'pl': u'\U0001F1F5\U0001F1F1',
  'uk': u'\U0001F1FA\U0001F1E6',
}

translatePath = xbmcvfs.translatePath

__cwd__        = translatePath(__addon__.getAddonInfo('path'))

__resource__   = translatePath(os.path.join(__cwd__, 'resources', 'lib'))

__profile__    = translatePath(__addon__.getAddonInfo('profile'))

def _bootstrap_log(message, level=LOG_INFO):
  try:
    xbmc.log('[%s] %s' % (__scriptid__, message), level)
  except Exception:
    pass

def _listdir_safe(path):
  try:
    return xbmcvfs.listdir(path)
  except Exception:
    return ([], [])

def _copy_tree(src, dst):
  if not xbmcvfs.exists(dst):
    xbmcvfs.mkdirs(dst)

  directories, files = _listdir_safe(src)
  for file_name in files:
    source_file = os.path.join(src, file_name)
    destination_file = os.path.join(dst, file_name)
    if not xbmcvfs.copy(source_file, destination_file):
      raise IOError('copy failed: %s' % (source_file))

  for directory in directories:
    if directory.lower() == 'temp':
      continue
    _copy_tree(os.path.join(src, directory), os.path.join(dst, directory))

def _migrate_legacy_profile_if_needed():
  if __scriptid__ in LEGACY_ADDON_IDS:
    return

  migration_marker = __addon__.getSetting(LEGACY_PROFILE_MIGRATION_SETTING)
  if migration_marker:
    return

  if xbmcvfs.exists(os.path.join(__profile__, 'settings.xml')):
    return

  profile_root = os.path.dirname(os.path.normpath(__profile__))
  for legacy_addon_id in LEGACY_ADDON_IDS:
    legacy_profile_path = os.path.join(profile_root, legacy_addon_id)
    legacy_settings_path = os.path.join(legacy_profile_path, 'settings.xml')
    if not xbmcvfs.exists(legacy_settings_path):
      continue

    try:
      xbmcvfs.mkdirs(__profile__)
      _copy_tree(legacy_profile_path, __profile__)
      __addon__.setSetting(LEGACY_PROFILE_MIGRATION_SETTING, legacy_addon_id)
      _bootstrap_log('migrated profile settings from %s' % (legacy_addon_id), LOG_INFO)
      return
    except Exception as error:
      _bootstrap_log('profile migration failed from %s: %s' % (legacy_addon_id, error), LOG_WARNING)

_migrate_legacy_profile_if_needed()

__temp__       = translatePath(os.path.join(__profile__, 'temp', ''))

__media__      = translatePath(os.path.join(__cwd__, 'resources', 'media'))

__flags__      = translatePath(os.path.join(__media__, 'flags'))

__syncicons__  = translatePath(os.path.join(__media__, 'sync'))

DOWNLOAD_PICKER_XML = 'DualSubtitlesDownloadPicker.xml'
LUCKY_PREVIEW_XML = 'DualSubtitlesLuckyPreview.xml'

if xbmcvfs.exists(__temp__):
  shutil.rmtree(__temp__)
xbmcvfs.mkdirs(__temp__)

__msg_box__       = xbmcgui.Dialog()

__subtitlepath__  = translatePath("special://subtitles")
if __subtitlepath__ is None:
  __subtitlepath__ = ""

sys.path.append(__resource__)

# Make sure the manual search button is disabled
try:
  if xbmc.getCondVisibility("Window.IsActive(subtitlesearch)"):
      window = xbmcgui.Window(10153)
      window.getControl(160).setEnableCondition('!String.IsEqual(Control.GetLabel(100),"{}")'.format(__scriptname__))
except Exception:
  window = ''

def AddItem(name, url):
  listitem = xbmcgui.ListItem(label="", label2=name)
  listitem.setProperty("sync", "false")
  listitem.setProperty("hearing_imp", "false")
  xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def Search():
  AddItem(__language__(33162), "plugin://%s/?action=downloadmanual" % (__scriptid__))
  AddItem(__language__(33274), "plugin://%s/?action=ifeelluckysingle" % (__scriptid__))
  AddItem(__language__(33275), "plugin://%s/?action=ifeelluckydual" % (__scriptid__))
  AddItem(__language__(33004), "plugin://%s/?action=browsedual" % (__scriptid__))
  AddItem(__language__(33120), "plugin://%s/?action=smartsyncmanual" % (__scriptid__))
  AddItem(__language__(33121), "plugin://%s/?action=translatemanual" % (__scriptid__))
  AddItem(__language__(33150), "plugin://%s/?action=restorebackup" % (__scriptid__))
  AddItem(__language__(33008), "plugin://%s/?action=settings" % (__scriptid__))

def get_params(string=""):
  """Parse the Kodi plugin URL query string into a flat key→value dict."""
  paramstring = string if string else (sys.argv[2] if len(sys.argv) > 2 else "")
  paramstring = paramstring.lstrip('?')
  parsed = parse_qs(paramstring, keep_blank_values=False)
  # parse_qs returns lists; unwrap to single values for backwards compatibility.
  return {k: v[0] for k, v in parsed.items() if v}

params = get_params()

def unzip(zip_path, exts):
  filename = None
  for file_name in xbmcvfs.listdir(zip_path)[1]:
    target = os.path.join(__temp__, file_name)
    if os.path.splitext(target)[1].lower() in exts:
      filename = target
      break

  if filename is not None:
    xbmc.executebuiltin('Extract("%s","%s")' % (zip_path, __temp__), True)
  else:
    _notify(__language__(33007), NOTIFY_WARNING)
  return filename

def Download(filename):
  listitem = xbmcgui.ListItem(label=filename)
  xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=filename, listitem=listitem, isFolder=False)

def _apply_subtitle_to_player_now(subtitle_path):
  path = _as_text(subtitle_path).strip()
  if not path:
    return False
  try:
    player = xbmc.Player()
    if not player.isPlayingVideo():
      return False
    try:
      player.showSubtitles(True)
    except Exception:
      pass
    player.setSubtitles(path)
    return True
  except Exception as exc:
    _log('setSubtitles failed for %s (%s)' % (path, exc), LOG_WARNING)
    return False

def _refresh_active_subtitle_renderer(subtitle_path):
  """Force Kodi to refresh subtitle rendering without user scrubbing."""
  path = _as_text(subtitle_path).strip()
  if not path:
    return False
  try:
    player = xbmc.Player()
    if not player.isPlayingVideo():
      return False
    try:
      player.showSubtitles(False)
      xbmc.sleep(90)
    except Exception:
      pass
    player.setSubtitles(path)
    try:
      player.showSubtitles(True)
    except Exception:
      pass
    # A tiny seek refresh mirrors the manual timeline scrub workaround.
    try:
      current_time = float(max(0.0, player.getTime()))
      player.seekTime(current_time + 0.04)
    except Exception:
      pass
    return True
  except Exception as exc:
    _log('subtitle renderer refresh failed for %s (%s)' % (path, exc), LOG_WARNING)
    return False

def _equal_text(setting_value, message_id):
  return setting_value == str(message_id) or setting_value == __language__(message_id)

def _notify(message, icon=NOTIFY_INFO, timeout=4000):
  try:
    __msg_box__.notification(__scriptname__, message, icon, timeout)
  except Exception:
    try:
      xbmc.executebuiltin(u'Notification(%s,%s)' % (__scriptname__, message))
    except Exception:
      pass

def _log(message, level=LOG_INFO):
  try:
    xbmc.log('[%s] %s' % (__scriptid__, message), level)
  except Exception:
    pass

def _is_disallowed_browse_path(path):
  if not path:
    return True

  lower = path.lower()
  return lower.startswith('plugin://') or lower.startswith('pvr://')

def _exists_dir(path):
  try:
    if xbmcvfs.exists(path):
      return True
  except Exception:
    pass

  if path and not path.endswith('/'):
    try:
      if xbmcvfs.exists(path + '/'):
        return True
    except Exception:
      pass

  return False

def _is_usable_browse_dir(path):
  if not path:
    return False

  if _is_disallowed_browse_path(path):
    return False

  return _exists_dir(path)

def _get_start_folder_priority():
  setting = __addon__.getSetting('start_folder_priority')
  if _equal_text(setting, 33034):
    return 'last_used_first'
  return 'video_first'

def _get_no_match_behavior():
  setting = __addon__.getSetting('no_match_behavior')
  if _equal_text(setting, 33023):
    return 'first_only'
  if _equal_text(setting, 33024):
    return 'stop'
  return 'manual_both'

def _get_partial_match_behavior():
  setting = __addon__.getSetting('partial_match_behavior')
  if _equal_text(setting, 33026):
    return 'auto_use'
  if _equal_text(setting, 33027):
    return 'manual_both'
  return 'ask'

def _get_match_strictness():
  setting = __addon__.getSetting('match_strictness')
  if _equal_text(setting, 33031):
    return 'relaxed'
  return 'strict'

def _is_second_subtitle_required():
  return __addon__.getSetting('second_subtitle_required') == 'true'

def _current_video_context():
  try:
    video_file = xbmc.Player().getPlayingFile()
  except Exception:
    video_file = ''

  if not video_file:
    return '', ''

  if _is_disallowed_browse_path(video_file):
    return '', ''

  video_dir = os.path.dirname(video_file)
  if not _is_usable_browse_dir(video_dir):
    return '', ''

  video_name = os.path.splitext(os.path.basename(video_file))[0]
  return video_dir, video_name

def _current_video_file_path():
  try:
    video_file = xbmc.Player().getPlayingFile()
  except Exception:
    video_file = ''

  if not video_file:
    return ''
  if _is_disallowed_browse_path(video_file):
    return ''
  return video_file

def _compute_file_hash_and_size(file_path):
  if not file_path:
    return '', 0
  if file_path.startswith('plugin://'):
    return '', 0

  try:
    file_size = int(os.path.getsize(file_path))
  except Exception:
    return '', 0

  if file_size <= 0:
    return '', 0

  chunk_size = 65536
  if file_size < (chunk_size * 2):
    return '', file_size

  try:
    file_hash = file_size
    with open(file_path, 'rb') as file_handle:
      for _ in range(int(chunk_size / 8)):
        block = file_handle.read(8)
        if len(block) < 8:
          break
        file_hash += struct.unpack('<Q', block)[0]

      file_handle.seek(max(0, file_size - chunk_size), os.SEEK_SET)
      for _ in range(int(chunk_size / 8)):
        block = file_handle.read(8)
        if len(block) < 8:
          break
        file_hash += struct.unpack('<Q', block)[0]

    file_hash &= 0xFFFFFFFFFFFFFFFF
    return ('%016x' % (file_hash)), file_size
  except Exception:
    return '', file_size

def _normalize_imdb_id(value):
  imdb_id = _as_text(value).strip()
  if not imdb_id:
    return ''
  imdb_id = imdb_id.lower()
  if imdb_id.startswith('tt') and imdb_id[2:].isdigit():
    digits = imdb_id[2:]
    # IMDb title ids are effectively 7+ digits; reject short/non-standard ids from scrapers.
    if len(digits) < 7 or len(digits) > 10:
      return ''
    return 'tt%s' % (digits)
  digits = re.sub(r'[^0-9]', '', imdb_id)
  if digits:
    if len(digits) < 7 or len(digits) > 10:
      return ''
    return 'tt%s' % (digits)
  return ''

def _current_video_metadata():
  metadata = {
    'imdb_id': '',
    'title': '',
    'tvshow_title': '',
  }

  player = xbmc.Player()
  try:
    if not player.isPlayingVideo():
      return metadata
  except Exception:
    pass

  try:
    tag = player.getVideoInfoTag()
  except Exception:
    tag = None

  if tag:
    try:
      metadata['imdb_id'] = _normalize_imdb_id(tag.getIMDBNumber())
    except Exception:
      pass
    try:
      metadata['title'] = _as_text(tag.getTitle()).strip()
    except Exception:
      pass
    try:
      metadata['tvshow_title'] = _as_text(tag.getTVShowTitle()).strip()
    except Exception:
      pass

  if not metadata['imdb_id']:
    try:
      metadata['imdb_id'] = _normalize_imdb_id(xbmc.getInfoLabel('VideoPlayer.IMDBNumber'))
    except Exception:
      pass
  if not metadata['title']:
    try:
      metadata['title'] = _as_text(xbmc.getInfoLabel('VideoPlayer.Title')).strip()
    except Exception:
      pass
  if not metadata['tvshow_title']:
    try:
      metadata['tvshow_title'] = _as_text(xbmc.getInfoLabel('VideoPlayer.TVShowTitle')).strip()
    except Exception:
      pass

  return metadata

def _resolve_start_dir(video_dir):
  last_used = __addon__.getSetting('last_used_subtitle_dir')
  if _get_start_folder_priority() == 'last_used_first':
    candidates = [last_used, video_dir, __subtitlepath__]
  else:
    candidates = [video_dir, last_used, __subtitlepath__]

  for candidate in candidates:
    if _is_usable_browse_dir(candidate):
      return candidate
  return ''

def _parse_language_code(setting_id):
  language_value = __addon__.getSetting(setting_id)
  if not language_value or language_value == 'Disabled':
    return None

  match = LANGUAGE_CODE_REGEX.search(language_value)
  if match is not None:
    normalized = _canonicalize_language_code(match.group(1))
    if normalized:
      return normalized

  normalized = _canonicalize_language_code(language_value)
  if normalized:
    return normalized

  return None

def _language_label(setting_id):
  language_value = __addon__.getSetting(setting_id)
  if not language_value or language_value == 'Disabled':
    return __language__(33018)
  return language_value

def _as_text(value):
  if value is None:
    return u''
  try:
    if isinstance(value, bytes):
      return value.decode('utf-8', 'replace')
  except Exception:
    pass
  try:
    return str(value)
  except Exception:
    return ''

def _canonicalize_language_code(language_code):
  normalized = _as_text(language_code).strip()
  if not normalized:
    return ''

  normalized = normalized.replace('_', '-').lower()
  normalized = re.sub(r'\s+', '', normalized)
  if not normalized:
    return ''

  match = re.match(r'^([a-z]{2,3})(?:-([a-z0-9]{2,8}))?$', normalized)
  if match is None:
    return ''

  primary = match.group(1)
  if len(primary) == 3:
    primary = ISO3_TO_ISO2_LANGUAGE_CODES.get(primary, primary)

  if not re.match(r'^[a-z]{2,3}$', primary):
    return ''

  return primary

def _language_suffix_aliases(language_code):
  canonical = _canonicalize_language_code(language_code)
  if not canonical:
    return []

  aliases = [canonical]
  for alias in LANGUAGE_CODE_ALIASES.get(canonical, []):
    if alias not in aliases:
      aliases.append(alias)
  return aliases

def _language_tail_matches(tail_lower, language_code, strict):
  for alias in _language_suffix_aliases(language_code):
    if strict:
      pattern = r'^[._-]%s(?:-[a-z0-9]{2,8})?$' % (re.escape(alias))
      if re.match(pattern, tail_lower):
        return True
    else:
      pattern = r'[._-]%s(?:-[a-z0-9]{2,8})?$' % (re.escape(alias))
      if re.search(pattern, tail_lower):
        return True
  return False

def _to_utf8_bytes(text):
  if text is None:
    text = ''
  if isinstance(text, bytes):
    return text
  return _as_text(text).encode('utf-8')

def _get_int_setting(setting_id, default_value, minimum_value, maximum_value):
  value = __addon__.getSetting(setting_id)
  try:
    parsed = int(value)
  except Exception:
    parsed = default_value

  if parsed < minimum_value:
    return minimum_value
  if parsed > maximum_value:
    return maximum_value
  return parsed

def _get_bool_setting(setting_id, default_value=False):
  try:
    setting = __addon__.getSetting(setting_id)
  except Exception:
    return default_value
  if setting == '':
    return default_value
  return setting == 'true'

def _is_ai_translation_enabled():
  return __addon__.getSetting('enable_ai_translation') == 'true'

def _is_subtitle_download_enabled():
  return __addon__.getSetting('enable_subtitle_download') == 'true'

def _is_download_auto_on_missing():
  setting = __addon__.getSetting('download_auto_on_missing')
  if setting == '':
    return True
  return setting == 'true'

def _get_download_max_results():
  return _get_int_setting('download_max_results', 12, 3, 50)

def _is_opensubtitles_enabled():
  setting = __addon__.getSetting('provider_opensubtitles_enabled')
  if setting == '':
    return True
  return setting == 'true'

def _is_podnadpisi_enabled():
  setting = __addon__.getSetting('provider_podnadpisi_enabled')
  if setting == '':
    return True
  return setting == 'true'

def _is_subdl_enabled():
  setting = __addon__.getSetting('provider_subdl_enabled')
  if setting == '':
    return False
  return setting == 'true'

def _is_bsplayer_enabled():
  setting = __addon__.getSetting('provider_bsplayer_enabled')
  if setting == '':
    return False
  return setting == 'true'

def _get_opensubtitles_username():
  return __addon__.getSetting('provider_opensubtitles_username').strip()

def _get_opensubtitles_password():
  return __addon__.getSetting('provider_opensubtitles_password').strip()

def _get_opensubtitles_api_key():
  return __addon__.getSetting('provider_opensubtitles_api_key').strip()

def _get_subdl_api_key():
  return __addon__.getSetting('provider_subdl_api_key').strip()

def _build_download_provider_config():
  return {
    'opensubtitles': {
      'enabled': _is_opensubtitles_enabled(),
      'username': _get_opensubtitles_username(),
      'password': _get_opensubtitles_password(),
      'api_key': _get_opensubtitles_api_key(),
      'timeout_seconds': DOWNLOAD_TIMEOUT_SECONDS,
      'user_agent': 'SubtitleSuite/%s' % (__version__),
    },
    'podnadpisi': {
      'enabled': _is_podnadpisi_enabled(),
      'timeout_seconds': DOWNLOAD_TIMEOUT_SECONDS,
      'user_agent': 'SubtitleSuite/%s' % (__version__),
    },
    'subdl': {
      'enabled': _is_subdl_enabled(),
      'api_key': _get_subdl_api_key(),
      'timeout_seconds': DOWNLOAD_TIMEOUT_SECONDS,
      'user_agent': 'SubtitleSuite/%s' % (__version__),
    },
    'bsplayer': {
      'enabled': _is_bsplayer_enabled(),
      'timeout_seconds': 20,
      'user_agent': 'BSPlayer/2.x (SubtitleSuite/%s)' % (__version__),
    },
  }

def _is_smart_sync_enabled():
  setting = __addon__.getSetting('enable_smart_sync')
  if setting == '':
    return True
  return setting == 'true'

def _is_lucky_download_enabled():
  # Lucky download follows the main download toggle; always enabled by default.
  lucky_explicit = __addon__.getSetting('lucky_enable_download')
  if lucky_explicit in ('true', 'false'):
    return lucky_explicit == 'true'
  return _is_subtitle_download_enabled() if __addon__.getSetting('enable_subtitle_download') != '' else True

def _is_lucky_smartsync_enabled():
  return _get_bool_setting('lucky_enable_smartsync', True)

def _is_lucky_allow_english_likely():
  return _get_bool_setting('lucky_allow_english_likely', True)

def _is_lucky_ai_translate_enabled():
  return _get_bool_setting('lucky_enable_ai_translate', True)

def _is_lucky_continue_on_partial():
  # Legacy setting kept for backward compatibility in stored settings.
  # I Feel Lucky flow is now strict 2-target and no longer uses this toggle.
  return _get_bool_setting('lucky_continue_on_partial', True)

def _is_lucky_prompt_english_test_enabled():
  return _get_bool_setting('lucky_prompt_english_test', True)

def _get_smart_sync_mode():
  setting = __addon__.getSetting('smart_sync_mode')
  if _equal_text(setting, 33146):
    return 'auto_prompt'
  return 'manual_only'

def _get_openai_api_key():
  try:
    return __addon__.getSetting('openai_api_key').strip()
  except Exception:
    return ''

def _get_openai_model():
  model = __addon__.getSetting('openai_model')
  if not model:
    model = 'gpt-4.1-mini'
  return model.strip()

def _get_translation_batch_size():
  return OPENAI_TRANSLATION_BATCH_SIZE

def _get_translation_timeout_seconds():
  return OPENAI_REQUEST_TIMEOUT_SECONDS

def _progress_update(progress, percent, line1='', line2=''):
  if progress is None:
    return

  if percent < 0:
    percent = 0
  if percent > 100:
    percent = 100

  try:
    progress.update(percent, line1, line2)
    return
  except Exception:
    pass

  try:
    progress.update(percent, line1)
    return
  except Exception:
    pass

  try:
    progress.update(percent)
  except Exception:
    pass

def _extract_json_payload(raw_content):
  content = _as_text(raw_content).strip()
  if not content:
    raise RuntimeError('OpenAI returned an empty response.')

  fence_match = FENCED_JSON_REGEX.match(content)
  if fence_match:
    content = fence_match.group(1).strip()

  if not content.startswith('{'):
    start_index = content.find('{')
    end_index = content.rfind('}')
    if start_index >= 0 and end_index > start_index:
      content = content[start_index:end_index + 1]

  payload = json.loads(content)
  if not isinstance(payload, dict):
    raise RuntimeError('OpenAI returned an invalid JSON payload.')
  return payload

def _openai_translate_lines(lines, source_language_code, target_language_code, api_key, model, timeout_seconds):
  source_hint = source_language_code
  if not source_hint or source_hint == 'auto':
    source_hint = 'the subtitle source language (auto-detect)'

  user_prompt = (
    'Translate subtitle lines from %s to %s.\n'
    'Return JSON only with this exact format: {"translations":["..."]}\n'
    'Rules:\n'
    '- Keep the same number of items and same order.\n'
    '- Keep \\N markers and formatting tags like {\\i1} unchanged when present.\n'
    '- Do not add notes or extra fields.\n'
    '\nLines JSON:\n%s'
  ) % (
    source_hint,
    target_language_code,
    json.dumps(lines, ensure_ascii=False)
  )

  request_payload = {
    'model': model,
    'temperature': 0,
    'messages': [
      {
        'role': 'system',
        'content': 'You are a subtitle translator. Return only valid JSON.'
      },
      {
        'role': 'user',
        'content': user_prompt
      }
    ]
  }

  request_data = _to_utf8_bytes(json.dumps(request_payload, ensure_ascii=False))
  request = Request(OPENAI_CHAT_ENDPOINT, data=request_data)
  request.add_header('Content-Type', 'application/json')
  request.add_header('Authorization', 'Bearer %s' % (api_key))

  try:
    response = urlopen(request, timeout=timeout_seconds)
    raw_response = response.read()
  except HTTPError as exc:
    body = ''
    try:
      body = _as_text(exc.read())
    except Exception:
      pass
    _log('openai request failed: code=%s body=%s' % (getattr(exc, 'code', 'unknown'), body), LOG_ERROR)
    raise RuntimeError('OpenAI request failed (%s).' % (getattr(exc, 'code', 'unknown')))
  except URLError as exc:
    _log('openai request network error: %s' % (exc), LOG_ERROR)
    raise RuntimeError('OpenAI request failed (network error).')
  except Exception as exc:
    _log('openai request unexpected error: %s' % (exc), LOG_ERROR)
    raise RuntimeError('OpenAI request failed.')

  try:
    response_payload = json.loads(_as_text(raw_response))
  except Exception as exc:
    _log('openai response json parse failed: %s' % (exc), LOG_ERROR)
    raise RuntimeError('OpenAI returned an invalid JSON response.')
  choices = response_payload.get('choices') or []
  if not choices:
    raise RuntimeError('OpenAI returned no choices.')

  message = choices[0].get('message') or {}
  message_content = message.get('content')
  try:
    payload = _extract_json_payload(message_content)
  except Exception as exc:
    _log('openai response payload parse failed: %s content=%s' % (exc, _as_text(message_content)[:200]), LOG_ERROR)
    raise RuntimeError('OpenAI returned an invalid translation payload.')
  translations = payload.get('translations')
  if not isinstance(translations, list):
    raise RuntimeError('OpenAI response is missing translations.')

  normalized = []
  for item in translations:
    normalized.append(_as_text(item))

  if len(normalized) != len(lines):
    if len(normalized) == 0:
      raise RuntimeError('OpenAI returned 0 translations for %d lines.' % (len(lines)))
    _log(
      'openai translation count mismatch: got=%d expected=%d; applying safe fallback for missing/extra lines'
      % (len(normalized), len(lines)),
      LOG_WARNING
    )
    if len(normalized) > len(lines):
      normalized = normalized[:len(lines)]
    elif len(normalized) < len(lines):
      # Keep flow stable: if model drops items, reuse source text for missing rows.
      for index in range(len(normalized), len(lines)):
        normalized.append(_as_text(lines[index]))

  return normalized

def _copy_subtitle_to_temp(source_path):
  temp_source = os.path.join(__temp__, '%s.srt' % (str(uuid.uuid4())))
  if not xbmcvfs.copy(source_path, temp_source):
    raise RuntimeError(__language__(33043))
  return temp_source

def _detect_text_encoding(local_subtitle_path):
  try:
    with open(local_subtitle_path, 'rb') as subtitle_file:
      raw_data = subtitle_file.read()
    encoding = None
    if chardet is not None:
      detected = chardet.detect(raw_data)
      encoding = detected.get('encoding')
    elif from_bytes is not None:
      results = from_bytes(raw_data)
      best = results.best()
      if best is not None:
        encoding = best.encoding
    if encoding and encoding.lower() == 'gb2312':
      encoding = 'gbk'
    if encoding:
      return encoding
  except Exception as exc:
    _log('encoding detection failed: %s' % (exc), LOG_WARNING)
  return 'utf-8'

def _build_translated_subtitle_path(source_subtitle_path, target_language_code):
  source_directory = os.path.dirname(source_subtitle_path)
  source_filename = os.path.basename(source_subtitle_path)
  source_base = os.path.splitext(source_filename)[0]
  target_code = _canonicalize_language_code(target_language_code)
  if not target_code:
    target_code = target_language_code.lower()

  match = re.match(r'^(.*?)([._-])([a-z]{2,3}(?:-[a-z0-9]{2,8})?)$', source_base, re.IGNORECASE)
  if match:
    translated_base = '%s%s%s' % (match.group(1), match.group(2), target_code)
  else:
    translated_base = '%s-%s' % (source_base, target_code)

  if translated_base.lower() == source_base.lower():
    translated_base = '%s-translated-%s' % (source_base, target_code)

  return os.path.join(source_directory, '%s.srt' % (translated_base))

def _guess_language_code_from_path(path):
  filename = os.path.basename(path)
  base = os.path.splitext(filename)[0]
  suffix_match = LANGUAGE_SUFFIX_REGEX.search(base)
  if suffix_match:
    normalized = _canonicalize_language_code(suffix_match.group(1))
    if normalized:
      return normalized

  for token in reversed(LANGUAGE_TOKEN_REGEX.split(base.lower())):
    normalized = _canonicalize_language_code(token)
    if normalized:
      return normalized
  return 'auto'

def _list_srt_files(folder_path, include_generated=True):
  if not folder_path:
    return []

  try:
    file_names = xbmcvfs.listdir(folder_path)[1]
  except Exception:
    return []

  candidates = []
  for file_name in file_names:
    if not file_name.lower().endswith('.srt'):
      continue
    full_path = os.path.join(folder_path, file_name)
    if not include_generated and _is_generated_subtitle_name(full_path):
      continue
    candidates.append(full_path)

  candidates.sort(key=lambda item: os.path.basename(item).lower())
  return candidates

def _build_compact_display_name(filename, max_length=72, tail_length=28):
  name = _as_text(filename)
  if len(name) <= max_length:
    return name

  if tail_length < 10:
    tail_length = 10
  head_length = max_length - tail_length - 3
  if head_length < 10:
    head_length = 10
    tail_length = max_length - head_length - 3

  return '%s...%s' % (name[:head_length], name[-tail_length:])

def _detect_language_from_filename(path):
  filename = os.path.basename(path)
  base = os.path.splitext(filename)[0].lower()

  preferred_codes = [
    _parse_language_code('preferred_language_1'),
    _parse_language_code('preferred_language_2'),
  ]

  candidates = []

  suffix_match = LANGUAGE_SUFFIX_REGEX.search(base)
  if suffix_match:
    candidates.append(suffix_match.group(1))

  for token in reversed(LANGUAGE_TOKEN_REGEX.split(base)):
    if token:
      candidates.append(token)

  seen = {}
  for candidate in candidates:
    normalized = _canonicalize_language_code(candidate)
    if not normalized:
      continue
    if normalized in seen:
      continue
    seen[normalized] = True
    if normalized in preferred_codes:
      return normalized
    if normalized in KNOWN_SUBTITLE_LANGUAGE_CODES:
      return normalized
  return ''

def _detect_language_from_content(path):
  max_read = 12288
  raw = None
  file_handle = None
  try:
    file_handle = xbmcvfs.File(path)
    raw = file_handle.read(max_read)
  except Exception:
    raw = None
  finally:
    try:
      if file_handle:
        file_handle.close()
    except Exception:
      pass

  text = _as_text(raw).lower()
  if not text:
    return 'unk'

  script_scores = {
    'ru': 0,
    'ar': 0,
    'zh': 0,
    'ja': 0,
    'ko': 0,
  }
  for character in text:
    codepoint = ord(character)
    if 0x0400 <= codepoint <= 0x04FF:
      script_scores['ru'] += 1
    elif 0x0600 <= codepoint <= 0x06FF:
      script_scores['ar'] += 1
    elif 0x4E00 <= codepoint <= 0x9FFF:
      script_scores['zh'] += 1
    elif (0x3040 <= codepoint <= 0x30FF) or (0x31F0 <= codepoint <= 0x31FF):
      script_scores['ja'] += 1
    elif 0xAC00 <= codepoint <= 0xD7AF:
      script_scores['ko'] += 1

  best_script = max(script_scores, key=script_scores.get)
  if script_scores[best_script] >= 6:
    return best_script

  words = re.findall(r"[a-z']+", text)
  if len(words) == 0:
    return 'unk'

  indicators = {
    'en': set(['the', 'and', 'you', 'is', 'are', 'what', 'this', 'that', 'with']),
    'nl': set(['de', 'het', 'een', 'en', 'ik', 'je', 'niet', 'dat', 'van']),
    'fr': set(['le', 'la', 'les', 'et', 'je', 'pas', 'vous', 'est', 'une']),
    'es': set(['el', 'la', 'los', 'las', 'y', 'que', 'de', 'no', 'una']),
    'de': set(['der', 'die', 'das', 'und', 'ich', 'nicht', 'ist', 'ein', 'mit']),
    'it': set(['il', 'la', 'e', 'che', 'non', 'una', 'per', 'con', 'sono']),
    'pt': set(['o', 'a', 'os', 'as', 'e', 'que', 'de', 'não', 'uma']),
  }

  language_scores = {}
  for language_code, marker_words in indicators.items():
    score = 0
    for word in words:
      if word in marker_words:
        score += 1
    language_scores[language_code] = score

  best_language = max(language_scores, key=language_scores.get)
  if language_scores[best_language] >= 3:
    return best_language
  return 'unk'

def _build_subtitle_prepicker_entries(folder_path):
  entries = []
  for path in _list_srt_files(folder_path, include_generated=False):
    language_code = _detect_language_from_filename(path)
    source_rank = 1
    if not language_code:
      language_code = _detect_language_from_content(path)
      source_rank = 2
    if not language_code:
      language_code = 'unk'

    label = _subtitle_menu_label(path, compact=True)
    entries.append({
      'label': label,
      'path': path,
      'source_rank': source_rank,
      'unknown_rank': 1 if language_code == 'unk' else 0,
    })

  entries.sort(key=lambda item: (item['unknown_rank'], item['source_rank'], os.path.basename(item['path']).lower()))
  normalized = []
  for item in entries:
    normalized.append((item['label'], item['path']))
  return normalized

def _get_dualsubtitles_work_dir_for_path(path):
  base_dir = os.path.dirname(path)
  work_dir = os.path.join(base_dir, 'DualSubtitles')
  try:
    xbmcvfs.mkdirs(work_dir)
  except Exception:
    pass
  _set_writable_permissions_in_dir(work_dir)
  return work_dir

def _set_writable_permissions(path, is_directory=False):
  if not path:
    return
  try:
    mode = int('777', 8) if is_directory else int('666', 8)
    os.chmod(path, mode)
  except Exception:
    pass

def _set_writable_permissions_in_dir(directory_path):
  if not directory_path:
    return
  try:
    _set_writable_permissions(directory_path, is_directory=True)
    _, files = xbmcvfs.listdir(directory_path)
    for file_name in files:
      _set_writable_permissions(os.path.join(directory_path, file_name), is_directory=False)
  except Exception:
    pass

def _dualsubs_work_temp_path(target_path, extension):
  work_dir = _get_dualsubtitles_work_dir_for_path(target_path)
  extension = extension if extension.startswith('.') else ('.%s' % (extension))
  filename = 'smartsync-%s%s' % (str(uuid.uuid4()), extension)
  return os.path.join(work_dir, filename)

def _dualsubs_backup_path(target_path):
  target_name = os.path.basename(target_path)
  work_dir = _get_dualsubtitles_work_dir_for_path(target_path)
  return os.path.join(work_dir, '%s.bak' % (target_name))

def _replace_file_with_dualsubs_backup(source_path, target_path, backup_existing=True):
  had_existing = False
  backup_path = ''
  try:
    had_existing = xbmcvfs.exists(target_path)
  except Exception:
    had_existing = False

  if backup_existing and had_existing:
    backup_path = _dualsubs_backup_path(target_path)
    if xbmcvfs.exists(backup_path):
      xbmcvfs.delete(backup_path)
    if not xbmcvfs.copy(target_path, backup_path):
      raise RuntimeError('backup copy failed')
    _set_writable_permissions(backup_path, is_directory=False)

  if xbmcvfs.exists(target_path):
    xbmcvfs.delete(target_path)

  if not xbmcvfs.copy(source_path, target_path):
    if backup_path and not xbmcvfs.exists(target_path):
      try:
        xbmcvfs.copy(backup_path, target_path)
      except Exception:
        pass
    raise RuntimeError('target write failed')

  _set_writable_permissions(target_path, is_directory=False)
  return {
    'target_path': target_path,
    'backup_path': backup_path,
    'had_existing': had_existing,
  }

def _build_smartsync_saved_output_path(target_path):
  directory = os.path.dirname(target_path)
  base = os.path.splitext(os.path.basename(target_path))[0]
  if base.lower().endswith('.smartsync'):
    base = '%s-%s' % (base, str(uuid.uuid4())[:8])
  return os.path.join(directory, '%s.smartsync.srt' % (base))

def _move_file_to_dualsubtitles_folder(path):
  if not path:
    return False

  destination = os.path.join(_get_dualsubtitles_work_dir_for_path(path), os.path.basename(path))
  if path.lower() == destination.lower():
    return True

  if xbmcvfs.exists(destination):
    xbmcvfs.delete(destination)
  if not xbmcvfs.copy(path, destination):
    return False
  _set_writable_permissions(destination, is_directory=False)
  xbmcvfs.delete(path)
  return True

def _cleanup_generated_movie_sidecars(video_dir, video_basename):
  if not video_dir or not video_basename:
    return

  candidate_names = set([
    ('%s..srt' % (video_basename)).lower(),
    ('%s..ass' % (video_basename)).lower(),
  ])

  try:
    file_names = xbmcvfs.listdir(video_dir)[1]
  except Exception:
    return

  for file_name in file_names:
    if file_name.lower() not in candidate_names:
      continue
    source_path = os.path.join(video_dir, file_name)
    if _move_file_to_dualsubtitles_folder(source_path):
      _log('moved generated sidecar to DualSubtitles: %s' % (source_path), LOG_INFO)
    else:
      _log('failed moving generated sidecar to DualSubtitles: %s' % (source_path), LOG_WARNING)

def _derive_output_base_name_from_subtitle(path):
  if not path:
    return 'DualSubtitles'
  base = os.path.splitext(os.path.basename(path))[0]
  match = re.match(r'^(.*?)[._-]([a-z]{2})$', base, re.IGNORECASE)
  if match:
    base = match.group(1)
  if not base:
    return 'DualSubtitles'
  return base

def _build_merged_ass_output_path(primary_subtitle_path):
  base_name = _derive_output_base_name_from_subtitle(primary_subtitle_path)
  work_dir = _get_dualsubtitles_work_dir_for_path(primary_subtitle_path)
  return os.path.join(work_dir, '%s.dual.ass' % (base_name))

def _create_smart_sync_progress():
  progress = None
  try:
    progress = xbmcgui.DialogProgress()
    progress.create(__scriptname__, __language__(33134))
  except Exception:
    progress = None
  return progress

def _close_progress(progress):
  if progress is None:
    return
  try:
    progress.close()
  except Exception:
    pass

def _set_smart_sync_progress(progress, percent, message_id):
  _progress_update(progress, percent, __language__(message_id))

def _is_generated_subtitle_name(path):
  name = os.path.basename(path).lower()
  if name.endswith('.srt.bak'):
    return True
  if name.endswith('.ass.bak'):
    return True
  if '..srt' in name:
    return True
  if '..ass' in name:
    return True
  if '-translated-' in name:
    return True
  if '.translated.' in name:
    return True
  if 'smartsync-' in name:
    return True
  if '.smartsync.' in name:
    return True
  if name.endswith('.dual.srt'):
    return True
  return False

def _select_translation_source_subtitle(video_dir, fallback_dir=''):
  source_dir = video_dir
  candidates = _list_srt_files(source_dir, include_generated=False)
  if len(candidates) == 0 and fallback_dir and fallback_dir != video_dir:
    source_dir = fallback_dir
    candidates = _list_srt_files(source_dir, include_generated=False)

  if len(candidates) == 0:
    _notify(__language__(33077), NOTIFY_WARNING)
    _log('translation source selection failed: no .srt files in video/fallback dir', LOG_WARNING)
    return None

  labels = []
  for path in candidates:
    labels.append(_subtitle_menu_label(path))

  selected = __msg_box__.select(__language__(33078), labels)
  if selected is None or selected < 0:
    _log('translation source selection cancelled', LOG_INFO)
    return None

  source_subtitle = candidates[selected]
  _log('translation source selected: %s' % (source_subtitle), LOG_INFO)
  return source_subtitle

def _unique_paths(paths):
  unique = []
  seen = {}
  for path in paths:
    if not path:
      continue
    key = path.lower()
    if key in seen:
      continue
    seen[key] = True
    unique.append(path)
  return unique

def _safe_basename(path):
  try:
    return os.path.basename(path)
  except Exception:
    return path

def _subtitle_menu_label(path, compact=False):
  display_name = _safe_basename(path)
  if compact:
    display_name = _build_compact_display_name(display_name)

  language_code = _detect_language_from_filename(path)
  if not language_code:
    language_code = _detect_language_from_content(path)
  if not language_code:
    language_code = 'unk'

  return '[%s] %s' % (language_code.upper(), display_name)

def _load_subtitle_for_processing(subtitle_path):
  pysubs2 = _load_pysubs2()
  local_copy = _copy_subtitle_to_temp(subtitle_path)
  encoding = _detect_text_encoding(local_copy)

  try:
    subtitle_data = pysubs2.load(local_copy, encoding=encoding)
  except Exception:
    subtitle_data = pysubs2.load(local_copy)
  return subtitle_data, local_copy

def _save_subtitle_to_temp(subtitle_data):
  temp_output = os.path.join(__temp__, '%s.srt' % (str(uuid.uuid4())))
  subtitle_data.save(temp_output, encoding='utf-8', format_='srt')
  return temp_output

def _smart_sync_method_label(method_name):
  if method_name == 'ai_anchor':
    return __language__(33100)
  return __language__(33083)

def _collect_smart_sync_reference_candidates(excluded_paths, subtitle1, subtitle2, video_dir, start_dir):
  excluded = {}
  for path in excluded_paths or []:
    if path:
      excluded[path.lower()] = True

  selected_candidates = []
  if subtitle1 and subtitle1.lower() not in excluded:
    selected_candidates.append((__language__(33093) % (_subtitle_menu_label(subtitle1)), subtitle1))
  if subtitle2 and subtitle2.lower() not in excluded:
    selected_candidates.append((__language__(33093) % (_subtitle_menu_label(subtitle2)), subtitle2))

  folder_candidates = []
  for candidate_dir in _unique_paths([video_dir, start_dir]):
    for path in _list_srt_files(candidate_dir, include_generated=False):
      if path.lower() in excluded:
        continue
      folder_candidates.append((__language__(33094) % (_subtitle_menu_label(path)), path))

  merged = []
  for label, path in selected_candidates + folder_candidates:
    merged.append((label, path))

  deduped = []
  seen = {}
  for label, path in merged:
    key = path.lower()
    if key in seen:
      continue
    seen[key] = True
    deduped.append((label, path))
  return deduped

def _select_smart_sync_reference(subtitle1, subtitle2, video_dir, start_dir):
  candidates = _collect_smart_sync_reference_candidates([], subtitle1, subtitle2, video_dir, start_dir)
  if len(candidates) == 0:
    _notify(__language__(33095), NOTIFY_WARNING)
    _log('smart sync reference selection failed: no candidates', LOG_WARNING)
    return None

  labels = []
  for label, _ in candidates:
    labels.append(label)
  selected = __msg_box__.select(__language__(33096), labels)
  if selected is None or selected < 0:
    _log('smart sync reference selection cancelled', LOG_INFO)
    return None

  return candidates[selected][1]

def _select_smart_sync_target_for_dual(reference_path, subtitle1, subtitle2):
  candidates = []
  if subtitle1 and subtitle1.lower() != reference_path.lower():
    candidates.append(('subtitle1', subtitle1))
  if subtitle2 and subtitle2.lower() != reference_path.lower():
    candidates.append(('subtitle2', subtitle2))

  if len(candidates) == 0:
    _log('smart sync target selection failed: no target candidates after reference selection', LOG_WARNING)
    return None

  if len(candidates) == 1:
    return candidates[0][1]

  option_labels = []
  for slot, path in candidates:
    if slot == 'subtitle1':
      option_labels.append(__language__(33091) % (_subtitle_menu_label(path)))
    else:
      option_labels.append(__language__(33092) % (_subtitle_menu_label(path)))

  selected = __msg_box__.select(__language__(33090), option_labels)
  if selected is None or selected < 0:
    _log('smart sync target selection cancelled', LOG_INFO)
    return None
  return candidates[selected][1]

def _collect_dual_sync_target_paths(reference_path, subtitle1, subtitle2):
  targets = []
  if subtitle1 and subtitle1.lower() != reference_path.lower():
    targets.append(subtitle1)
  if subtitle2 and subtitle2.lower() != reference_path.lower():
    targets.append(subtitle2)
  return targets

def _openai_find_smart_sync_anchors(reference_samples, target_samples, api_key, model, timeout_seconds):
  user_prompt = (
    'Match subtitle cues that represent the same spoken line.\n'
    'Return JSON only using this exact format:\n'
    '{"pairs":[{"target_id":12,"reference_id":33}]}\n'
    'Rules:\n'
    '- Use only ids from the provided lists.\n'
    '- Return 6 to 24 high-confidence pairs.\n'
    '- Keep pairs ordered by target timeline.\n'
    '- Do not include explanations.\n\n'
    'Reference cues JSON:\n%s\n\n'
    'Target cues JSON:\n%s'
  ) % (
    json.dumps(reference_samples, ensure_ascii=False),
    json.dumps(target_samples, ensure_ascii=False)
  )

  payload = {
    'model': model,
    'temperature': 0,
    'messages': [
      {
        'role': 'system',
        'content': 'You are an expert subtitle aligner. Return only valid JSON.'
      },
      {
        'role': 'user',
        'content': user_prompt
      }
    ]
  }

  request_data = _to_utf8_bytes(json.dumps(payload, ensure_ascii=False))
  request = Request(OPENAI_CHAT_ENDPOINT, data=request_data)
  request.add_header('Content-Type', 'application/json')
  request.add_header('Authorization', 'Bearer %s' % (api_key))

  try:
    response = urlopen(request, timeout=timeout_seconds)
    raw_response = response.read()
  except HTTPError as exc:
    body = ''
    try:
      body = _as_text(exc.read())
    except Exception:
      pass
    _log('smart sync ai request failed: code=%s body=%s' % (getattr(exc, 'code', 'unknown'), body), LOG_ERROR)
    raise RuntimeError('OpenAI request failed (%s).' % (getattr(exc, 'code', 'unknown')))
  except URLError as exc:
    _log('smart sync ai network error: %s' % (exc), LOG_ERROR)
    raise RuntimeError('OpenAI request failed (network error).')
  except Exception as exc:
    _log('smart sync ai request unexpected error: %s' % (exc), LOG_ERROR)
    raise RuntimeError('OpenAI request failed.')

  try:
    response_payload = json.loads(_as_text(raw_response))
  except Exception as exc:
    _log('smart sync ai response parse failed: %s' % (exc), LOG_ERROR)
    raise RuntimeError('OpenAI returned invalid JSON.')

  choices = response_payload.get('choices') or []
  if len(choices) == 0:
    raise RuntimeError('OpenAI returned no choices.')

  message = choices[0].get('message') or {}
  message_content = message.get('content')
  try:
    parsed = _extract_json_payload(message_content)
  except Exception as exc:
    _log('smart sync ai payload parse failed: %s content=%s' % (exc, _as_text(message_content)[:200]), LOG_ERROR)
    raise RuntimeError('OpenAI returned an invalid anchor payload.')

  pairs = parsed.get('pairs')
  if not isinstance(pairs, list):
    raise RuntimeError('OpenAI response is missing pairs.')

  normalized_pairs = []
  for pair in pairs:
    if not isinstance(pair, dict):
      continue
    try:
      normalized_pairs.append({
        'target_id': int(pair.get('target_id')),
        'reference_id': int(pair.get('reference_id')),
      })
    except Exception:
      continue

  if len(normalized_pairs) == 0:
    raise RuntimeError(__language__(33106))
  return normalized_pairs

def _run_smart_sync_local(reference_path, target_path):
  reference_subs = None
  target_subs = None
  reference_local = ''
  target_local = ''
  try:
    reference_subs, reference_local = _load_subtitle_for_processing(reference_path)
    target_subs, target_local = _load_subtitle_for_processing(target_path)
    return smartsync.sync_local(reference_subs, target_subs)
  finally:
    if reference_local:
      xbmcvfs.delete(reference_local)
    if target_local:
      xbmcvfs.delete(target_local)

def _run_smart_sync_ai(reference_path, target_path):
  api_key = _get_openai_api_key()
  if not api_key:
    _notify(__language__(33104), NOTIFY_WARNING)
    return None

  consent_message = __language__(33101)
  if not __msg_box__.yesno(__scriptname__, consent_message):
    _log('smart sync ai fallback cancelled by user', LOG_INFO)
    return None

  reference_subs = None
  target_subs = None
  reference_local = ''
  target_local = ''
  try:
    reference_subs, reference_local = _load_subtitle_for_processing(reference_path)
    target_subs, target_local = _load_subtitle_for_processing(target_path)

    reference_samples = smartsync.build_ai_samples(reference_subs, max_items=70)
    target_samples = smartsync.build_ai_samples(target_subs, max_items=70)
    if len(reference_samples) == 0 or len(target_samples) == 0:
      raise RuntimeError(__language__(33103))

    anchors = _openai_find_smart_sync_anchors(
      reference_samples,
      target_samples,
      api_key,
      _get_openai_model(),
      _get_translation_timeout_seconds()
    )
    ai_result = smartsync.sync_from_anchor_pairs(reference_subs, target_subs, anchors)
    _log('smart sync ai fallback succeeded: anchors=%d confidence=%.3f' % (len(anchors), ai_result.get('confidence', 0.0)), LOG_INFO)
    return ai_result
  finally:
    if reference_local:
      xbmcvfs.delete(reference_local)
    if target_local:
      xbmcvfs.delete(target_local)

def _select_smart_sync_apply_mode():
  options = [
    __language__(33152),
    __language__(33155),
    __language__(33159),
    __language__(33112),
  ]
  selected = __msg_box__.select(__language__(33151), options)
  if selected == 0:
    return 'replace'
  if selected == 1:
    return 'save_as_new'
  if selected == 2:
    return 'playback_only'
  return 'skip'

def _run_smart_sync_pipeline(reference_path, target_path, allow_ai_fallback=True):
  result = {
    'applied': False,
    'play_path': target_path,
    'temp_paths': [],
  }
  progress = _create_smart_sync_progress()

  try:
    _set_smart_sync_progress(progress, 8, 33135)
    local_result = _run_smart_sync_local(reference_path, target_path)
    _set_smart_sync_progress(progress, 45, 33136)
  except Exception as exc:
    _close_progress(progress)
    _log('smart sync local stage failed: %s' % (exc), LOG_WARNING)
    _notify(__language__(33109), NOTIFY_WARNING)
    return result

  _notify(__language__(33107) % (_smart_sync_confidence_percent(local_result), local_result.get('median_error_ms', 0)), NOTIFY_INFO)

  chosen_result = local_result
  if local_result.get('low_confidence'):
    low_conf_title = __language__(33099) % (_smart_sync_confidence_percent(local_result), local_result.get('median_error_ms', 0))
    if allow_ai_fallback:
      low_conf_choice = __msg_box__.select(low_conf_title, [__language__(33110), __language__(33111), __language__(33112)])
      if low_conf_choice == 2 or low_conf_choice < 0:
        _close_progress(progress)
        _log('smart sync skipped due low confidence user choice', LOG_INFO)
        return result

      if low_conf_choice == 1:
        ai_result = None
        try:
          _set_smart_sync_progress(progress, 62, 33137)
          ai_result = _run_smart_sync_ai(reference_path, target_path)
          _set_smart_sync_progress(progress, 78, 33138)
        except Exception as exc:
          _log('smart sync ai stage failed: %s' % (exc), LOG_WARNING)
          ai_result = None

        if ai_result is not None:
          chosen_result = ai_result
          _notify(__language__(33102), NOTIFY_INFO)
        else:
          fallback_choice = __msg_box__.select(__language__(33105), [__language__(33110), __language__(33112)])
          if fallback_choice != 0:
            _close_progress(progress)
            return result
    else:
      low_conf_choice = __msg_box__.select(low_conf_title, [__language__(33110), __language__(33112)])
      if low_conf_choice != 0:
        _close_progress(progress)
        _log('smart sync skipped due low confidence user choice (local-only mode)', LOG_INFO)
        return result

  apply_mode = _select_smart_sync_apply_mode()
  if apply_mode == 'skip':
    _close_progress(progress)
    _log('smart sync skipped at apply mode selection', LOG_INFO)
    return result

  _set_smart_sync_progress(progress, 88, 33139)
  if apply_mode == 'replace':
    sync_apply = _apply_synced_subtitle_to_target(target_path, chosen_result['synced_subs'])
  elif apply_mode == 'save_as_new':
    sync_apply = _save_synced_subtitle_as_new_file(target_path, chosen_result['synced_subs'])
  else:
    sync_apply = _prepare_synced_subtitle_playback_only(target_path, chosen_result['synced_subs'])
  _set_smart_sync_progress(progress, 100, 33140)
  _close_progress(progress)
  method_label = _smart_sync_method_label(chosen_result.get('method', 'local'))
  if apply_mode == 'playback_only':
    _notify(__language__(33161), NOTIFY_INFO)
  elif apply_mode == 'save_as_new' and sync_apply['persisted']:
    _notify(__language__(33160) % (os.path.basename(sync_apply.get('play_path', ''))), NOTIFY_INFO)
  elif sync_apply['persisted']:
    _notify(__language__(33108) % (method_label), NOTIFY_INFO)
  else:
    _notify(__language__(33113), NOTIFY_WARNING)

  result['applied'] = True
  result['play_path'] = sync_apply['play_path']
  if sync_apply.get('temp_path'):
    result['temp_paths'].append(sync_apply['temp_path'])
  return result

def _apply_synced_subtitle_to_target(target_path, synced_subs):
  local_synced_temp = _save_subtitle_to_temp(synced_subs)
  synced_temp = local_synced_temp
  work_synced_temp = _dualsubs_work_temp_path(target_path, '.srt')
  if xbmcvfs.copy(local_synced_temp, work_synced_temp):
    synced_temp = work_synced_temp
    _set_writable_permissions(work_synced_temp, is_directory=False)
    xbmcvfs.delete(local_synced_temp)
  try:
    write_result = _replace_file_with_dualsubs_backup(synced_temp, target_path, backup_existing=True)
    xbmcvfs.delete(synced_temp)
    return {
      'play_path': target_path,
      'persisted': True,
      'temp_path': '',
      'backup_path': write_result.get('backup_path', ''),
    }
  except Exception as exc:
    _log('smart sync persist failed for %s (%s)' % (target_path, exc), LOG_WARNING)
    return {
      'play_path': synced_temp,
      'persisted': False,
      'temp_path': synced_temp,
      'backup_path': _dualsubs_backup_path(target_path),
    }

def _save_synced_subtitle_as_new_file(target_path, synced_subs):
  output_path = _build_smartsync_saved_output_path(target_path)
  local_synced_temp = _save_subtitle_to_temp(synced_subs)
  try:
    write_result = _replace_file_with_dualsubs_backup(local_synced_temp, output_path, backup_existing=True)
    xbmcvfs.delete(local_synced_temp)
    return {
      'play_path': output_path,
      'persisted': True,
      'temp_path': '',
      'backup_path': write_result.get('backup_path', ''),
    }
  except Exception as exc:
    _log('smart sync save-as-new failed for %s (%s)' % (output_path, exc), LOG_WARNING)
    return {
      'play_path': local_synced_temp,
      'persisted': False,
      'temp_path': local_synced_temp,
      'backup_path': '',
    }

def _prepare_synced_subtitle_playback_only(target_path, synced_subs):
  local_synced_temp = _save_subtitle_to_temp(synced_subs)
  playback_temp = _dualsubs_work_temp_path(target_path, '.srt')
  if xbmcvfs.copy(local_synced_temp, playback_temp):
    _set_writable_permissions(playback_temp, is_directory=False)
    xbmcvfs.delete(local_synced_temp)
    return {
      'play_path': playback_temp,
      'persisted': False,
      'temp_path': playback_temp,
      'backup_path': '',
    }
  return {
    'play_path': local_synced_temp,
    'persisted': False,
    'temp_path': local_synced_temp,
    'backup_path': '',
  }

def _smart_sync_confidence_percent(sync_result):
  confidence = sync_result.get('confidence', 0.0)
  if confidence < 0:
    confidence = 0
  if confidence > 1:
    confidence = 1
  return int(round(confidence * 100.0))

def _maybe_run_smart_sync(subtitle1, subtitle2, video_dir, start_dir):
  if not _is_smart_sync_enabled():
    _log('smart sync disabled in settings', LOG_DEBUG)
    return subtitle1, subtitle2, []

  if _get_smart_sync_mode() != 'auto_prompt':
    _log('smart sync auto mode disabled (manual only)', LOG_DEBUG)
    return subtitle1, subtitle2, []

  if subtitle1 is None or subtitle2 is None:
    return subtitle1, subtitle2, []

  first_subs = None
  second_subs = None
  first_local = ''
  second_local = ''
  try:
    first_subs, first_local = _load_subtitle_for_processing(subtitle1)
    second_subs, second_local = _load_subtitle_for_processing(subtitle2)
    mismatch = smartsync.assess_pair(first_subs, second_subs)
  except Exception as exc:
    _log('smart sync mismatch detection failed: %s' % (exc), LOG_WARNING)
    return subtitle1, subtitle2, []
  finally:
    if first_local:
      xbmcvfs.delete(first_local)
    if second_local:
      xbmcvfs.delete(second_local)

  if not mismatch.get('likely_mismatch'):
    _log(
      'smart sync mismatch not detected: median=%s offset=%s overlap_improvement=%s'
      % (mismatch.get('raw_median_error_ms'), mismatch.get('estimated_global_offset_ms'), mismatch.get('overlap_improvement')),
      LOG_DEBUG
    )
    return subtitle1, subtitle2, []

  start_message = __language__(33098) % (mismatch.get('raw_median_error_ms', 0), mismatch.get('estimated_global_offset_ms', 0))
  selected_action = __msg_box__.select(start_message, [__language__(33084), __language__(33085)])
  if selected_action != 1:
    _log('smart sync skipped by user after mismatch prompt', LOG_INFO)
    return subtitle1, subtitle2, []

  reference_path = _select_smart_sync_reference(subtitle1, subtitle2, video_dir, start_dir)
  if reference_path is None:
    return subtitle1, subtitle2, []
  available_targets = _collect_dual_sync_target_paths(reference_path, subtitle1, subtitle2)
  if len(available_targets) == 0:
    return subtitle1, subtitle2, []

  target_path = _select_smart_sync_target_for_dual(reference_path, subtitle1, subtitle2)
  if target_path is None:
    return subtitle1, subtitle2, []

  target_paths = [target_path]
  if len(available_targets) > 1:
    also_sync_other = __msg_box__.yesno(__scriptname__, __language__(33141))
    if also_sync_other:
      for other_path in available_targets:
        if other_path.lower() != target_path.lower():
          target_paths.append(other_path)

  updated_subtitle1 = subtitle1
  updated_subtitle2 = subtitle2
  all_temp_paths = []
  applied_count = 0

  for path_to_sync in target_paths:
    sync_apply = _run_smart_sync_pipeline(reference_path, path_to_sync, allow_ai_fallback=False)
    if not sync_apply.get('applied'):
      continue

    applied_count += 1
    if path_to_sync.lower() == subtitle1.lower():
      updated_subtitle1 = sync_apply.get('play_path')
    elif path_to_sync.lower() == subtitle2.lower():
      updated_subtitle2 = sync_apply.get('play_path')

    for temp_path in sync_apply.get('temp_paths', []):
      all_temp_paths.append(temp_path)

  if applied_count == 0:
    return subtitle1, subtitle2, []

  if applied_count > 1:
    _notify(__language__(33142), NOTIFY_INFO)

  return updated_subtitle1, updated_subtitle2, all_temp_paths

def _run_manual_smart_sync_action():
  if not _is_smart_sync_enabled():
    _notify(__language__(33131), NOTIFY_WARNING)
    return

  video_dir, video_basename = _current_video_context()
  _cleanup_generated_movie_sidecars(video_dir, video_basename)
  start_dir = _resolve_start_dir(video_dir)
  base_dir = video_dir or start_dir

  reference_path, reference_dir = _browse_for_subtitle(__language__(33124), base_dir)
  if reference_path is None:
    return
  if not reference_path.lower().endswith('.srt') or reference_path.startswith(__temp__):
    _notify(__language__(33123), NOTIFY_WARNING)
    return

  target_path, _ = _browse_for_subtitle(__language__(33122), reference_dir)
  if target_path is None:
    return
  if not target_path.lower().endswith('.srt') or target_path.startswith(__temp__):
    _notify(__language__(33123), NOTIFY_WARNING)
    return
  if reference_path.lower() == target_path.lower():
    _notify(__language__(33097), NOTIFY_WARNING)
    return

  sync_apply = _run_smart_sync_pipeline(reference_path, target_path)
  if not sync_apply.get('applied'):
    return

  if not __msg_box__.yesno(__scriptname__, __language__(33143)):
    return

  second_target_path, _ = _browse_for_subtitle(__language__(33144), reference_dir)
  if second_target_path is None:
    return
  if not second_target_path.lower().endswith('.srt') or second_target_path.startswith(__temp__):
    _notify(__language__(33123), NOTIFY_WARNING)
    return
  if second_target_path.lower() == reference_path.lower() or second_target_path.lower() == target_path.lower():
    _notify(__language__(33097), NOTIFY_WARNING)
    return

  second_sync_apply = _run_smart_sync_pipeline(reference_path, second_target_path)
  if not second_sync_apply.get('applied'):
    return

  _notify(__language__(33142), NOTIFY_INFO)

def _load_pysubs2():
  try:
    import pysubs2
  except Exception:
    from resources.lib import pysubs2
  return pysubs2

def _translate_subtitle_file(source_subtitle_path, source_language_code, target_language_code):
  api_key = _get_openai_api_key()
  if not api_key:
    raise RuntimeError(__language__(33067))

  model = _get_openai_model()
  batch_size = _get_translation_batch_size()
  timeout_seconds = _get_translation_timeout_seconds()

  temp_source = ''
  temp_output = ''
  progress = None
  try:
    pysubs2 = _load_pysubs2()
    temp_source = _copy_subtitle_to_temp(source_subtitle_path)
    encoding = _detect_text_encoding(temp_source)

    try:
      subtitle_data = pysubs2.load(temp_source, encoding=encoding)
    except Exception:
      subtitle_data = pysubs2.load(temp_source)

    subtitle_lines = []
    for line in subtitle_data:
      if _as_text(line.text).strip():
        subtitle_lines.append(line)

    if len(subtitle_lines) == 0:
      raise RuntimeError('No subtitle lines available for translation.')

    progress = xbmcgui.DialogProgress()
    progress.create(__scriptname__, __language__(33064))

    translated_count = 0
    total_lines = len(subtitle_lines)
    index = 0
    while index < total_lines:
      try:
        if progress.iscanceled():
          raise RuntimeError(__language__(33072))
      except RuntimeError:
        raise
      except Exception:
        pass

      chunk_lines = subtitle_lines[index:index + batch_size]
      request_lines = []
      for item in chunk_lines:
        request_lines.append(_as_text(item.text))

      translated_lines = _openai_translate_lines(
        request_lines,
        source_language_code,
        target_language_code,
        api_key,
        model,
        timeout_seconds
      )

      for item_index in range(len(chunk_lines)):
        chunk_lines[item_index].text = translated_lines[item_index]

      translated_count += len(chunk_lines)
      index += batch_size
      _progress_update(progress, int((100.0 * translated_count) / total_lines), __language__(33064), '%d/%d' % (translated_count, total_lines))

    temp_output = os.path.join(__temp__, '%s.srt' % (str(uuid.uuid4())))
    subtitle_data.save(temp_output, encoding='utf-8', format_='srt')

    translated_path = _build_translated_subtitle_path(source_subtitle_path, target_language_code)
    try:
      _replace_file_with_dualsubs_backup(temp_output, translated_path, backup_existing=True)
    except Exception as write_exc:
      _log('ai translation write failed for %s (%s)' % (translated_path, write_exc), LOG_WARNING)
      raise RuntimeError(__language__(33071))

    _log('ai translation wrote subtitle=%s model=%s' % (translated_path, model), LOG_INFO)
    return translated_path
  finally:
    if progress is not None:
      try:
        progress.close()
      except Exception:
        pass
    if temp_source:
      xbmcvfs.delete(temp_source)
    if temp_output:
      xbmcvfs.delete(temp_output)

def _build_translation_targets_for_automatch(automatch):
  targets = []
  language1 = _parse_language_code('preferred_language_1')
  language2 = _parse_language_code('preferred_language_2')
  if not language1 or not language2 or language1 == language2:
    return targets

  if automatch['mode'] == 'partial':
    if automatch['missing'] == 'subtitle2':
      targets.append({
        'slot': 'subtitle2',
        'code': language2,
        'label': _language_label('preferred_language_2')
      })
    elif automatch['missing'] == 'subtitle1':
      targets.append({
        'slot': 'subtitle1',
        'code': language1,
        'label': _language_label('preferred_language_1')
      })
  elif automatch['mode'] == 'none':
    targets.append({
      'slot': 'subtitle1',
      'code': language1,
      'label': _language_label('preferred_language_1')
    })
    targets.append({
      'slot': 'subtitle2',
      'code': language2,
      'label': _language_label('preferred_language_2')
    })

  return targets

def _prompt_ai_translation_plan(automatch, video_dir, start_dir):
  result = {
    'status': 'skip',
    'source': None,
    'targets': [],
  }

  if not _is_ai_translation_enabled():
    return result

  if automatch['mode'] not in ['partial', 'none']:
    return result

  targets = _build_translation_targets_for_automatch(automatch)
  if len(targets) == 0:
    return result

  if not _get_openai_api_key():
    _notify(__language__(33067), NOTIFY_WARNING)
    _log('ai translation prompt skipped: openai_api_key is empty', LOG_WARNING)
    return result

  if len(targets) == 1:
    translate_option = __language__(33075) % (targets[0]['label'])
  else:
    translate_option = __language__(33076) % (targets[0]['label'], targets[1]['label'])

  options = [
    __language__(33074),
    translate_option
  ]
  selected = __msg_box__.select(__language__(33079), options)
  if selected != 1:
    _log('ai translation skipped by user selection', LOG_INFO)
    return result

  source_dir = video_dir
  if not _is_usable_browse_dir(source_dir):
    source_dir = start_dir
  source_subtitle = _select_translation_source_subtitle(source_dir, start_dir)
  if source_subtitle is None:
    return result

  result['status'] = 'translate'
  result['source'] = source_subtitle
  result['targets'] = targets
  return result

def _run_ai_translation_plan(plan, automatch):
  result = {
    'status': 'skip',
    'subtitle1': automatch.get('subtitle1'),
    'subtitle2': automatch.get('subtitle2'),
  }

  if plan.get('status') != 'translate':
    return result

  source_subtitle = plan.get('source')
  targets = plan.get('targets') or []
  if not source_subtitle or len(targets) == 0:
    return result

  source_language_code = _guess_language_code_from_path(source_subtitle)
  try:
    for target in targets:
      translated_path = _translate_subtitle_file(source_subtitle, source_language_code, target['code'])
      if target['slot'] == 'subtitle1':
        result['subtitle1'] = translated_path
      else:
        result['subtitle2'] = translated_path
      _notify(__language__(33065) % (target['label'], os.path.basename(translated_path)), NOTIFY_INFO)
      _log('ai translation target complete: slot=%s path=%s' % (target['slot'], translated_path), LOG_INFO)

    result['status'] = 'success'
    if len(targets) > 1:
      _notify(__language__(33080) % (targets[0]['label'], targets[1]['label']), NOTIFY_INFO)
    return result
  except Exception as exc:
    result['status'] = 'failed'
    result['subtitle1'] = automatch.get('subtitle1')
    result['subtitle2'] = automatch.get('subtitle2')
    _notify(__language__(33066), NOTIFY_WARNING)
    _log('ai translation plan failed: %s' % (exc), LOG_ERROR)
    return result

def _preferred_translation_targets():
  targets = []
  language1 = _parse_language_code('preferred_language_1')
  language2 = _parse_language_code('preferred_language_2')

  if language1:
    targets.append({
      'code': language1,
      'label': _language_label('preferred_language_1')
    })
  if language2 and language2 != language1:
    targets.append({
      'code': language2,
      'label': _language_label('preferred_language_2')
    })
  return targets

def _run_manual_translation_action():
  if not _is_ai_translation_enabled():
    _notify(__language__(33130), NOTIFY_WARNING)
    return

  if not _get_openai_api_key():
    _notify(__language__(33067), NOTIFY_WARNING)
    return

  targets = _preferred_translation_targets()
  if len(targets) == 0:
    _notify(__language__(33125), NOTIFY_WARNING)
    return

  video_dir, _ = _current_video_context()
  start_dir = _resolve_start_dir(video_dir)
  source_subtitle = _select_translation_source_subtitle(video_dir, start_dir)
  if source_subtitle is None:
    return

  options = []
  if len(targets) == 1:
    options.append(__language__(33127) % (targets[0]['label']))
  else:
    options.append(__language__(33127) % (targets[0]['label']))
    options.append(__language__(33127) % (targets[1]['label']))
    options.append(__language__(33128) % (targets[0]['label'], targets[1]['label']))

  selected = __msg_box__.select(__language__(33126), options)
  if selected is None or selected < 0:
    _log('manual translation target selection cancelled', LOG_INFO)
    return

  selected_targets = []
  if len(targets) == 1:
    selected_targets = [targets[0]]
  else:
    if selected == 0:
      selected_targets = [targets[0]]
    elif selected == 1:
      selected_targets = [targets[1]]
    else:
      selected_targets = [targets[0], targets[1]]

  source_language_code = _guess_language_code_from_path(source_subtitle)
  created = []
  for target in selected_targets:
    try:
      translated_path = _translate_subtitle_file(source_subtitle, source_language_code, target['code'])
      created.append((target, translated_path))
      _notify(__language__(33065) % (target['label'], os.path.basename(translated_path)), NOTIFY_INFO)
      _log('manual translation created: target=%s path=%s' % (target['code'], translated_path), LOG_INFO)
    except Exception as exc:
      _notify(__language__(33066), NOTIFY_WARNING)
      _log('manual translation failed for %s: %s' % (target['code'], exc), LOG_WARNING)

  if len(created) == 0:
    return

  if len(created) > 1:
    _notify(__language__(33080) % (created[0][0]['label'], created[1][0]['label']), NOTIFY_INFO)

  for _, translated_path in created:
    Download(translated_path)

def _notify_manual_translation_hint():
  if not _is_ai_translation_enabled():
    return
  if not _get_openai_api_key():
    return
  _notify(__language__(33153), NOTIFY_INFO, timeout=5000)

def _run_restore_backup_action():
  video_dir, _ = _current_video_context()
  start_dir = _resolve_start_dir(video_dir)
  base_dir = video_dir or start_dir

  target_path, _ = _browse_for_subtitle(__language__(33154), base_dir)
  if target_path is None:
    return
  if not target_path.lower().endswith('.srt') or target_path.startswith(__temp__):
    _notify(__language__(33123), NOTIFY_WARNING)
    return

  backup_path = _dualsubs_backup_path(target_path)
  if not xbmcvfs.exists(backup_path):
    _notify(__language__(33156), NOTIFY_WARNING)
    _log('restore backup failed: no backup found for %s' % (target_path), LOG_WARNING)
    return

  try:
    if xbmcvfs.exists(target_path):
      xbmcvfs.delete(target_path)
    if not xbmcvfs.copy(backup_path, target_path):
      raise RuntimeError('restore copy failed')
    _set_writable_permissions(target_path, is_directory=False)
    _notify(__language__(33157) % (os.path.basename(target_path)), NOTIFY_INFO)
    _log('restored backup: target=%s backup=%s' % (target_path, backup_path), LOG_INFO)
  except Exception as exc:
    _notify(__language__(33158), NOTIFY_WARNING)
    _log('restore backup failed for %s (%s)' % (target_path, exc), LOG_WARNING)

def _build_download_query(video_basename):
  base = _as_text(video_basename).strip()
  if not base:
    return ''

  tokens = re.findall(r'[a-z0-9]+', base.lower())
  if len(tokens) == 0:
    return base

  ignore_tokens = set([
    '1080p', '720p', '2160p', '480p', 'x264', 'x265', 'h264', 'h265', 'hevc', 'bluray', 'brrip',
    'webdl', 'webrip', 'web', 'hdr', 'dv', 'aac', 'dts', 'ddp5', 'atmos', 'proper', 'repack', 'yts',
    'yify', 'rarbg', 'am'
  ])

  filtered = []
  for token in tokens:
    if token in ignore_tokens:
      continue
    if re.match(r'^\d{3,4}p$', token):
      continue
    if len(token) <= 2 and not re.match(r'^\d{4}$', token):
      continue
    filtered.append(token)

  if len(filtered) == 0:
    filtered = tokens
  return ' '.join(filtered[:8])

def _build_download_context(video_dir, video_basename):
  query = _build_download_query(video_basename)
  season, episode = _extract_season_episode(video_basename)
  metadata = _current_video_metadata()
  video_path = _current_video_file_path()
  file_hash, file_size = _compute_file_hash_and_size(video_path)
  return {
    'video_dir': video_dir,
    'video_basename': video_basename,
    'video_path': video_path,
    'query': query,
    'year': _extract_release_year(video_basename),
    'season': season,
    'episode': episode,
    'is_tvshow': bool(season and episode),
    'imdb_id': metadata.get('imdb_id', ''),
    'title': metadata.get('title', ''),
    'tvshow_title': metadata.get('tvshow_title', ''),
    'file_hash': file_hash,
    'file_size': file_size,
  }

def _tokenize_release(text):
  tokens = re.findall(r'[a-z0-9]+', _as_text(text).lower())
  filtered = []
  for token in tokens:
    if len(token) <= 1:
      continue
    if token in RELEASE_NOISE_TOKENS:
      continue
    filtered.append(token)
  return filtered

def _release_similarity_score(video_basename, release_name):
  video_tokens = set(_tokenize_release(video_basename))
  release_tokens = set(_tokenize_release(release_name))
  if len(video_tokens) == 0 or len(release_tokens) == 0:
    return 0
  overlap = len(video_tokens.intersection(release_tokens))
  return int(round((100.0 * overlap) / float(len(video_tokens))))

def _unknown_match_likelihood_score(video_basename, release_name, similarity_score=0):
  video_signature = _build_release_signature(video_basename)
  release_signature = _build_release_signature(release_name)

  video_title_tokens = set(video_signature.get('title_tokens', []))
  release_title_tokens = set(release_signature.get('title_tokens', []))
  overlap_count = len(video_title_tokens.intersection(release_title_tokens))
  if len(video_title_tokens) == 0:
    overlap_ratio = 0.0
  else:
    overlap_ratio = float(overlap_count) / float(len(video_title_tokens))

  title_ratio = 0.0
  if len(video_title_tokens) > 0 and len(release_title_tokens) > 0:
    title_ratio = difflib.SequenceMatcher(
      None,
      ' '.join(sorted(video_title_tokens)),
      ' '.join(sorted(release_title_tokens))
    ).ratio()

  score = int(round((55.0 * overlap_ratio) + (20.0 * title_ratio) + (0.20 * float(similarity_score or 0))))

  video_year = _as_text(video_signature.get('year', '')).strip()
  release_year = _as_text(release_signature.get('year', '')).strip()
  if video_year and release_year:
    if video_year == release_year:
      score += 10
    else:
      score -= 12

  video_source = _as_text(video_signature.get('source', '')).strip()
  release_source = _as_text(release_signature.get('source', '')).strip()
  if video_source and release_source:
    if video_source == release_source:
      score += 6
    else:
      score -= 4

  video_resolution = _as_text(video_signature.get('resolution', '')).strip()
  release_resolution = _as_text(release_signature.get('resolution', '')).strip()
  if video_resolution and release_resolution:
    if video_resolution == release_resolution:
      score += 5
    else:
      score -= 2

  video_codec = _as_text(video_signature.get('codec', '')).strip()
  release_codec = _as_text(release_signature.get('codec', '')).strip()
  if video_codec and release_codec and video_codec == release_codec:
    score += 3

  if len(video_title_tokens) >= 3 and overlap_count < 2:
    score -= 22
  elif len(video_title_tokens) >= 2 and overlap_count < 1:
    score -= 18
  elif overlap_count == 0:
    score -= 12

  if score < 0:
    score = 0
  if score > 100:
    score = 100

  return {
    'score': score,
    'title_overlap': overlap_count,
    'title_overlap_ratio': overlap_ratio,
  }

def _extract_season_episode(text):
  raw = _as_text(text)
  if not raw:
    return '', ''

  match = re.search(r'[sS](\d{1,3})[.\-_\s]?[eE](\d{1,3})', raw)
  if match:
    return match.group(1).zfill(2), match.group(2).zfill(2)

  match = re.search(r'\b(\d{1,2})[xX](\d{1,3})\b', raw)
  if match:
    return match.group(1).zfill(2), match.group(2).zfill(2)

  return '', ''

def _extract_release_year(text):
  tokens = re.findall(r'\b(19\d{2}|20\d{2})\b', _as_text(text))
  if len(tokens) == 0:
    return ''
  for token in tokens:
    if token not in ['1080', '2160', '720', '480']:
      return token
  return tokens[0]

def _normalize_release_token(token):
  value = _as_text(token).lower().strip()
  if not value:
    return ''
  if value in ['blu', 'ray', 'blu-ray']:
    return 'bluray'
  if value == 'web-dl':
    return 'webdl'
  if value in ['ddp5', 'dd5']:
    return 'ddp'
  if value in ['dovi', 'dolbyvision']:
    return 'dv'
  return value

def _detect_group_value(token_set, groups):
  for group_name in groups:
    if len(groups[group_name].intersection(token_set)) > 0:
      return group_name
  return ''

def _detect_source_group(token_set):
  normalized = set([_normalize_release_token(token) for token in token_set if token])
  if 'web' in normalized and 'dl' in normalized:
    normalized.add('webdl')
  if 'blu' in normalized and 'ray' in normalized:
    normalized.add('bluray')
  return _detect_group_value(normalized, RELEASE_SOURCE_GROUPS)

def _detect_resolution(token_set):
  for token in token_set:
    match = re.match(r'^(2160|1080|720|576|540|480|360|240)p?$', token)
    if match:
      return '%sp' % (match.group(1))
  return ''

def _detect_codec(token_set):
  normalized = set([_normalize_release_token(token) for token in token_set if token])
  return _detect_group_value(normalized, RELEASE_CODEC_GROUPS)

def _detect_hdr_profile(token_set):
  normalized = set([_normalize_release_token(token) for token in token_set if token])
  return _detect_group_value(normalized, RELEASE_HDR_GROUPS)

def _release_title_tokens(token_set):
  title_tokens = []
  for token in token_set:
    if not token or len(token) <= 1:
      continue
    if token in RELEASE_NOISE_TOKENS:
      continue
    if token in RELEASE_AUDIO_TOKENS:
      continue
    if token in ['web', 'webdl', 'webrip', 'bluray', 'bdrip', 'brrip', 'dvd', 'hdtv', 'hevc', 'hdr', 'dv']:
      continue
    if re.match(r'^(19\d{2}|20\d{2})$', token):
      continue
    if re.match(r'^(2160|1080|720|576|540|480|360|240)p?$', token):
      continue
    if re.match(r'^s\d{1,3}e\d{1,3}$', token):
      continue
    title_tokens.append(token)
  return sorted(title_tokens)

def _build_release_signature(text):
  raw_tokens = re.findall(r'[a-z0-9]+', _as_text(text).lower())
  token_set = set([_normalize_release_token(token) for token in raw_tokens if token])
  season, episode = _extract_season_episode(text)
  signature = {
    'tokens': token_set,
    'title_tokens': _release_title_tokens(token_set),
    'source': _detect_source_group(token_set),
    'resolution': _detect_resolution(token_set),
    'codec': _detect_codec(token_set),
    'hdr': _detect_hdr_profile(token_set),
    'audio': token_set.intersection(RELEASE_AUDIO_TOKENS),
    'year': _extract_release_year(text),
    'season': season,
    'episode': episode,
  }
  return signature

def _evaluate_download_sync_likelihood(video_basename, release_name, result):
  # Heuristic scoring inspired by a4kSubtitles matching ideas, re-implemented for this addon.
  provider_tier = _as_text(result.get('provider_sync_tier', '')).lower()
  if provider_tier not in ['exact', 'likely']:
    provider_tier = ''

  similarity_score = _release_similarity_score(video_basename, release_name)
  video_signature = _build_release_signature(video_basename)
  release_signature = _build_release_signature(release_name)
  video_title_tokens = set(video_signature.get('title_tokens', []))
  release_title_tokens = set(release_signature.get('title_tokens', []))
  title_overlap_count = len(video_title_tokens.intersection(release_title_tokens))
  score = int(round(0.45 * similarity_score))
  hard_conflict = False
  title_strict_ok = True

  if video_signature['season'] and release_signature['season']:
    if video_signature['season'] == release_signature['season']:
      score += 8
    else:
      score -= 22
      hard_conflict = True
  if video_signature['episode'] and release_signature['episode']:
    if video_signature['episode'] == release_signature['episode']:
      score += 22
    else:
      score -= 35
      hard_conflict = True

  if video_signature['year'] and release_signature['year']:
    if video_signature['year'] == release_signature['year']:
      score += 10
    else:
      score -= 14

  if video_signature['source'] and release_signature['source']:
    if video_signature['source'] == release_signature['source']:
      score += 18
    else:
      score -= 20
      if similarity_score < 70:
        hard_conflict = True

  if video_signature['resolution'] and release_signature['resolution']:
    if video_signature['resolution'] == release_signature['resolution']:
      score += 14
    else:
      score -= 10

  if video_signature['codec'] and release_signature['codec']:
    if video_signature['codec'] == release_signature['codec']:
      score += 8
    else:
      score -= 6

  if video_signature['hdr'] and release_signature['hdr']:
    if video_signature['hdr'] == release_signature['hdr']:
      score += 6
    else:
      score -= 4

  audio_overlap = len(video_signature['audio'].intersection(release_signature['audio']))
  if audio_overlap > 0:
    score += min(6, audio_overlap * 2)

  if len(video_signature['title_tokens']) > 0 and len(release_signature['title_tokens']) > 0:
    title_ratio = difflib.SequenceMatcher(
      None,
      ' '.join(video_signature['title_tokens']),
      ' '.join(release_signature['title_tokens'])
    ).ratio()
    score += int(round(title_ratio * 12.0))
    if title_ratio < 0.15 and similarity_score < 35:
      hard_conflict = True
  else:
    title_ratio = 0.0

  if len(video_title_tokens) >= 3:
    if title_overlap_count < 2:
      score -= 28
      hard_conflict = True
      title_strict_ok = False
  elif len(video_title_tokens) == 2:
    if title_overlap_count < 1:
      score -= 24
      hard_conflict = True
      title_strict_ok = False
  elif len(video_title_tokens) == 1:
    if title_overlap_count == 0:
      score -= 20
      hard_conflict = True
      title_strict_ok = False

  if score < 0:
    score = 0
  if score > 100:
    score = 100

  if provider_tier == 'exact':
    tier = 'exact'
    score = max(score, 95)
  elif score >= 88 and similarity_score >= 65 and not hard_conflict and title_strict_ok:
    tier = 'exact'
  elif score >= 60 and not hard_conflict and title_strict_ok:
    tier = 'likely'
  else:
    tier = 'unknown'

  if provider_tier == 'likely' and tier == 'unknown' and score >= 45 and not hard_conflict and title_strict_ok:
    tier = 'likely'

  return {
    'tier': tier,
    'score': score,
    'hard_conflict': hard_conflict,
    'title_overlap': title_overlap_count,
    'title_strict_ok': title_strict_ok,
    'similarity_score': similarity_score,
  }

def _sync_tier_badge(sync_tier):
  if sync_tier == 'exact':
    return '[SYNC]'
  if sync_tier == 'likely':
    return '[LIKELY]'
  return '[?]'

def _download_candidate_sort_key(item):
  sync_tier = _as_text(item.get('sync_tier', 'unknown')).lower()
  tier_rank = int(item.get('sync_tier_rank', SYNC_TIER_PRIORITY.get(sync_tier, 0)))
  sync_score = int(item.get('sync_score', 0))
  unknown_likelihood = int(item.get('unknown_match_likelihood', 0))

  if sync_tier == 'unknown':
    tier_score = unknown_likelihood
  else:
    tier_score = 200 + sync_score

  return (
    -tier_rank,
    -tier_score,
    -sync_score,
    -int(item.get('rank_score', 0)),
    -int(item.get('similarity_score', 0)),
    -int(item.get('provider_score', 0)),
    _as_text(item.get('release_name', '')).lower()
  )

def _rank_download_results(video_basename, language_code, results):
  ranked = []
  target_language = _canonicalize_language_code(language_code)
  for result in results:
    language = _canonicalize_language_code(result.get('language', ''))
    language_score = 100 if language == target_language else 0
    similarity_score = _release_similarity_score(video_basename, result.get('release_name', ''))
    provider_score = int(result.get('provider_score') or 0)
    sync_eval = _evaluate_download_sync_likelihood(video_basename, result.get('release_name', ''), result)
    unknown_eval = _unknown_match_likelihood_score(video_basename, result.get('release_name', ''), similarity_score=similarity_score)
    hearing_penalty = 8 if result.get('hearing_impaired') else 0
    rank_score = int((0.30 * similarity_score) + (0.25 * language_score) + (0.15 * provider_score) + (0.30 * sync_eval.get('score', 0))) - hearing_penalty
    result['rank_score'] = rank_score
    result['similarity_score'] = similarity_score
    result['sync_score'] = int(sync_eval.get('score', 0))
    result['sync_tier'] = sync_eval.get('tier', 'unknown')
    result['sync_tier_rank'] = SYNC_TIER_PRIORITY.get(result['sync_tier'], 0)
    result['hard_conflict'] = bool(sync_eval.get('hard_conflict'))
    result['unknown_match_likelihood'] = int(unknown_eval.get('score', 0))
    result['unknown_title_overlap'] = int(unknown_eval.get('title_overlap', 0))
    ranked.append(result)

  ranked.sort(key=_download_candidate_sort_key)
  return ranked

def _download_result_menu_label(result):
  language_code = _canonicalize_language_code(result.get('language', '')) or 'unk'
  sync_tier = _as_text(result.get('sync_tier', 'unknown')).lower()
  provider_label = _provider_colored_label(result)
  rating_label = _provider_stars(result)
  return '%s %s [B]%s[/B]  %s' % (
    _sync_tier_icon_markup(sync_tier),
    _language_flag_label(language_code),
    _language_display_name(language_code),
    '%s %s' % (provider_label, rating_label)
  )

def _sync_tier_short(sync_tier):
  if sync_tier == 'exact':
    return 'SYNC'
  if sync_tier == 'likely':
    return 'LIKELY'
  return '?'

def _release_traits_label(release_name):
  signature = _build_release_signature(release_name)
  traits = []

  source = _as_text(signature.get('source', '')).strip()
  if source:
    traits.append(source.upper())

  resolution = _as_text(signature.get('resolution', '')).strip()
  if resolution:
    traits.append(resolution)

  codec = _as_text(signature.get('codec', '')).strip()
  if codec:
    traits.append(codec.upper())

  hdr = _as_text(signature.get('hdr', '')).strip()
  if hdr:
    traits.append(hdr.upper())

  audio = sorted(list(signature.get('audio', [])))
  if len(audio) > 0:
    traits.append('/'.join([token.upper() for token in audio[:2]]))

  return ' '.join(traits)

def _download_result_detail_label(result):
  release_name = _as_text(result.get('release_name', '')).strip()
  if not release_name:
    release_name = 'subtitle'
  sync_tier = _as_text(result.get('sync_tier', 'unknown')).lower()
  sync_hint = _sync_tier_hint(sync_tier)
  hi_label = ' [HI]' if result.get('hearing_impaired') else ''
  return '[COLOR gray]%s %s[/COLOR]%s' % (sync_hint, release_name, hi_label)

def _language_flag_label(language_code):
  code = _canonicalize_language_code(language_code)
  if not code:
    return u'\u25A1'
  flag = LANGUAGE_FLAG_EMOJI.get(code, '')
  if flag:
    return flag
  return '[%s]' % (code.upper())

def _sync_tier_icon_markup(sync_tier):
  if sync_tier == 'exact':
    return '[COLOR springgreen]✓[/COLOR]'
  if sync_tier == 'likely':
    return '[COLOR gold]≈[/COLOR]'
  return '[COLOR gray]%s[/COLOR]' % (__language__(33305))

def _sync_tier_hint(sync_tier):
  if sync_tier == 'exact':
    return u'\u2713'
  if sync_tier == 'likely':
    return u'\u2248'
  return __language__(33305)

def _provider_stars(result):
  try:
    provider_score = int(result.get('provider_score', 0))
  except Exception:
    provider_score = 0

  filled = int(round(float(provider_score) / 20.0))
  if filled < 0:
    filled = 0
  if filled > 5:
    filled = 5
  empty = 5 - filled
  if empty < 0:
    empty = 0
  return '[COLOR gold]%s[/COLOR][COLOR gray]%s[/COLOR]' % ((u'\u2605' * filled), (u'\u2606' * empty))

def _download_flag_icon_path(language_code):
  code = _canonicalize_language_code(language_code) or ''
  alias_map = {
    'en': 'gb',
  }
  if code in alias_map:
    code = alias_map.get(code, code)
  path = ''
  if code:
    path = os.path.join(__flags__, '%s.png' % (code.lower()))
    if xbmcvfs.exists(path):
      return path
  fallback = os.path.join(__flags__, 'default.png')
  if xbmcvfs.exists(fallback):
    return fallback
  if path:
    return path
  return fallback

def _download_sync_icon_path(sync_tier):
  tier = _as_text(sync_tier).lower()
  if tier == 'exact':
    file_name = 'exact.png'
  elif tier == 'likely':
    file_name = 'likely.png'
  else:
    file_name = 'unknown.png'

  path = os.path.join(__syncicons__, file_name)
  if xbmcvfs.exists(path):
    return path

  fallback = os.path.join(__syncicons__, 'unknown.png')
  if xbmcvfs.exists(fallback):
    return fallback
  return path

def _sync_tier_window_label(sync_tier):
  tier = _as_text(sync_tier).lower()
  if tier == 'exact':
    return '[COLOR springgreen]%s[/COLOR]' % (_sync_tier_text(sync_tier))
  if tier == 'likely':
    return '[COLOR gold]%s[/COLOR]' % (_sync_tier_text(sync_tier))
  return '[COLOR gray]%s[/COLOR]' % (_sync_tier_text(sync_tier))

def _sync_tier_inline_label(sync_tier):
  tier = _as_text(sync_tier).lower()
  if tier == 'exact':
    return '[COLOR springgreen]%s[/COLOR]' % (_sync_tier_text(sync_tier))
  if tier == 'likely':
    return '[COLOR gold]%s[/COLOR]' % (_sync_tier_text(sync_tier))
  return '[COLOR gray]%s[/COLOR]' % (_sync_tier_text(sync_tier))

def _sync_tier_text(sync_tier):
  tier = _as_text(sync_tier).lower()
  if tier == 'exact':
    return 'SYNC'
  if tier == 'likely':
    return 'LIKELY'
  return __language__(33305)

def _window_language_line(language_name, language_code):
  label = _as_text(language_name).strip()
  if label and len(label) <= 7:
    return label
  code = _canonicalize_language_code(language_code) or _as_text(language_code).strip().lower()
  if code:
    return code.upper()
  if label:
    return label[:7]
  return 'N/A'

def _compact_release_traits_label(release_name):
  traits = _release_traits_label(release_name)
  if not traits:
    return ''
  compact = traits.replace(' ', ' · ').lower()
  if len(compact) > 74:
    return '%s...' % (compact[:71])
  return compact

def _build_download_window_listitem(result):
  release_name = _as_text(result.get('release_name', '')).strip()
  if not release_name:
    release_name = 'subtitle'
  release_display = release_name.replace('.', ' ').replace('_', ' ')

  language_code = _canonicalize_language_code(result.get('language', '')) or 'unk'
  language_name = _language_display_name(language_code)
  provider_line = _provider_colored_label(result)
  stars_line = _provider_stars(result)
  sync_tier = _as_text(result.get('sync_tier', 'unknown')).lower()
  sync_line = _sync_tier_window_label(sync_tier)
  hi_line = ' [COLOR gold]HI[/COLOR]' if result.get('hearing_impaired') else ''
  extra_line_override = _as_text(result.get('display_extra_line', '')).strip()
  extra_line = extra_line_override if extra_line_override else _compact_release_traits_label(release_name)
  flag_icon = _download_flag_icon_path(language_code)
  sync_icon = _download_sync_icon_path(sync_tier)

  try:
    item = xbmcgui.ListItem(label=release_display, label2=language_name)
  except Exception:
    item = xbmcgui.ListItem(release_display)

  item.setProperty('release_line', release_display)
  item.setProperty('provider_line', '%s%s' % (provider_line, hi_line))
  item.setProperty('stars_line', stars_line)
  item.setProperty('sync_line', sync_line)
  item.setProperty('language_line', _window_language_line(language_name, language_code))
  item.setProperty('extra_line', extra_line)
  item.setProperty('flag_icon', flag_icon)
  item.setProperty('sync_icon', sync_icon)

  try:
    item.setArt({
      'icon': flag_icon,
      'thumb': sync_icon,
    })
  except Exception:
    pass

  try:
    item.setProperty('sync', 'true' if sync_tier in ['exact', 'likely'] else 'false')
    item.setProperty('hearing_imp', 'true' if result.get('hearing_impaired') else 'false')
  except Exception:
    pass
  return item

def _select_download_result_dialog_select(results, language_label):
  option_labels = []
  option_items = []
  for item in results:
    option_labels.append(_download_result_browser_label2(item))
    option_items.append(_build_download_browser_listitem(item))

  try:
    return __msg_box__.select(__language__(33178) % (language_label), option_items, useDetails=True)
  except TypeError:
    try:
      return __msg_box__.select(__language__(33178) % (language_label), option_items)
    except Exception:
      return __msg_box__.select(__language__(33178) % (language_label), option_labels)
  except Exception:
    return __msg_box__.select(__language__(33178) % (language_label), option_labels)

def _select_download_result_with_custom_window(results, language_label, video_basename):
  if DownloadPickerDialog is None:
    return _select_download_result_dialog_select(results, language_label)

  provider_names = _configured_download_provider_names()
  providers_label = ' | '.join(provider_names)
  dialog_items = []
  for item in results:
    dialog_items.append(_build_download_window_listitem(item))

  try:
    dialog = DownloadPickerDialog(
      DOWNLOAD_PICKER_XML,
      __cwd__,
      'default',
      '1080i',
      heading=__language__(33178) % (language_label),
      subtitle=video_basename,
      providers=providers_label,
      listitems=dialog_items
    )
    dialog.doModal()
    selected = int(dialog.selected_index)
    del dialog
    if selected >= 0 and selected < len(results):
      return selected
    return -1
  except Exception as exc:
    _log('custom download picker failed, falling back to default selector (%s)' % (exc), LOG_WARNING)
    return _select_download_result_dialog_select(results, language_label)

def _build_download_result_listitem(result):
  language_code = _canonicalize_language_code(result.get('language', '')) or 'unk'
  label = _download_result_menu_label(result)
  label2 = _download_result_detail_label(result)
  try:
    item = xbmcgui.ListItem(label=label, label2=label2)
  except Exception:
    item = xbmcgui.ListItem(label)
    try:
      item.setLabel2(label2)
    except Exception:
      pass

  try:
    provider_score = int(result.get('provider_score', 0))
  except Exception:
    provider_score = 0
  provider_rating = int(round(float(provider_score) / 20.0))
  if provider_rating < 0:
    provider_rating = 0
  if provider_rating > 5:
    provider_rating = 5

  try:
    item.setArt({
      'icon': str(provider_rating),
      'thumb': language_code.lower(),
    })
  except Exception:
    pass

  try:
    sync_tier = _as_text(result.get('sync_tier', '')).lower()
    item.setProperty('sync', 'true' if sync_tier in ['exact', 'likely'] else 'false')
    item.setProperty('hearing_imp', 'true' if result.get('hearing_impaired') else 'false')
  except Exception:
    pass
  return item

def _provider_color(provider_value):
  provider_key = _as_text(provider_value).strip().lower()
  if provider_key in DOWNLOAD_PROVIDER_COLORS:
    return DOWNLOAD_PROVIDER_COLORS[provider_key]
  if provider_key in ['opensubtitles', 'open subtitles']:
    return DOWNLOAD_PROVIDER_COLORS.get('opensubtitles', 'white')
  if provider_key in ['podnadpisi', 'podnapisi']:
    return DOWNLOAD_PROVIDER_COLORS.get('podnadpisi', 'white')
  if provider_key == 'subdl':
    return DOWNLOAD_PROVIDER_COLORS.get('subdl', 'white')
  if provider_key in ['bsplayer', 'bs player']:
    return DOWNLOAD_PROVIDER_COLORS.get('bsplayer', 'white')
  return 'white'

def _provider_colored_label(result):
  provider_name = _as_text(result.get('provider', 'provider')).strip() or 'provider'
  color = _provider_color(result.get('provider_key', provider_name))
  return '[COLOR %s]%s[/COLOR]' % (color, provider_name)

def _language_display_name(language_code):
  code = _canonicalize_language_code(language_code) or _as_text(language_code).lower().strip()
  if not code:
    return __language__(33018)
  try:
    name = xbmc.convertLanguage(code, xbmc.ENGLISH_NAME)
    if name and name.strip() and name.lower().strip() != code:
      return name
  except Exception:
    pass
  return code.upper()

def _download_result_browser_label2(result):
  release_name = _as_text(result.get('release_name', '')).strip()
  if not release_name:
    release_name = 'subtitle'
  item_name, item_ext = os.path.splitext(release_name)
  if item_name:
    release_display = item_name.replace('.', ' ').replace('_', ' ')
  else:
    release_display = release_name.replace('.', ' ').replace('_', ' ')
  if item_ext:
    ext_label = item_ext.replace('.', '').upper()
  else:
    ext_label = 'SRT'

  sync_tier = _as_text(result.get('sync_tier', 'unknown')).lower()
  provider_label = _provider_colored_label(result)
  hi_label = ''
  if result.get('hearing_impaired'):
    hi_label = ' [COLOR gold]HI[/COLOR]'
  sync_label = _sync_tier_inline_label(sync_tier)
  base_line = '%s ([B]%s[/B]) ([B]%s%s[/B]) [COLOR gray]|[/COLOR] %s' % (release_display, ext_label, provider_label, hi_label, sync_label)
  extra_line = _as_text(result.get('display_extra_line', '')).strip()
  if extra_line:
    return '%s[CR][COLOR gray]%s[/COLOR]' % (base_line, extra_line)
  # Layout intentionally mirrors a4k's native subtitle list style:
  # "<release> (EXT) (Provider)" with provider color emphasis.
  return base_line

def _a4k_thumb_language_code(language_code):
  code = _canonicalize_language_code(language_code) or _as_text(language_code).lower().strip()
  if not code:
    return 'en'
  if code == 'en':
    return 'gb'
  if len(code) > 2:
    return code[:2]
  return code

def _build_download_browser_listitem(result):
  language_code = _canonicalize_language_code(result.get('language', '')) or 'unk'
  label = _language_display_name(language_code)
  label2 = _download_result_browser_label2(result)

  try:
    item = xbmcgui.ListItem(label=label, label2=label2, offscreen=True)
  except Exception:
    item = xbmcgui.ListItem(label)
    try:
      item.setLabel2(label2)
    except Exception:
      pass

  provider_score = int(result.get('provider_score', 0))
  provider_rating = int(round(float(provider_score) / 20.0))
  if provider_rating < 0:
    provider_rating = 0
  if provider_rating > 5:
    provider_rating = 5

  try:
    item.setArt({
      'icon': str(provider_rating),
      'thumb': _a4k_thumb_language_code(language_code),
    })
  except Exception:
    pass

  sync_tier = _as_text(result.get('sync_tier', '')).lower()
  sync_value = 'true' if sync_tier == 'exact' else 'false'
  try:
    item.setProperty('sync', sync_value)
    item.setProperty('hearing_imp', 'true' if result.get('hearing_impaired') else 'false')
  except Exception:
    pass
  return item

def _select_download_language():
  options = []
  languages = []

  preferred1 = _parse_language_code('preferred_language_1')
  preferred2 = _parse_language_code('preferred_language_2')

  if preferred1:
    options.append('%s (%s)' % (_language_label('preferred_language_1'), preferred1.upper()))
    languages.append(preferred1)
  if preferred2 and preferred2 != preferred1:
    options.append('%s (%s)' % (_language_label('preferred_language_2'), preferred2.upper()))
    languages.append(preferred2)

  options.append(__language__(33197))
  selected = __msg_box__.select(__language__(33185), options)
  if selected is None or selected < 0:
    return None, ''

  if selected < len(languages):
    code = languages[selected]
    return code, code.upper()

  custom_code = ''
  try:
    custom_code = __msg_box__.input(__language__(33196))
  except Exception:
    custom_code = ''
  normalized = _canonicalize_language_code(custom_code)
  if not normalized:
    _notify(__language__(33194), NOTIFY_WARNING)
    return None, ''
  return normalized, normalized.upper()

def _notify_download_provider_warning_once(provider_name, message):
  key = _as_text(provider_name).lower()
  if not key:
    return
  if DOWNLOAD_PROVIDER_WARNING_SHOWN.get(key):
    return
  DOWNLOAD_PROVIDER_WARNING_SHOWN[key] = True
  _notify(message, NOTIFY_WARNING, timeout=5000)

def _format_download_provider_user_message(provider, exc, auth_error=False):
  provider_name = _as_text(getattr(provider, 'display_name', getattr(provider, 'name', 'provider'))).strip() or 'Provider'
  provider_key = _as_text(getattr(provider, 'name', provider_name)).lower().strip()
  error_text = _as_text(exc).strip()
  lowered = error_text.lower()

  if provider_key == 'opensubtitles':
    if auth_error:
      if 'incomplete' in lowered or 'missing' in lowered:
        return 'OpenSubtitles setup is incomplete. Enter username, password, and API key in Subtitle Suite settings.'
      return 'OpenSubtitles login failed. Use your OpenSubtitles username (not email), password, and API key.'
    if 'download limit' in lowered or 'no downloads left' in lowered:
      return 'OpenSubtitles download limit reached for today.'
    if '(429)' in lowered or 'too many requests' in lowered:
      return 'OpenSubtitles is temporarily rate limited. Please try again in a bit.'
    if '(503)' in lowered or 'service unavailable' in lowered:
      return 'OpenSubtitles is temporarily unavailable. Please try again in a bit.'
    if 'network error' in lowered:
      return 'OpenSubtitles network error. Check your connection and try again.'
    return 'OpenSubtitles request failed. Please check your credentials and try again.'

  if provider_key == 'subdl':
    if auth_error:
      return 'SubDL setup is incomplete. Enter a valid SubDL API key in Subtitle Suite settings.'
    if 'network error' in lowered:
      return 'SubDL network error. Check your connection and try again.'
    return '%s request failed.' % (provider_name)

  if provider_key == 'podnadpisi':
    if 'too-many-requests' in lowered or '(429)' in lowered:
      return 'Podnadpisi is temporarily rate limited. Please try again later.'
    if 'network error' in lowered:
      return 'Podnadpisi network error. Check your connection and try again.'
    return '%s request failed.' % (provider_name)

  if provider_key == 'bsplayer':
    if 'network error' in lowered:
      return 'BSPlayer network error. Check your connection and try again.'
    return '%s request failed.' % (provider_name)

  if auth_error:
    return '%s credentials are incomplete or invalid.' % (provider_name)
  if 'network error' in lowered:
    return '%s network error. Check your connection and try again.' % (provider_name)
  return '%s request failed.' % (provider_name)

def _is_download_provider_runtime_disabled(provider_name):
  key = _as_text(provider_name).lower().strip()
  if not key:
    return False
  return bool(DOWNLOAD_PROVIDER_RUNTIME_DISABLED.get(key))

def _disable_download_provider_for_session(provider_name):
  key = _as_text(provider_name).lower().strip()
  if not key:
    return
  if DOWNLOAD_PROVIDER_RUNTIME_DISABLED.get(key):
    return
  DOWNLOAD_PROVIDER_RUNTIME_DISABLED[key] = True
  _log('download provider temporarily disabled for current run: %s' % (key), LOG_WARNING)

def _configured_download_provider_names():
  names = []
  if _is_opensubtitles_enabled():
    names.append('OpenSubtitles')
  if _is_podnadpisi_enabled():
    names.append('Podnadpisi')
  if _is_subdl_enabled():
    names.append('SubDL')
  if _is_bsplayer_enabled():
    names.append('BSPlayer')
  return names

def _download_results_cache_file():
  return os.path.join(__profile__, 'download_results_cache.json')

def _serialize_download_result_for_cache(result):
  return {
    'provider': _as_text(result.get('provider', '')),
    'provider_key': _as_text(result.get('provider_key', '')).lower(),
    'file_id': _as_text(result.get('file_id', '')),
    'download_url': _as_text(result.get('download_url', '')),
    'language': _as_text(result.get('language', '')),
    'release_name': _as_text(result.get('release_name', '')),
    'hearing_impaired': bool(result.get('hearing_impaired')),
    'provider_score': int(result.get('provider_score', 0)),
    'download_count': int(result.get('download_count', 0)),
    'sync_tier': _as_text(result.get('sync_tier', 'unknown')).lower(),
    'sync_score': int(result.get('sync_score', 0)),
    'similarity_score': int(result.get('similarity_score', 0)),
    'rank_score': int(result.get('rank_score', 0)),
  }

def _save_download_results_cache(payload):
  cache_path = _download_results_cache_file()
  try:
    with open(cache_path, 'wb') as file_handle:
      file_handle.write(_to_utf8_bytes(json.dumps(payload)))
    return True
  except Exception as exc:
    _log('download cache write failed: %s' % (exc), LOG_WARNING)
    return False

def _load_download_results_cache(token):
  cache_path = _download_results_cache_file()
  if not xbmcvfs.exists(cache_path):
    return None
  try:
    with open(cache_path, 'rb') as file_handle:
      data = file_handle.read()
    payload = json.loads(_as_text(data))
  except Exception as exc:
    _log('download cache read failed: %s' % (exc), LOG_WARNING)
    return None

  if not isinstance(payload, dict):
    return None
  if _as_text(payload.get('token', '')) != _as_text(token):
    return None
  return payload

def _resolve_provider_for_cached_result(result):
  provider_key = _as_text(result.get('provider_key', '')).lower()
  if not provider_key:
    return None

  providers = get_enabled_subtitle_providers(_build_download_provider_config(), logger=_log)
  for provider in providers:
    if _as_text(provider.name).lower() != provider_key:
      continue
    try:
      provider.validate_config()
    except Exception:
      return None
    return provider
  return None

def _get_ready_download_providers():
  if not _is_subtitle_download_enabled():
    raise RuntimeError(__language__(33172))

  providers = get_enabled_subtitle_providers(_build_download_provider_config(), logger=_log)
  if len(providers) == 0:
    raise RuntimeError(__language__(33173))

  ready = []
  auth_errors = 0
  last_auth_message = ''
  for provider in providers:
    if _is_download_provider_runtime_disabled(provider.name):
      continue
    try:
      provider.validate_config()
      ready.append(provider)
    except ProviderAuthError as exc:
      auth_errors += 1
      last_auth_message = _format_download_provider_user_message(provider, exc, auth_error=True)
      _log('download provider config invalid (%s): %s' % (provider.name, exc), LOG_WARNING)
      _notify_download_provider_warning_once(provider.name, last_auth_message)
    except Exception as exc:
      _log('download provider validation failed (%s): %s' % (provider.name, exc), LOG_WARNING)

  if len(ready) == 0:
    if auth_errors > 0:
      raise RuntimeError(last_auth_message or __language__(33223))
    raise RuntimeError(__language__(33173))
  return ready

def _search_download_results(context, language_code):
  providers = _get_ready_download_providers()
  max_results = _get_download_max_results()
  _log(
    'download search start: language=%s query=%s imdb=%s year=%s season=%s episode=%s providers=%s'
    % (
      _as_text(language_code),
      _as_text(context.get('query', '')),
      _as_text(context.get('imdb_id', '')),
      _as_text(context.get('year', '')),
      _as_text(context.get('season', '')),
      _as_text(context.get('episode', '')),
      ', '.join([_as_text(getattr(provider, 'display_name', provider.name)) for provider in providers])
    ),
    LOG_INFO
  )

  aggregated = []
  auth_failures = 0
  request_failures = 0
  last_auth_message = ''
  last_request_message = ''

  for provider in providers:
    try:
      results = provider.search(context, language_code, max_results)
      _log(
        'download provider results (%s): %d' % (
          _as_text(getattr(provider, 'display_name', provider.name)),
          len(results)
        ),
        LOG_INFO
      )
      for item in results:
        aggregated.append(item)
    except ProviderAuthError as exc:
      auth_failures += 1
      last_auth_message = _format_download_provider_user_message(provider, exc, auth_error=True)
      _log('download provider auth failed (%s): %s' % (provider.name, exc), LOG_WARNING)
      _notify_download_provider_warning_once(provider.name, last_auth_message)
    except ProviderRequestError as exc:
      request_failures += 1
      last_request_message = _format_download_provider_user_message(provider, exc, auth_error=False)
      _log('download provider request failed (%s): %s' % (provider.name, exc), LOG_WARNING)
      provider_key = _as_text(getattr(provider, 'name', '')).lower().strip()
      if provider_key == 'bsplayer':
        exc_text = _as_text(exc).lower()
        if 'timed out' in exc_text or 'timeout' in exc_text or 'network error' in exc_text:
          _disable_download_provider_for_session(provider.name)
    except Exception as exc:
      request_failures += 1
      last_request_message = _format_download_provider_user_message(provider, exc, auth_error=False)
      _log('download provider unexpected failure (%s): %s' % (provider.name, exc), LOG_WARNING)

  if len(aggregated) == 0:
    if auth_failures > 0 and auth_failures == len(providers):
      raise RuntimeError(last_auth_message or __language__(33181))
    if request_failures > 0 and request_failures == len(providers):
      raise RuntimeError(last_request_message or __language__(33182))
    return []

  deduped = []
  seen = {}
  for item in aggregated:
    key = '%s:%s' % (_as_text(item.get('provider_key', 'provider')).lower(), _as_text(item.get('file_id', '')))
    if key in seen:
      continue
    seen[key] = True
    deduped.append(item)

  return _rank_download_results(context.get('video_basename', ''), language_code, deduped)[:max_results]

def _write_download_payload_to_target(context, language_code, selected_result):
  provider = selected_result.get('_provider_ref')
  if provider is None:
    provider = _resolve_provider_for_cached_result(selected_result)
  if provider is None:
    raise RuntimeError(__language__(33193))

  payload = provider.download(selected_result)
  data = payload.get('content_bytes')
  if data is None:
    raise RuntimeError(__language__(33193))
  if not isinstance(data, bytes):
    data = _to_utf8_bytes(data)

  temp_subtitle = os.path.join(__temp__, '%s.srt' % (str(uuid.uuid4())))
  try:
    with open(temp_subtitle, 'wb') as file_handle:
      file_handle.write(data)
  except Exception as exc:
    _log('download temp write failed: %s' % (exc), LOG_WARNING)
    raise RuntimeError(__language__(33193))

  target_language = _canonicalize_language_code(language_code) or language_code.lower()
  target_path = os.path.join(context['video_dir'], '%s.%s.srt' % (context['video_basename'], target_language))
  try:
    _replace_file_with_dualsubs_backup(temp_subtitle, target_path, backup_existing=True)
    return target_path
  except Exception as exc:
    _log('download target write failed: path=%s error=%s' % (target_path, exc), LOG_WARNING)
    raise RuntimeError(__language__(33180))
  finally:
    try:
      if xbmcvfs.exists(temp_subtitle):
        xbmcvfs.delete(temp_subtitle)
    except Exception:
      pass

def _notify_top_download_candidate(results):
  if len(results) == 0:
    return
  top_result = results[0]
  top_tier = _as_text(top_result.get('sync_tier', 'unknown')).lower()
  top_release = _as_text(top_result.get('release_name', 'subtitle'))
  if top_tier == 'exact':
    _notify(__language__(33225) % (top_release), NOTIFY_INFO, timeout=3500)
  elif top_tier == 'likely':
    _notify(__language__(33226) % (top_release), NOTIFY_INFO, timeout=3500)
  _log(
    'download candidate top: tier=%s sync_score=%s rank=%s release=%s provider=%s' % (
      top_tier or 'unknown',
      int(top_result.get('sync_score', 0)),
      int(top_result.get('rank_score', 0)),
      top_release,
      _as_text(top_result.get('provider', 'provider'))
    ),
    LOG_INFO
  )

def _normalize_required_sync_tiers(required_tiers):
  allowed = []
  for tier in (required_tiers or []):
    normalized = _as_text(tier).lower().strip()
    if normalized in ['exact', 'likely', 'unknown'] and normalized not in allowed:
      allowed.append(normalized)
  return allowed

def _build_sync_tier_candidates(results, required_tiers=None, fallback_to_top=True):
  if not results:
    return []

  allowed = _normalize_required_sync_tiers(required_tiers)
  if len(allowed) == 0:
    return list(results)

  filtered = []
  for item in results:
    if _as_text(item.get('sync_tier', 'unknown')).lower() in allowed:
      filtered.append(item)

  if len(filtered) > 0:
    return filtered
  if fallback_to_top:
    return list(results)
  return []

def _is_fallback_title_compatible(video_basename, release_name):
  video_signature = _build_release_signature(video_basename)
  release_signature = _build_release_signature(release_name)
  video_title_tokens = set(video_signature.get('title_tokens', []))
  release_title_tokens = set(release_signature.get('title_tokens', []))

  if len(video_title_tokens) == 0 or len(release_title_tokens) == 0:
    return True

  overlap = len(video_title_tokens.intersection(release_title_tokens))
  if len(video_title_tokens) >= 3:
    if overlap < 2:
      return False
  elif overlap < 1:
    return False

  video_year = _as_text(video_signature.get('year', '')).strip()
  release_year = _as_text(release_signature.get('year', '')).strip()
  if video_year and release_year and video_year != release_year:
    return False

  return True

def _select_best_download_result(results, required_tiers=None, fallback_to_top=True):
  candidates = _build_sync_tier_candidates(results, required_tiers=required_tiers, fallback_to_top=fallback_to_top)
  if len(candidates) == 0:
    return None
  return candidates[0]

def _is_retryable_download_error(error):
  message = _as_text(error).lower()
  retry_tokens = [
    '(429)',
    '(500)',
    '(502)',
    '(503)',
    '(504)',
    'service unavailable',
    'temporarily unavailable',
    'timed out',
    'timeout',
    'network error',
    'connection reset',
    'connection aborted',
    'too many requests',
  ]
  for token in retry_tokens:
    if token in message:
      return True
  return False

def _interleave_download_candidates_by_provider(candidate_results):
  if not candidate_results:
    return []

  grouped = {}
  provider_order = []
  for item in candidate_results:
    provider_key = _as_text(item.get('provider_key') or item.get('provider') or 'provider').lower()
    if not provider_key:
      provider_key = 'provider'
    if provider_key not in grouped:
      grouped[provider_key] = []
      provider_order.append(provider_key)
    grouped[provider_key].append(item)

  ordered = []
  index = 0
  while True:
    appended = False
    for provider_key in provider_order:
      items = grouped.get(provider_key, [])
      if index < len(items):
        ordered.append(items[index])
        appended = True
    if not appended:
      break
    index += 1
  return ordered

def _download_best_result_for_language(
  video_dir,
  video_basename,
  language_code,
  language_label='',
  required_tiers=None,
  fallback_to_top=True,
  notify_errors=True,
  max_write_attempts=5,
  request_delay_seconds=0.0,
  max_provider_attempts=2,
  retry_delay_seconds=0.9,
  progress_callback=None,
  progress_label=''
):
  response = {
    'path': '',
    'result': None,
    'results': [],
  }
  if not video_dir or not video_basename or not language_code:
    return response

  context = _build_download_context(video_dir, video_basename)
  normalized_language = _canonicalize_language_code(language_code) or _as_text(language_code).lower().strip()
  if not normalized_language:
    return response

  if not language_label:
    language_label = _language_display_name(normalized_language)

  if request_delay_seconds and request_delay_seconds > 0:
    try:
      time.sleep(float(request_delay_seconds))
    except Exception:
      pass

  try:
    results = _search_download_results(context, normalized_language)
  except RuntimeError as exc:
    if notify_errors:
      _notify(_as_text(exc), NOTIFY_WARNING)
    _log('lucky download search failed for %s: %s' % (normalized_language, exc), LOG_WARNING)
    return response
  except Exception as exc:
    if notify_errors:
      _notify(__language__(33193), NOTIFY_WARNING)
    _log('lucky download search unexpected failure for %s: %s' % (normalized_language, exc), LOG_WARNING)
    return response

  response['results'] = results
  if len(results) == 0:
    return response

  candidate_results = _build_sync_tier_candidates(results, required_tiers=required_tiers, fallback_to_top=fallback_to_top)
  if len(candidate_results) == 0:
    return response
  if fallback_to_top:
    filtered_candidates = []
    for item in candidate_results:
      tier = _as_text(item.get('sync_tier', 'unknown')).lower()
      if tier != 'unknown':
        filtered_candidates.append(item)
        continue

      unknown_likelihood = int(item.get('unknown_match_likelihood', 0))
      if unknown_likelihood <= 0:
        unknown_eval = _unknown_match_likelihood_score(
          video_basename,
          _as_text(item.get('release_name', '')),
          similarity_score=int(item.get('similarity_score', 0))
        )
        unknown_likelihood = int(unknown_eval.get('score', 0))
        item['unknown_match_likelihood'] = unknown_likelihood

      # Keep unknown fallback candidates ordered by title-likelihood, but
      # skip clearly unrelated results before we attempt a download.
      if unknown_likelihood < 32:
        continue
      if (
        not _is_fallback_title_compatible(video_basename, _as_text(item.get('release_name', '')))
        and unknown_likelihood < 48
      ):
        continue
      filtered_candidates.append(item)
    candidate_results = filtered_candidates
    if len(candidate_results) == 0:
      _log(
        'lucky download rejected all fallback candidates: language=%s video=%s'
        % (normalized_language, video_basename),
        LOG_WARNING
      )
      return response
    candidate_results.sort(key=_download_candidate_sort_key)
  candidate_results = _interleave_download_candidates_by_provider(candidate_results)

  try:
    attempt_limit = int(max_write_attempts)
  except Exception:
    attempt_limit = 5
  if attempt_limit < 1:
    attempt_limit = 1
  attempt_limit = min(attempt_limit, len(candidate_results))
  try:
    provider_attempt_limit = int(max_provider_attempts)
  except Exception:
    provider_attempt_limit = 2
  if provider_attempt_limit < 1:
    provider_attempt_limit = 1
  provider_attempt_counts = {}
  global_attempt = 0

  for selected_result in candidate_results:
    if global_attempt >= attempt_limit:
      break

    provider_key = _as_text(selected_result.get('provider_key') or selected_result.get('provider') or 'provider').lower()
    if not provider_key:
      provider_key = 'provider'
    provider_attempt_count = int(provider_attempt_counts.get(provider_key, 0))
    if provider_attempt_count >= provider_attempt_limit:
      continue
    provider_attempt_count += 1
    provider_attempt_counts[provider_key] = provider_attempt_count
    global_attempt += 1
    if progress_callback is not None:
      try:
        provider_name = _as_text(selected_result.get('provider', provider_key))
        release_name = _as_text(selected_result.get('release_name', 'subtitle'))
        short_release = release_name if len(release_name) <= 68 else ('%s...' % (release_name[:65]))
        if progress_label:
          progress_callback('%s: %s (%s)' % (progress_label, provider_name, short_release))
        else:
          progress_callback('%s (%s)' % (provider_name, short_release))
      except Exception:
        pass

    try:
      target_path = _write_download_payload_to_target(context, normalized_language, selected_result)
      response['path'] = target_path
      response['result'] = selected_result
      _log(
        'lucky download selected: language=%s provider=%s tier=%s sync_score=%s release=%s path=%s'
        % (
          normalized_language,
          _as_text(selected_result.get('provider', provider_key)),
          _as_text(selected_result.get('sync_tier', 'unknown')).lower(),
          int(selected_result.get('sync_score', 0)),
          _as_text(selected_result.get('release_name', 'subtitle')),
          target_path
        ),
        LOG_INFO
      )
      return response
    except RuntimeError as exc:
      _log(
        'lucky download write failed for %s attempt=%d/%d provider=%s release=%s error=%s'
        % (
          normalized_language,
          global_attempt,
          attempt_limit,
          _as_text(selected_result.get('provider', 'provider')),
          _as_text(selected_result.get('release_name', 'subtitle')),
          exc
        ),
        LOG_WARNING
      )
      if _is_retryable_download_error(exc):
        try:
          time.sleep(float(retry_delay_seconds) * float(provider_attempt_count))
        except Exception:
          pass
      continue
    except Exception as exc:
      _log(
        'lucky download unexpected write failure for %s attempt=%d/%d provider=%s release=%s error=%s'
        % (
          normalized_language,
          global_attempt,
          attempt_limit,
          _as_text(selected_result.get('provider', 'provider')),
          _as_text(selected_result.get('release_name', 'subtitle')),
          exc
        ),
        LOG_WARNING
      )
      if _is_retryable_download_error(exc):
        try:
          time.sleep(float(retry_delay_seconds) * float(provider_attempt_count))
        except Exception:
          pass
      continue

  if notify_errors:
    _notify(__language__(33193), NOTIFY_WARNING)
  return response

def _pick_best_exact_local_language_match(video_dir, video_basename, language_code):
  matches = _find_subtitle_matches(video_dir, video_basename, language_code, strict=True)
  if len(matches) == 0:
    return ''

  matches.sort(key=lambda item: (len(os.path.basename(item)), os.path.basename(item).lower()))
  return matches[0]

def _pick_best_local_likely_language_match(video_dir, video_basename, language_code):
  target_language = _canonicalize_language_code(language_code)
  if not target_language:
    return ''

  candidates = []
  for path in _list_srt_files(video_dir, include_generated=False):
    detected = _canonicalize_language_code(_detect_language_from_filename(path))
    if not detected:
      detected = _canonicalize_language_code(_detect_language_from_content(path))
    if detected != target_language:
      continue

    release_name = os.path.splitext(os.path.basename(path))[0]
    sync_eval = _evaluate_download_sync_likelihood(video_basename, release_name, {})
    tier = _as_text(sync_eval.get('tier', 'unknown')).lower()
    if tier not in ['exact', 'likely']:
      continue
    sync_score = int(sync_eval.get('score', 0))
    similarity = _release_similarity_score(video_basename, release_name)
    candidates.append((path, tier, sync_score, similarity))

  if len(candidates) == 0:
    return ''

  candidates.sort(
    key=lambda item: (
      -int(SYNC_TIER_PRIORITY.get(item[1], 0)),
      -int(item[2]),
      -int(item[3]),
      len(os.path.basename(item[0])),
      os.path.basename(item[0]).lower()
    )
  )
  return candidates[0][0]

def _pick_best_local_any_language_match(video_dir, language_code):
  target_language = _canonicalize_language_code(language_code)
  if not target_language:
    return ''

  candidates = []
  for path in _list_srt_files(video_dir, include_generated=False):
    detected = _canonicalize_language_code(_detect_language_from_filename(path))
    if not detected:
      detected = _canonicalize_language_code(_detect_language_from_content(path))
    if detected != target_language:
      continue
    candidates.append(path)

  if len(candidates) == 0:
    return ''
  candidates.sort(key=lambda item: (len(os.path.basename(item)), os.path.basename(item).lower()))
  return candidates[0]

def _build_unknown_match_risk_reason(video_basename, result):
  release_name = _as_text(result.get('release_name', ''))
  unknown_eval = _unknown_match_likelihood_score(
    video_basename,
    release_name,
    similarity_score=int(result.get('similarity_score', 0))
  )
  score = int(unknown_eval.get('score', 0))
  overlap = int(unknown_eval.get('title_overlap', 0))
  video_signature = _build_release_signature(video_basename)
  release_signature = _build_release_signature(release_name)

  if len(video_signature.get('title_tokens', [])) >= 2 and overlap == 0:
    return __language__(33289)
  if (
    _as_text(video_signature.get('year', '')).strip()
    and _as_text(release_signature.get('year', '')).strip()
    and _as_text(video_signature.get('year', '')).strip() != _as_text(release_signature.get('year', '')).strip()
  ):
    return __language__(33290)
  if (
    _as_text(video_signature.get('source', '')).strip()
    and _as_text(release_signature.get('source', '')).strip()
    and _as_text(video_signature.get('source', '')).strip() != _as_text(release_signature.get('source', '')).strip()
  ):
    return __language__(33291)
  if score < 25:
    return __language__(33292)
  if score < 45:
    return __language__(33293)
  return __language__(33284)

def _collect_lucky_unknown_candidates(video_dir, video_basename, language_code, max_candidates=3):
  if not video_dir or not video_basename or not language_code:
    return []

  context = _build_download_context(video_dir, video_basename)
  normalized_language = _canonicalize_language_code(language_code) or _as_text(language_code).lower().strip()
  if not normalized_language:
    return []

  try:
    results = _search_download_results(context, normalized_language)
  except RuntimeError as exc:
    _log('lucky unknown candidate search failed for %s: %s' % (normalized_language, exc), LOG_WARNING)
    return []
  except Exception as exc:
    _log('lucky unknown candidate search unexpected failure for %s: %s' % (normalized_language, exc), LOG_WARNING)
    return []

  unknown_candidates = []
  seen_release = set()
  for item in results:
    tier = _as_text(item.get('sync_tier', 'unknown')).lower()
    if tier in ['exact', 'likely']:
      continue

    release_name = _as_text(item.get('release_name', '')).strip()
    provider_name = _as_text(item.get('provider', '')).strip()
    dedupe_key = '%s::%s' % (provider_name.lower(), release_name.lower())
    if dedupe_key in seen_release:
      continue
    seen_release.add(dedupe_key)

    candidate = dict(item)
    unknown_eval = _unknown_match_likelihood_score(
      video_basename,
      release_name,
      similarity_score=int(candidate.get('similarity_score', 0))
    )
    candidate['unknown_match_likelihood'] = int(unknown_eval.get('score', 0))
    candidate['risk_reason'] = _build_unknown_match_risk_reason(video_basename, candidate)
    unknown_candidates.append(candidate)

  unknown_candidates.sort(
    key=lambda item: (
      -int(item.get('unknown_match_likelihood', 0)),
      -int(item.get('similarity_score', 0)),
      -int(item.get('provider_score', 0)),
      _as_text(item.get('release_name', '')).lower()
    )
  )

  if max_candidates < 1:
    max_candidates = 1
  return unknown_candidates[:max_candidates]

def _prompt_lucky_unknown_candidate(slot_label, candidates, video_basename=''):
  if not candidates:
    return None

  enriched = []
  for item in candidates:
    candidate = dict(item)
    risk_reason = _as_text(candidate.get('risk_reason', '')).strip() or __language__(33284)
    candidate['display_extra_line'] = risk_reason
    enriched.append(candidate)

  try:
    selected_index = _select_download_result_with_custom_window(
      enriched,
      _as_text(slot_label) or '?',
      _as_text(video_basename) or ''
    )
  except Exception as exc:
    _log('lucky unknown picker failed, falling back to simple selector (%s)' % (exc), LOG_WARNING)
    selected_index = -1

  if selected_index is None:
    return None

  try:
    selected_index = int(selected_index)
  except Exception:
    _log('lucky unknown picker returned invalid index: %s' % (_as_text(selected_index)), LOG_WARNING)
    return None

  if selected_index < 0 or selected_index >= len(enriched):
    return None
  return enriched[selected_index]

def _download_lucky_selected_candidate(video_dir, video_basename, slot, selected_candidate):
  if not selected_candidate:
    return ''
  context = _build_download_context(video_dir, video_basename)
  language_code = _canonicalize_language_code(slot.get('code', ''))
  if not language_code:
    return ''
  try:
    target_path = _write_download_payload_to_target(context, language_code, selected_candidate)
    return target_path
  except Exception as exc:
    _log(
      'lucky risky candidate download failed: language=%s release=%s provider=%s error=%s'
      % (
        language_code,
        _as_text(selected_candidate.get('release_name', 'subtitle')),
        _as_text(selected_candidate.get('provider', 'provider')),
        exc
      ),
      LOG_WARNING
    )
    _notify(__language__(33193), NOTIFY_WARNING)
    return ''

def _offer_lucky_recovery_actions(missing_text):
  missing_label = _as_text(missing_text).strip() or 'subtitle'
  selected = __msg_box__.select(
    __language__(33297) % (missing_label),
    [
      __language__(33298),
      __language__(33299),
      __language__(33133),
    ]
  )
  if selected == 0:
    _run_manual_download_action()
  elif selected == 1:
    _run_manual_translation_action()

def _find_lucky_english_reference(
  video_dir,
  video_basename,
  request_delay_seconds=0.0,
  allow_unknown_download=False,
  allow_unknown_local=False,
  progress_callback=None
):
  result = {
    'path': '',
    'tier': '',
    'origin': '',
  }
  if not video_dir or not video_basename:
    return result

  exact_local = _pick_best_exact_local_language_match(video_dir, video_basename, 'en')
  if exact_local:
    result['path'] = exact_local
    result['tier'] = 'exact'
    result['origin'] = 'local_exact'
    return result

  if _is_lucky_allow_english_likely():
    likely_local = _pick_best_local_likely_language_match(video_dir, video_basename, 'en')
    if likely_local:
      result['path'] = likely_local
      result['tier'] = 'likely'
      result['origin'] = 'local_likely'
      return result

  if _is_lucky_download_enabled():
    required_tiers = ['exact']
    if _is_lucky_allow_english_likely():
      required_tiers.append('likely')
    if allow_unknown_download:
      required_tiers.append('unknown')

    downloaded = _download_best_result_for_language(
      video_dir,
      video_basename,
      'en',
      language_label='English',
      required_tiers=required_tiers,
      fallback_to_top=False,
      notify_errors=False,
      max_write_attempts=4,
      request_delay_seconds=request_delay_seconds,
      max_provider_attempts=2,
      retry_delay_seconds=0.95,
      progress_callback=progress_callback,
      progress_label='English reference'
    )
    if downloaded.get('path'):
      selected_result = downloaded.get('result') or {}
      selected_tier = _as_text(selected_result.get('sync_tier', 'unknown')).lower()
      if selected_tier not in ['exact', 'likely', 'unknown']:
        selected_tier = 'unknown'
      result['path'] = downloaded['path']
      result['tier'] = selected_tier
      result['origin'] = 'download_%s' % (selected_tier)
      return result

  if allow_unknown_local:
    local_any = _pick_best_local_any_language_match(video_dir, 'en')
    if local_any:
      result['path'] = local_any
      result['tier'] = 'unknown'
      result['origin'] = 'local_unknown'
      return result

  return result

def _assess_subtitle_pair_mismatch(reference_path, target_path):
  reference_subs = None
  target_subs = None
  reference_local = ''
  target_local = ''
  try:
    reference_subs, reference_local = _load_subtitle_for_processing(reference_path)
    target_subs, target_local = _load_subtitle_for_processing(target_path)
    return smartsync.assess_pair(reference_subs, target_subs)
  except Exception as exc:
    _log('lucky mismatch assessment failed: ref=%s target=%s error=%s' % (reference_path, target_path, exc), LOG_WARNING)
    return {}
  finally:
    if reference_local:
      xbmcvfs.delete(reference_local)
    if target_local:
      xbmcvfs.delete(target_local)

def _run_lucky_smartsync_to_reference(reference_path, target_path, force_apply=False):
  response = {
    'applied': False,
    'path': target_path,
    'persisted': False,
    'temp_paths': [],
  }
  if not reference_path or not target_path:
    return response
  if reference_path.lower() == target_path.lower():
    return response

  mismatch = _assess_subtitle_pair_mismatch(reference_path, target_path)
  if not force_apply and not mismatch.get('likely_mismatch'):
    _log('lucky smart sync skipped: mismatch not detected (ref=%s target=%s)' % (reference_path, target_path), LOG_INFO)
    return response

  try:
    local_result = _run_smart_sync_local(reference_path, target_path)
    sync_apply = _apply_synced_subtitle_to_target(target_path, local_result['synced_subs'])
  except Exception as exc:
    _log('lucky smart sync failed: ref=%s target=%s error=%s' % (reference_path, target_path, exc), LOG_WARNING)
    return response

  response['applied'] = True
  response['path'] = sync_apply.get('play_path') or target_path
  response['persisted'] = bool(sync_apply.get('persisted'))
  if sync_apply.get('temp_path'):
    response['temp_paths'].append(sync_apply.get('temp_path'))
  _log('lucky smart sync applied: ref=%s target=%s output=%s persisted=%s' % (reference_path, target_path, response['path'], response['persisted']), LOG_INFO)
  return response

def _run_download_for_language(video_dir, video_basename, language_code, language_label=''):
  if not video_dir or not video_basename:
    _notify(__language__(33175), NOTIFY_WARNING)
    return None

  context = _build_download_context(video_dir, video_basename)
  if not language_label:
    language_label = (language_code or '').upper()

  progress = xbmcgui.DialogProgress()
  try:
    search_line = __language__(33187) % (language_label)
    progress.create(__scriptname__, search_line)
    provider_names = _configured_download_provider_names()
    if len(provider_names) > 0:
      _progress_update(progress, 5, search_line, '%s: %s' % (__language__(33227), ' | '.join(provider_names)))
    results = _search_download_results(context, language_code)
  except RuntimeError as exc:
    _close_progress(progress)
    _notify(_as_text(exc), NOTIFY_WARNING)
    return None
  except Exception as exc:
    _close_progress(progress)
    _notify(__language__(33193), NOTIFY_WARNING)
    _log('download search failed for %s (%s)' % (language_code, exc), LOG_WARNING)
    return None

  _close_progress(progress)
  if len(results) == 0:
    _notify(__language__(33177) % (language_label), NOTIFY_WARNING)
    return None

  _notify_top_download_candidate(results)
  selected = _select_download_result_with_custom_window(results, language_label, video_basename)

  if selected is None or selected < 0 or selected >= len(results):
    return None

  selected_result = results[selected]
  progress = xbmcgui.DialogProgress()
  try:
    progress.create(__scriptname__, __language__(33191))
    target_path = _write_download_payload_to_target(context, language_code, selected_result)
  except RuntimeError as exc:
    _close_progress(progress)
    _notify(_as_text(exc), NOTIFY_WARNING)
    return None
  except Exception as exc:
    _close_progress(progress)
    _notify(__language__(33193), NOTIFY_WARNING)
    _log('download write failed (%s)' % (exc), LOG_WARNING)
    return None

  _close_progress(progress)
  _notify(__language__(33190) % (os.path.basename(target_path)), NOTIFY_INFO)
  _log('downloaded subtitle: language=%s path=%s provider=%s' % (language_code, target_path, selected_result.get('provider')), LOG_INFO)
  return target_path

def _open_manual_download_results_browser(video_dir, video_basename, language_code, language_label):
  context = _build_download_context(video_dir, video_basename)
  if not language_label:
    language_label = (language_code or '').upper()

  progress = xbmcgui.DialogProgress()
  try:
    search_line = __language__(33187) % (language_label)
    progress.create(__scriptname__, search_line)
    provider_names = _configured_download_provider_names()
    if len(provider_names) > 0:
      _progress_update(progress, 5, search_line, '%s: %s' % (__language__(33227), ' | '.join(provider_names)))
    results = _search_download_results(context, language_code)
  except RuntimeError as exc:
    _close_progress(progress)
    _notify(_as_text(exc), NOTIFY_WARNING)
    return
  except Exception as exc:
    _close_progress(progress)
    _notify(__language__(33193), NOTIFY_WARNING)
    _log('manual download search failed for %s (%s)' % (language_code, exc), LOG_WARNING)
    return

  _close_progress(progress)
  if len(results) == 0:
    _notify(__language__(33177) % (language_label), NOTIFY_WARNING)
    return

  _notify_top_download_candidate(results)

  cache_token = str(uuid.uuid4())
  cache_payload = {
    'token': cache_token,
    'context': {
      'video_dir': video_dir,
      'video_basename': video_basename,
      'language_code': language_code,
      'language_label': language_label,
    },
    'results': [_serialize_download_result_for_cache(item) for item in results],
  }
  if not _save_download_results_cache(cache_payload):
    selected = _select_download_result_dialog_select(results, language_label)
    if selected is None or selected < 0 or selected >= len(results):
      return
    selected_result = results[selected]
    progress = xbmcgui.DialogProgress()
    try:
      progress.create(__scriptname__, __language__(33191))
      target_path = _write_download_payload_to_target(context, language_code, selected_result)
    except RuntimeError as exc:
      _close_progress(progress)
      _notify(_as_text(exc), NOTIFY_WARNING)
      return
    except Exception as exc:
      _close_progress(progress)
      _notify(__language__(33193), NOTIFY_WARNING)
      _log('manual download fallback write failed (%s)' % (exc), LOG_WARNING)
      return
    _close_progress(progress)
    _notify(__language__(33190) % (os.path.basename(target_path)), NOTIFY_INFO)
    _log('manual download fallback selected: language=%s path=%s provider=%s' % (language_code, target_path, selected_result.get('provider')), LOG_INFO)
    Download(target_path)
    return

  handle = int(sys.argv[1])
  for index, item in enumerate(results):
    url = 'plugin://%s/?action=downloadpick&token=%s&index=%d' % (__scriptid__, cache_token, index)
    listitem = _build_download_browser_listitem(item)
    xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=listitem, isFolder=False)

  try:
    xbmcplugin.setContent(handle, 'files')
  except Exception:
    pass

def _run_manual_download_action():
  if not _is_subtitle_download_enabled():
    _notify(__language__(33172), NOTIFY_WARNING)
    return

  video_dir, video_basename = _current_video_context()
  if not video_dir or not video_basename:
    _notify(__language__(33175), NOTIFY_WARNING)
    return

  language_code, language_label = _select_download_language()
  if not language_code:
    return

  downloaded_path = _run_download_for_language(video_dir, video_basename, language_code, language_label)
  if not downloaded_path:
    return
  Download(downloaded_path)

def _run_manual_download_pick_action():
  token = _as_text(params.get('token', '')).strip()
  index_raw = _as_text(params.get('index', '')).strip()
  if not token or not index_raw:
    _notify(__language__(33193), NOTIFY_WARNING)
    return

  try:
    result_index = int(index_raw)
  except Exception:
    _notify(__language__(33193), NOTIFY_WARNING)
    return

  cache_payload = _load_download_results_cache(token)
  if cache_payload is None:
    _notify(__language__(33193), NOTIFY_WARNING)
    return

  context = cache_payload.get('context') or {}
  results = cache_payload.get('results') or []
  if result_index < 0 or result_index >= len(results):
    _notify(__language__(33193), NOTIFY_WARNING)
    return

  selected_result = results[result_index]
  language_code = _canonicalize_language_code(context.get('language_code', '')) or _canonicalize_language_code(selected_result.get('language', ''))
  if not language_code:
    _notify(__language__(33194), NOTIFY_WARNING)
    return

  progress = xbmcgui.DialogProgress()
  try:
    progress.create(__scriptname__, __language__(33191))
    target_path = _write_download_payload_to_target(context, language_code, selected_result)
  except RuntimeError as exc:
    _close_progress(progress)
    _notify(_as_text(exc), NOTIFY_WARNING)
    return
  except Exception as exc:
    _close_progress(progress)
    _notify(__language__(33193), NOTIFY_WARNING)
    _log('manual download write failed (%s)' % (exc), LOG_WARNING)
    return

  _close_progress(progress)
  _notify(__language__(33190) % (os.path.basename(target_path)), NOTIFY_INFO)
  _log('manual download selected: language=%s path=%s provider=%s' % (language_code, target_path, selected_result.get('provider')), LOG_INFO)
  Download(target_path)

def _refresh_automatch_mode_from_slots(automatch):
  subtitle1 = automatch.get('subtitle1')
  subtitle2 = automatch.get('subtitle2')
  if subtitle1 and subtitle2 and subtitle1.lower() != subtitle2.lower():
    automatch['mode'] = 'full'
    automatch['missing'] = ''
    return automatch
  if subtitle1 and not subtitle2:
    automatch['mode'] = 'partial'
    automatch['missing'] = 'subtitle2'
    automatch['found_label'] = automatch.get('language1_label', '')
    automatch['missing_label'] = automatch.get('language2_label', '')
    return automatch
  if subtitle2 and not subtitle1:
    automatch['mode'] = 'partial'
    automatch['missing'] = 'subtitle1'
    automatch['found_label'] = automatch.get('language2_label', '')
    automatch['missing_label'] = automatch.get('language1_label', '')
    return automatch

  automatch['mode'] = 'none'
  automatch['missing'] = ''
  return automatch

def _attempt_auto_download_for_automatch(automatch, video_dir, video_basename):
  result = {
    'applied': False,
    'subtitle1': automatch.get('subtitle1'),
    'subtitle2': automatch.get('subtitle2'),
  }
  if not _is_subtitle_download_enabled():
    return result
  if not _is_download_auto_on_missing():
    return result
  if automatch.get('mode') not in ['partial', 'none']:
    return result
  if not video_dir or not video_basename:
    _notify(__language__(33175), NOTIFY_WARNING)
    return result

  targets = _build_translation_targets_for_automatch(automatch)
  if len(targets) == 0:
    return result

  selected = __msg_box__.select(__language__(33179), [__language__(33188), __language__(33189)])
  if selected != 1:
    _notify(__language__(33184), NOTIFY_INFO)
    return result

  for target in targets:
    downloaded_path = _run_download_for_language(video_dir, video_basename, target['code'], target['label'])
    if not downloaded_path:
      continue
    result['applied'] = True
    if target['slot'] == 'subtitle1':
      result['subtitle1'] = downloaded_path
    else:
      result['subtitle2'] = downloaded_path
    _notify(__language__(33183) % (target['label']), NOTIFY_INFO)

  if result['applied']:
    _notify(__language__(33195), NOTIFY_INFO)
  return result

def _match_subtitle_name(subtitle_name, video_basename, language_code, strict):
  name_lower = subtitle_name.lower()
  base_lower = video_basename.lower()

  if not name_lower.endswith('.srt'):
    return False
  if not name_lower.startswith(base_lower):
    return False

  name_without_ext = subtitle_name[:-4]
  if len(name_without_ext) <= len(video_basename):
    return False

  tail = name_without_ext[len(video_basename):]
  if not tail:
    return False
  if tail[0] not in ['.', '-', '_']:
    return False

  tail_lower = tail.lower()
  return _language_tail_matches(tail_lower, language_code, strict)

def _find_subtitle_matches(video_dir, video_basename, language_code, strict):
  if not video_dir or not video_basename or not language_code:
    return []

  try:
    files = xbmcvfs.listdir(video_dir)[1]
  except Exception:
    return []

  matches = []
  seen = {}
  for subtitle_name in files:
    if _is_generated_subtitle_name(subtitle_name):
      continue
    if _match_subtitle_name(subtitle_name, video_basename, language_code, strict):
      full_path = os.path.join(video_dir, subtitle_name)
      lower_key = full_path.lower()
      if lower_key not in seen:
        seen[lower_key] = True
        matches.append(full_path)

  return matches

def _auto_match_subtitles(video_dir, video_basename):
  result = {
      'mode': 'disabled',
      'subtitle1': None,
      'subtitle2': None,
      'found_label': '',
      'missing_label': '',
      'missing': '',
      'language1_label': _language_label('preferred_language_1'),
      'language2_label': _language_label('preferred_language_2'),
  }

  language1 = _parse_language_code('preferred_language_1')
  language2 = _parse_language_code('preferred_language_2')
  if not video_dir or not video_basename or not language1 or not language2 or language1 == language2:
    _log('auto-match disabled: video_dir=%s base=%s lang1=%s lang2=%s' % (video_dir, video_basename, language1, language2), LOG_DEBUG)
    return result

  strict = _get_match_strictness() == 'strict'
  matches1 = _find_subtitle_matches(video_dir, video_basename, language1, strict)
  matches2 = _find_subtitle_matches(video_dir, video_basename, language2, strict)
  _log('auto-match candidates: strict=%s lang1=%s count1=%d lang2=%s count2=%d' % (strict, language1, len(matches1), language2, len(matches2)), LOG_DEBUG)

  if len(matches1) == 1 and len(matches2) == 1 and matches1[0] != matches2[0]:
    result['mode'] = 'full'
    result['subtitle1'] = matches1[0]
    result['subtitle2'] = matches2[0]
    _log('auto-match full: %s | %s' % (result['subtitle1'], result['subtitle2']), LOG_INFO)
    return result

  if len(matches1) == 1 and len(matches2) == 0:
    result['mode'] = 'partial'
    result['subtitle1'] = matches1[0]
    result['found_label'] = _language_label('preferred_language_1')
    result['missing_label'] = _language_label('preferred_language_2')
    result['missing'] = 'subtitle2'
    _log('auto-match partial: found subtitle1=%s missing subtitle2' % (result['subtitle1']), LOG_INFO)
    return result

  if len(matches1) == 0 and len(matches2) == 1:
    result['mode'] = 'partial'
    result['subtitle2'] = matches2[0]
    result['found_label'] = _language_label('preferred_language_2')
    result['missing_label'] = _language_label('preferred_language_1')
    result['missing'] = 'subtitle1'
    _log('auto-match partial: found subtitle2=%s missing subtitle1' % (result['subtitle2']), LOG_INFO)
    return result

  if len(matches1) > 1 or len(matches2) > 1 or (len(matches1) == 1 and len(matches2) == 1 and matches1[0] == matches2[0]):
    result['mode'] = 'ambiguous'
    _log('auto-match ambiguous: count1=%d count2=%d' % (len(matches1), len(matches2)), LOG_WARNING)
    return result

  result['mode'] = 'none'
  _log('auto-match none: no usable subtitle match', LOG_INFO)
  return result

def _browse_for_subtitle(title, browse_dir):
  if not _is_usable_browse_dir(browse_dir):
    browse_dir = ''

  show_prepicker = True
  while True:
    if show_prepicker and _is_usable_browse_dir(browse_dir):
      prepicker_entries = _build_subtitle_prepicker_entries(browse_dir)
      if len(prepicker_entries) > 0:
        options = []
        for label, _ in prepicker_entries:
          options.append(label)
        options.append(__language__(33132))
        options.append(__language__(33133))

        selected = __msg_box__.select(title, options)
        if selected is None or selected < 0 or selected == len(options) - 1:
          _log('subtitle pre-picker cancelled: %s' % (title), LOG_DEBUG)
          return None, browse_dir

        if selected < len(prepicker_entries):
          subtitle_path = prepicker_entries[selected][1]
          _log('subtitle selected from pre-picker: %s' % (subtitle_path), LOG_DEBUG)
          return subtitle_path, os.path.dirname(subtitle_path)

        show_prepicker = False

    subtitlefile = __msg_box__.browse(1, title, "video", ".zip|.srt", False, False, browse_dir, False)
    if subtitlefile is None or subtitlefile == '' or subtitlefile == browse_dir:
      return None, browse_dir

    selected_dir = os.path.dirname(subtitlefile)
    if subtitlefile.lower().endswith('.zip'):
      extracted_file = unzip(subtitlefile, [ ".srt" ])
      if extracted_file is None:
        browse_dir = selected_dir
        show_prepicker = True
        continue
      return extracted_file, selected_dir

    return subtitlefile, selected_dir

def _remember_last_used_dir(path):
  if not _is_usable_browse_dir(path):
    return

  try:
    __addon__.setSetting('last_used_subtitle_dir', path)
  except Exception:
    pass

def _prepare_and_merge_subtitles(subs):
  substemp = []
  merged_temp = ''
  try:
    for sub in subs:
      # Python can fail to read subtitles from special Kodi locations (for example smb://).
      # Copy each selected subtitle to a local temporary file first.
      subtemp = os.path.join(__temp__, "%s" % (str(uuid.uuid4())))
      if not xbmcvfs.copy(sub, subtemp):
        raise RuntimeError(__language__(33043))
      substemp.append(subtemp)
    merged_temp = mergesubs(substemp)

    merged_output = _build_merged_ass_output_path(subs[0])
    if xbmcvfs.exists(merged_output):
      xbmcvfs.delete(merged_output)

    if xbmcvfs.copy(merged_temp, merged_output):
      _set_writable_permissions(merged_output, is_directory=False)
      xbmcvfs.delete(merged_temp)
      _log('merged subtitles: count=%d output=%s' % (len(subs), merged_output), LOG_INFO)
      return merged_output

    _log('merged subtitles copy to DualSubtitles failed, using temp output=%s' % (merged_temp), LOG_WARNING)
    return merged_temp
  finally:
    for subtemp in substemp:
      xbmcvfs.delete(subtemp)

def _enforce_dual_bottom_stack_visibility(ass_path):
  """Ensure dual ASS subtitles are visible together near the bottom.

  Some skins/overlays make top-aligned lines hard to see. For dual output we
  force top-style to bottom alignment with a higher vertical margin so both
  languages remain visible at once.
  """
  path = _as_text(ass_path).strip()
  if not path or not path.lower().endswith('.ass'):
    return
  if not xbmcvfs.exists(path):
    return

  try:
    with open(path, 'rb') as handle:
      raw = handle.read()
  except Exception as exc:
    _log('dual ass visibility patch read failed (%s): %s' % (path, exc), LOG_WARNING)
    return

  text = _as_text(raw)
  lines = text.splitlines()
  changed = False
  patched = []

  for line in lines:
    if line.startswith('Style: top-style,'):
      prefix, body = line.split(': ', 1)
      fields = body.split(',')
      if len(fields) >= 23:
        fields[18] = '2'  # Alignment -> bottom-center
        try:
          margin_v = int(_as_text(fields[21]).strip() or '0')
        except Exception:
          margin_v = 0
        if margin_v < 56:
          fields[21] = '56'
        line = '%s: %s' % (prefix, ','.join(fields))
        changed = True
    patched.append(line)

  if not changed:
    return

  try:
    with open(path, 'wb') as handle:
      handle.write(_to_utf8_bytes('\n'.join(patched) + '\n'))
    _log('dual ass visibility patch applied: %s' % (path), LOG_INFO)
  except Exception as exc:
    _log('dual ass visibility patch write failed (%s): %s' % (path, exc), LOG_WARNING)

def _pick_subtitles_with_settings(start_dir, apply_no_match_behavior=False, force_manual_both=False):
  second_required = _is_second_subtitle_required()
  behavior = 'manual_both'
  if apply_no_match_behavior:
    behavior = _get_no_match_behavior()
  if force_manual_both:
    behavior = 'manual_both'

  if behavior == 'stop':
    _log('no-match behavior=stop; aborting manual picker', LOG_INFO)
    _notify(__language__(33039), NOTIFY_WARNING)
    return None, None, ''

  _log('manual picker behavior=%s second_required=%s start_dir=%s' % (behavior, second_required, start_dir), LOG_DEBUG)
  subtitle1, subtitle1_dir = _browse_for_subtitle(__language__(33005), start_dir)
  if subtitle1 is None:
    _log('manual picker cancelled on first subtitle', LOG_DEBUG)
    return None, None, ''

  if behavior == 'first_only' and not second_required:
    _log('manual picker using first subtitle only: %s' % (subtitle1), LOG_INFO)
    return subtitle1, None, subtitle1_dir

  title2 = __language__(33006) + ' ' + __language__(33009)
  subtitle2, _ = _browse_for_subtitle(title2, subtitle1_dir)
  if subtitle2 is None and second_required:
    _log('manual picker cancelled second subtitle while required', LOG_WARNING)
    _notify(__language__(33040), NOTIFY_WARNING)
    return None, None, ''

  _log('manual picker selected subtitle1=%s subtitle2=%s' % (subtitle1, subtitle2), LOG_INFO)
  return subtitle1, subtitle2, subtitle1_dir

def _finalize_selected_subtitle_paths(
  subtitle1,
  subtitle2,
  subtitle1_dir='',
  smart_sync_temp_files=None,
  show_notifications=True,
  register_download_item=True
):
  if subtitle1 is None:
    return False

  if smart_sync_temp_files is None:
    smart_sync_temp_files = []

  if not subtitle1_dir:
    subtitle1_dir = os.path.dirname(subtitle1)
  _remember_last_used_dir(subtitle1_dir)
  _log('selected subtitles before merge: subtitle1=%s subtitle2=%s' % (subtitle1, subtitle2), LOG_INFO)

  subs = [subtitle1]
  if subtitle2 is not None:
    subs.append(subtitle2)

  try:
    finalfile = _prepare_and_merge_subtitles(subs)
  except Exception as exc:
    _log('subtitle merge failed: %s' % (exc), LOG_ERROR)
    if show_notifications:
      _notify(__language__(33042), NOTIFY_ERROR)
    __msg_box__.ok(__language__(32531), str(exc))
    return False
  finally:
    for temp_sync_path in smart_sync_temp_files:
      try:
        if temp_sync_path and temp_sync_path.startswith(__temp__):
          xbmcvfs.delete(temp_sync_path)
      except Exception:
        pass

  if register_download_item:
    Download(finalfile)
  if len(subs) > 1:
    _enforce_dual_bottom_stack_visibility(finalfile)
  if not _apply_subtitle_to_player_now(finalfile):
    # Retry once shortly after Kodi finishes plugin callback handling.
    xbmc.sleep(250)
    _apply_subtitle_to_player_now(finalfile)
  if len(subs) > 1:
    xbmc.sleep(180)
    _refresh_active_subtitle_renderer(finalfile)
  if show_notifications:
    if len(subs) > 1:
      _notify(__language__(33041), NOTIFY_INFO)
    else:
      _notify(__language__(33045), NOTIFY_INFO)
  return True

def _build_lucky_target_slots():
  language1 = _parse_language_code('preferred_language_1')
  language2 = _parse_language_code('preferred_language_2')
  if not language1 or not language2 or language1 == language2:
    return []

  return [
    {
      'slot': 'subtitle1',
      'code': language1,
      'label': _language_label('preferred_language_1'),
      'path': '',
      'origin': 'missing',
    },
    {
      'slot': 'subtitle2',
      'code': language2,
      'label': _language_label('preferred_language_2'),
      'path': '',
      'origin': 'missing',
    }
  ]

def _build_lucky_single_target_slot():
  target_code = _parse_language_code('lucky_single_language')
  if not target_code:
    target_code = _parse_language_code('preferred_language_1')
  if not target_code:
    return {}

  target_label = _language_display_name(target_code)
  if not target_label:
    target_label = target_code.upper()

  return {
    'slot': 'subtitle1',
    'code': target_code,
    'label': target_label,
    'path': '',
    'origin': 'missing',
  }

def _lucky_missing_slots(slots):
  missing = []
  for slot in slots:
    if not slot.get('path'):
      missing.append(slot)
  return missing

def _pick_lucky_translation_source(video_dir, video_basename, english_reference_path, slots, exclude_source_paths=None, english_only=False):
  excluded = set()
  for item in exclude_source_paths or []:
    value = _as_text(item).strip()
    if value:
      excluded.add(os.path.normcase(os.path.normpath(value)))

  def _is_excluded(path):
    value = _as_text(path).strip()
    if not value:
      return False
    try:
      normalized = os.path.normcase(os.path.normpath(value))
    except Exception:
      normalized = value.lower()
    return normalized in excluded

  if english_reference_path and xbmcvfs.exists(english_reference_path) and not _is_excluded(english_reference_path):
    return english_reference_path

  local_english_exact = _pick_best_exact_local_language_match(video_dir, video_basename, 'en')
  if local_english_exact and not _is_excluded(local_english_exact):
    return local_english_exact

  local_english_likely = _pick_best_local_likely_language_match(video_dir, video_basename, 'en')
  if local_english_likely and not _is_excluded(local_english_likely):
    return local_english_likely

  if english_only:
    for slot in slots or []:
      slot_path = _as_text(slot.get('path', '')).strip()
      if not slot_path or _is_excluded(slot_path):
        continue
      detected_code = _guess_language_code_from_path(slot_path)
      if detected_code == 'en':
        return slot_path
    return ''

  for slot in slots:
    slot_path = slot.get('path')
    if slot_path and not _is_excluded(slot_path):
      return slot_path

  local_files = _list_srt_files(video_dir, include_generated=False)
  for item in local_files:
    if not _is_excluded(item):
      return item
  return ''

def _create_lucky_progress():
  progress = None
  try:
    progress = xbmcgui.DialogProgress()
    progress.create(__language__(33230), __language__(33236))
  except Exception:
    progress = None
  return progress

def _update_lucky_progress(progress, percent, line1='', line2=''):
  _progress_update(progress, percent, line1, line2)
  if progress is None:
    return True
  try:
    if progress.iscanceled():
      return False
  except Exception:
    pass
  return True

def _show_lucky_center_summary(title, lines):
  cleaned = []
  for line in lines or []:
    text = _as_text(line).strip()
    if text:
      if len(text) > 120:
        text = '%s...' % (text[:117])
      cleaned.append(text)
  if len(cleaned) > 8:
    cleaned = [cleaned[0]] + cleaned[-7:]
  if len(cleaned) == 0:
    return
  summary_text = '[CR]'.join(cleaned)
  try:
    player = xbmc.Player()
    if player.isPlayingVideo():
      # Avoid modal dialogs during playback; they can feel like flow aborts.
      _notify(summary_text, NOTIFY_INFO, timeout=5500)
      return
  except Exception:
    pass
  try:
    __msg_box__.ok(_as_text(title) or __language__(33230), summary_text)
  except Exception:
    pass

def _lucky_slot_label(slot):
  label = _as_text((slot or {}).get('label', (slot or {}).get('code', 'Target'))).strip()
  if label:
    return label
  return 'Target'

def _build_lucky_single_result_summary(slot, english_preview_tested=False, english_preview_in_sync=False, smartsync_applied=False, overall_success=True):
  lines = []
  if english_preview_tested:
    lines.append('English preview: %s' % ('Success' if english_preview_in_sync else 'Failed'))
  lines.append('%s subtitle: %s' % (_lucky_slot_label(slot), 'Success' if (slot or {}).get('path') else 'Failed'))
  if smartsync_applied:
    lines.append('SmartSync: Success')
  lines.append('Lucky flow: %s' % ('Success' if overall_success else 'Failed'))
  return lines

def _build_lucky_dual_result_summary(slots, english_preview_tested=False, english_preview_in_sync=False, smartsync_applied=False, overall_success=True):
  lines = []
  if english_preview_tested:
    lines.append('English preview: %s' % ('Success' if english_preview_in_sync else 'Failed'))
  for slot in slots or []:
    lines.append('%s subtitle: %s' % (_lucky_slot_label(slot), 'Success' if slot.get('path') else 'Failed'))
  if smartsync_applied:
    lines.append('SmartSync: Success')
  lines.append('Lucky flow: %s' % ('Success' if overall_success else 'Failed'))
  return lines

def _pause_lucky_background_playback():
  player = xbmc.Player()
  try:
    if not player.isPlayingVideo():
      return False
  except Exception:
    return False

  try:
    if xbmc.getCondVisibility('Player.Paused'):
      return False
  except Exception:
    pass

  try:
    player.pause()
    xbmc.sleep(180)
    _log('lucky: playback paused for background processing', LOG_INFO)
    return True
  except Exception as exc:
    _log('lucky: failed to pause playback for background processing (%s)' % (exc), LOG_WARNING)
    return False

def _pause_playback_for_lucky_step():
  state = {
    'can_resume': False,
    'was_playing_video': False,
    'was_paused': False,
  }

  player = xbmc.Player()
  try:
    state['was_playing_video'] = bool(player.isPlayingVideo())
  except Exception:
    return state

  if not state['was_playing_video']:
    return state

  try:
    state['was_paused'] = bool(xbmc.getCondVisibility('Player.Paused'))
  except Exception:
    state['was_paused'] = False

  if state['was_paused']:
    return state

  try:
    player.pause()
    xbmc.sleep(180)
    state['can_resume'] = True
    _log('lucky translation: playback paused for AI translation step', LOG_INFO)
  except Exception as exc:
    _log('lucky translation: failed to pause playback (%s)' % (exc), LOG_WARNING)

  return state

def _resume_playback_for_lucky_step(state):
  if not state or not state.get('can_resume'):
    return

  player = xbmc.Player()
  try:
    if not player.isPlayingVideo():
      return
  except Exception:
    return

  try:
    is_paused_now = bool(xbmc.getCondVisibility('Player.Paused'))
  except Exception:
    is_paused_now = False

  if not is_paused_now:
    return

  try:
    player.pause()
    xbmc.sleep(180)
    _log('lucky translation: playback resumed after AI translation step', LOG_INFO)
  except Exception as exc:
    _log('lucky translation: failed to resume playback (%s)' % (exc), LOG_WARNING)

def _normalize_subtitle_preview_text(text):
  normalized = _as_text(text)
  normalized = normalized.replace('\\N', ' ')
  normalized = normalized.replace('\n', ' ')
  normalized = re.sub(r'\{\\[^}]*\}', ' ', normalized)
  normalized = re.sub(r'<[^>]+>', ' ', normalized)
  normalized = re.sub(r'\[[^\]]+\]', ' ', normalized)
  normalized = re.sub(r'\s+', ' ', normalized).strip()
  return normalized

def _first_spoken_subtitle_start_ms(subtitle_path):
  local_copy = ''
  try:
    subtitle_data, local_copy = _load_subtitle_for_processing(subtitle_path)
    for event in getattr(subtitle_data, 'events', []):
      text = _normalize_subtitle_preview_text(getattr(event, 'text', ''))
      if not text:
        continue
      # Skip non-spoken cues: music symbols, sound effects, and punctuation-only lines.
      stripped = re.sub(r'[\u266a\u266b\u266c\u266d\u266e\u266f\u2669#*\-\s]', '', text)
      if not stripped:
        continue
      if re.match(r'^[\W_]+$', text):
        continue
      try:
        return int(max(0, getattr(event, 'start', 0)))
      except Exception:
        return 0
  except Exception as exc:
    _log('lucky english preview parse failed: %s' % (exc), LOG_WARNING)
  finally:
    try:
      if local_copy and xbmcvfs.exists(local_copy):
        xbmcvfs.delete(local_copy)
    except Exception:
      pass
  return 0

def _capture_lucky_preview_state():
  state = {
    'valid': False,
    'play_time_seconds': 0.0,
    'subtitle_path': '',
    'subtitle_visible': None,
    'was_fullscreen_video': False,
  }

  player = xbmc.Player()
  try:
    if not player.isPlayingVideo():
      return state
  except Exception:
    return state

  try:
    state['play_time_seconds'] = float(max(0.0, player.getTime()))
  except Exception:
    state['play_time_seconds'] = 0.0

  try:
    subtitle_path = _as_text(xbmc.getInfoLabel('VideoPlayer.SubtitlesFilename')).strip()
    if not subtitle_path:
      subtitle_path = _as_text(xbmc.getInfoLabel('VideoPlayer.SubtitlesFile')).strip()
    state['subtitle_path'] = subtitle_path
  except Exception:
    state['subtitle_path'] = ''

  try:
    state['subtitle_visible'] = bool(xbmc.getCondVisibility('VideoPlayer.SubtitlesEnabled'))
  except Exception:
    state['subtitle_visible'] = None

  try:
    state['was_fullscreen_video'] = bool(xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'))
  except Exception:
    state['was_fullscreen_video'] = False

  state['valid'] = True
  return state

def _restore_lucky_preview_state(state):
  if not state or not state.get('valid'):
    return

  player = xbmc.Player()
  try:
    if not player.isPlayingVideo():
      return
  except Exception:
    return

  play_time = state.get('play_time_seconds')
  try:
    play_time = float(play_time)
  except Exception:
    play_time = None

  if play_time is not None and play_time >= 0.0:
    try:
      player.seekTime(play_time)
    except Exception as exc:
      _log('lucky english preview restore seek failed: %s' % (exc), LOG_WARNING)

  subtitle_path = _as_text(state.get('subtitle_path', '')).strip()
  if subtitle_path and xbmcvfs.exists(subtitle_path):
    try:
      player.setSubtitles(subtitle_path)
    except Exception as exc:
      _log('lucky english preview restore subtitles failed: %s' % (exc), LOG_WARNING)

  subtitle_visible = state.get('subtitle_visible')
  if subtitle_visible is not None:
    try:
      player.showSubtitles(bool(subtitle_visible))
    except Exception as exc:
      _log('lucky english preview restore visibility failed: %s' % (exc), LOG_WARNING)

  expected_fullscreen = bool(state.get('was_fullscreen_video'))
  try:
    current_fullscreen = bool(xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'))
  except Exception:
    current_fullscreen = expected_fullscreen

  if expected_fullscreen != current_fullscreen:
    try:
      xbmc.executebuiltin('Action(FullScreen)')
      xbmc.sleep(120)
    except Exception as exc:
      _log('lucky english preview restore fullscreen state failed: %s' % (exc), LOG_WARNING)

def _run_lucky_english_sync_preview(english_reference_path):
  result = {
    'started': False,
    'state': {},
  }
  if not english_reference_path:
    return result

  player = xbmc.Player()
  try:
    if not player.isPlayingVideo():
      return result
  except Exception:
    return result

  result['state'] = _capture_lucky_preview_state()

  first_start_ms = _first_spoken_subtitle_start_ms(english_reference_path)
  seek_seconds = max(0.0, (float(first_start_ms) / 1000.0) - 1.0)

  try:
    player.setSubtitles(english_reference_path)
  except Exception as exc:
    _log('lucky english preview setSubtitles failed: %s' % (exc), LOG_WARNING)

  try:
    player.showSubtitles(True)
  except Exception:
    pass

  try:
    player.seekTime(seek_seconds)
  except Exception as exc:
    _log('lucky english preview seek failed: %s' % (exc), LOG_WARNING)
    return result

  result['started'] = True
  return result

def _focus_video_for_lucky_preview(state=None):
  # Ensure preview is visible on top of subtitle/search dialogs.
  try:
    xbmc.executebuiltin('Dialog.Close(subtitlesearch,true)')
  except Exception:
    pass
  try:
    xbmc.executebuiltin('Dialog.Close(DialogSubtitles.xml,true)')
  except Exception:
    pass
  try:
    xbmc.executebuiltin('Dialog.Close(subtitlesettings,true)')
  except Exception:
    pass
  try:
    xbmc.executebuiltin('Dialog.Close(videoosd,true)')
  except Exception:
    pass
  try:
    xbmc.executebuiltin('Dialog.Close(DialogSettings.xml,true)')
  except Exception:
    pass
  try:
    if not xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
      xbmc.executebuiltin('Action(FullScreen)')
      xbmc.sleep(120)
  except Exception:
    pass

def _let_lucky_preview_play(duration_ms=5000):
  # Let users actually watch subtitle timing in fullscreen before asking.
  _notify(
    'Previewing subtitles for 5 seconds. The sync confirmation will appear after this preview.',
    NOTIFY_INFO,
    timeout=4500
  )
  # Close subtitle dialogs again in case the skin re-opened one.
  _focus_video_for_lucky_preview()
  try:
    xbmc.sleep(max(0, int(duration_ms)))
  except Exception:
    pass

def _show_lucky_english_preview_dialog(english_reference_path):
  # Use a select dialog with 3 explicit options so the UI is identical on
  # every platform (Windows, CoreELEC, LibreELEC, etc.).  The old yesno
  # fallback rendered differently per skin/platform.
  _PREVIEW_OPTIONS = [
    __language__(33271),  # "In Sync"
    __language__(33273),  # "Not In Sync"
    __language__(33133),  # "Cancel"
  ]
  _PREVIEW_MAP = {0: 'sync', 1: 'not_sync', 2: 'cancel'}

  if LuckyPreviewDialog is not None:
    subtitle_name = os.path.basename(_as_text(english_reference_path).strip())
    if not subtitle_name:
      subtitle_name = _as_text(english_reference_path).strip()
    try:
      dialog = LuckyPreviewDialog(
        LUCKY_PREVIEW_XML,
        __cwd__,
        'default',
        '1080i',
        heading=__language__(33230),
        subtitle=subtitle_name,
        message=__language__(33272),
        sync_label=__language__(33271),
        not_sync_label=__language__(33273),
        cancel_label=__language__(33133)
      )
      dialog.doModal()
      selection = _as_text(getattr(dialog, 'result', '')).lower().strip()
      del dialog
      if selection in ('sync', 'not_sync', 'cancel'):
        return selection
    except Exception as exc:
      _log('lucky preview dialog failed (%s), using select fallback' % (exc), LOG_WARNING)

  # Consistent 3-option select dialog — looks identical on all platforms.
  try:
    chosen = __msg_box__.select(__language__(33269), _PREVIEW_OPTIONS)
    return _PREVIEW_MAP.get(chosen, 'cancel')
  except Exception:
    return 'cancel'

def _run_lucky_translate_missing_slots(
  slots,
  video_dir,
  video_basename,
  english_reference_path,
  exclude_source_paths=None,
  require_english_source=False,
  notify=False,
  progress_callback=None
):
  missing_slots = _lucky_missing_slots(slots)
  if len(missing_slots) == 0:
    return
  if not _is_lucky_ai_translate_enabled():
    return

  if not _is_ai_translation_enabled() or not _get_openai_api_key():
    for slot in missing_slots:
      if notify:
        _notify(__language__(33247) % (slot['label']), NOTIFY_WARNING, timeout=4500)
    return

  playback_state = _pause_playback_for_lucky_step()

  source_subtitle = _pick_lucky_translation_source(
    video_dir,
    video_basename,
    english_reference_path,
    slots,
    exclude_source_paths=exclude_source_paths,
    english_only=require_english_source
  )
  if not source_subtitle:
    if require_english_source:
      _log('lucky translation skipped: no English source available for missing targets', LOG_WARNING)
    for slot in missing_slots:
      if notify:
        _notify(__language__(33247) % (slot['label']), NOTIFY_WARNING, timeout=4500)
    _resume_playback_for_lucky_step(playback_state)
    return

  source_language_code = _guess_language_code_from_path(source_subtitle)
  source_label = _language_display_name(source_language_code)
  if not source_label or source_language_code == 'auto':
    source_label = os.path.basename(source_subtitle)

  # Always require explicit user confirmation before AI translation in Lucky flow.
  target_labels = []
  for slot in missing_slots:
    label = _as_text(slot.get('label', slot.get('code', 'target'))).strip()
    if label:
      target_labels.append(label)
  target_text = ', '.join(target_labels) if len(target_labels) > 0 else 'target subtitles'
  prompt = 'Translate with AI from %s to %s?' % (source_label, target_text)
  prompt += '[CR][CR]This sends subtitle text to OpenAI.'
  try:
    confirmed = __msg_box__.yesno(__language__(33230), prompt)
  except Exception:
    confirmed = False
  if not confirmed:
    _log('lucky translation skipped: user did not confirm AI translation (%s -> %s)' % (source_label, target_text), LOG_INFO)
    _resume_playback_for_lucky_step(playback_state)
    return

  try:
    for slot in missing_slots:
      target_label = _as_text(slot.get('label', slot.get('code', 'target')))
      if progress_callback is not None:
        try:
          progress_callback(__language__(33304) % (source_label, target_label))
        except Exception:
          pass
      _log(
        'lucky translation step: translating %s -> %s using AI (source=%s)'
        % (source_label, target_label, source_subtitle),
        LOG_INFO
      )
      try:
        translated_path = _translate_subtitle_file(source_subtitle, source_language_code, slot['code'])
        slot['path'] = translated_path
        slot['origin'] = 'translated'
        if notify:
          _notify(__language__(33243) % (slot['label'], source_label), NOTIFY_INFO, timeout=3500)
        _log('lucky translation created for %s from %s: %s' % (slot['code'], source_subtitle, translated_path), LOG_INFO)
      except Exception as exc:
        _log('lucky translation failed for %s (%s)' % (slot['code'], exc), LOG_WARNING)
        if notify:
          _notify(__language__(33247) % (slot['label']), NOTIFY_WARNING, timeout=4500)
  finally:
    _resume_playback_for_lucky_step(playback_state)

def _cleanup_lucky_temp_sync_files(temp_paths):
  for temp_sync_path in temp_paths or []:
    try:
      if temp_sync_path and temp_sync_path.startswith(__temp__):
        xbmcvfs.delete(temp_sync_path)
    except Exception:
      pass

def _cleanup_lucky_downloaded_files(slots):
  """Remove downloaded subtitle files when the Lucky flow fails before finalizing."""
  for slot in (slots if isinstance(slots, list) else [slots]):
    origin = _as_text(slot.get('origin', '')).lower()
    path = _as_text(slot.get('path', '')).strip()
    if not path or not origin:
      continue
    # Only clean up files we downloaded or generated — never remove local_exact files.
    if origin.startswith('download_') or origin in ('smartsync', 'translated'):
      try:
        if xbmcvfs.exists(path):
          xbmcvfs.delete(path)
          _log('lucky cleanup removed: %s (origin=%s)' % (path, origin), LOG_INFO)
      except Exception:
        pass

def _run_i_feel_lucky_single_flow():
  video_dir, video_basename = _current_video_context()
  if not video_dir or not video_basename:
    _show_lucky_center_summary(__language__(33230), [__language__(33175)])
    return

  slot = _build_lucky_single_target_slot()
  if not slot:
    _show_lucky_center_summary(__language__(33230), [__language__(33279)])
    return

  _cleanup_generated_movie_sidecars(video_dir, video_basename)
  _log('i feel lucky single start: video_dir=%s video=%s target=%s' % (video_dir, video_basename, slot.get('code')), LOG_INFO)

  progress = _create_lucky_progress()
  smart_sync_temp_files = []
  lucky_cancel_token = '__lucky_cancelled__'
  lucky_timeout_token = '__lucky_timeout__'
  english_preview_confirmed_sync = False
  english_preview_tested = False
  smartsync_applied_any = False
  status_lines = []
  search_phase_start = time.time()
  search_phase_timeout_seconds = 90
  search_phase_timeout_active = True

  def _status(line):
    text = _as_text(line).strip()
    if not text:
      return
    if len(status_lines) > 0 and status_lines[-1] == text:
      return
    status_lines.append(text)

  def _check_search_timeout():
    if not search_phase_timeout_active:
      return
    elapsed = time.time() - search_phase_start
    if elapsed >= search_phase_timeout_seconds:
      _log('lucky single search phase timeout after %.1f seconds' % (elapsed), LOG_WARNING)
      raise RuntimeError(lucky_timeout_token)

  def _step(percent, line1='', line2=''):
    if not _update_lucky_progress(progress, percent, line1, line2):
      raise RuntimeError(lucky_cancel_token)
    _check_search_timeout()

  def _attempt_download(required_tiers, fallback_to_top, percent, status_label, delay_seconds):
    def _progress_line(message):
      _step(percent, status_label, message)

    result = _download_best_result_for_language(
      video_dir,
      video_basename,
      slot['code'],
      language_label=slot['label'],
      required_tiers=required_tiers,
      fallback_to_top=fallback_to_top,
      notify_errors=False,
      max_write_attempts=8,
      request_delay_seconds=delay_seconds,
      max_provider_attempts=2,
      retry_delay_seconds=0.95,
      progress_callback=_progress_line,
      progress_label=slot['label']
    )
    path = result.get('path')
    if not path:
      return False
    slot['path'] = path
    selected_result = result.get('result') or {}
    sync_tier = _as_text(selected_result.get('sync_tier', 'unknown')).lower()
    if sync_tier not in ['exact', 'likely', 'unknown']:
      sync_tier = 'unknown'
    slot['origin'] = 'download_%s' % (sync_tier)
    slot['last_release'] = _as_text(selected_result.get('release_name', '')).strip()
    slot['last_tier'] = sync_tier
    return True

  try:
    _step(4, __language__(33236), __language__(33251))

    exact_local = _pick_best_exact_local_language_match(video_dir, video_basename, slot['code'])
    if exact_local:
      slot['path'] = exact_local
      slot['origin'] = 'local_exact'
      _status('%s: local subtitle found (%s).' % (slot['label'], os.path.basename(exact_local)))
      _step(12, __language__(33236), '%s local match: %s' % (slot['label'], os.path.basename(exact_local)))

    download_request_delay_seconds = 0.0
    if not slot.get('path') and _is_lucky_download_enabled():
      status_line = __language__(33258) % (slot['label'])
      _step(18, status_line)
      downloaded = _attempt_download(
        required_tiers=['exact', 'likely'],
        fallback_to_top=False,
        percent=26,
        status_label=status_line,
        delay_seconds=download_request_delay_seconds
      )
      download_request_delay_seconds = 1.15
      if downloaded:
        release_name = _as_text(slot.get('last_release', '')).strip() or os.path.basename(_as_text(slot.get('path', '')))
        tier_text = _as_text(slot.get('last_tier', 'unknown')).upper()
        _status('%s: downloaded %s candidate (%s).' % (slot['label'], tier_text, release_name))
        _step(34, __language__(33242) % (slot['label']), '%s [%s]' % (release_name, tier_text))

    english_reference_path = ''
    english_reference_tier = ''
    rejected_english_reference_path = ''
    needs_english_reference = not slot.get('path')

    if needs_english_reference:
      _step(42, __language__(33261))

      def _english_progress(message):
        _step(46, __language__(33261), message)

      english_reference = _find_lucky_english_reference(
        video_dir,
        video_basename,
        request_delay_seconds=download_request_delay_seconds,
        allow_unknown_download=False,
        allow_unknown_local=False,
        progress_callback=_english_progress
      )
      english_reference_path = english_reference.get('path')
      english_reference_tier = _as_text(english_reference.get('tier', '')).lower()

      if english_reference_path:
        _status('English reference found (%s).' % (_as_text(english_reference_tier or 'likely').upper()))
        _step(52, __language__(33245) % (_as_text(english_reference_tier or 'likely').upper()))
      else:
        _status('No reliable English reference found.')
        _step(52, __language__(33246))

    # NOTE: Redundant second download attempt removed — same tiers/params as
    # the first attempt would not yield new results.

    can_use_reference_for_sync = english_reference_tier in ['exact', 'likely']
    should_test_english_reference = False
    if english_reference_path and _is_lucky_prompt_english_test_enabled() and (not slot.get('path') or _as_text(slot.get('origin', '')).lower() == 'download_unknown'):
      try:
        prompt_message = '%s[CR][CR]%s' % (__language__(33249), __language__(33250))
        should_test_english_reference = __msg_box__.yesno(__language__(33230), prompt_message)
      except Exception:
        should_test_english_reference = False

    if should_test_english_reference and english_reference_path and can_use_reference_for_sync:
      _close_progress(progress)
      progress = None
      preview_result = _run_lucky_english_sync_preview(english_reference_path)
      if preview_result.get('started'):
        english_preview_tested = True
        _focus_video_for_lucky_preview(preview_result.get('state'))
        _log('lucky single english preview started: reference=%s' % (english_reference_path), LOG_INFO)
        _let_lucky_preview_play(5000)
        preview_selection = 'cancel'
        try:
          preview_selection = _show_lucky_english_preview_dialog(english_reference_path)
        finally:
          try:
            _restore_lucky_preview_state(preview_result.get('state'))
            _log('lucky single english preview restore complete', LOG_INFO)
          except Exception:
            pass

        if preview_selection == 'cancel':
          raise RuntimeError(lucky_cancel_token)

        if preview_selection == 'sync':
          english_preview_confirmed_sync = True
        else:
          rejected_english_reference_path = english_reference_path
          english_reference_path = ''
          english_reference_tier = ''
          can_use_reference_for_sync = False
          _log('lucky single english reference rejected by user after preview', LOG_INFO)
          _status('English preview marked as not in sync; reference was rejected.')
          _step(68, __language__(33264), __language__(33270))
      progress = _create_lucky_progress()
      paused_now = _pause_lucky_background_playback()
      if paused_now:
        _status('Playback paused after English preview.')
        _step(68, __language__(33264), 'Playback paused for Lucky processing')
      else:
        _step(68, __language__(33264))

    if _is_lucky_smartsync_enabled() and english_reference_path and can_use_reference_for_sync:
      slot_path = slot.get('path')
      if slot_path and slot_path.lower() != english_reference_path.lower():
        _step(72, __language__(33262) % (slot['label']))
        force_sync_apply = bool(english_preview_confirmed_sync)
        sync_apply = _run_lucky_smartsync_to_reference(english_reference_path, slot_path, force_apply=force_sync_apply)
        if sync_apply.get('applied'):
          slot['path'] = sync_apply.get('path') or slot_path
          slot['origin'] = 'smartsync'
          smartsync_applied_any = True
          for temp_path in sync_apply.get('temp_paths', []):
            smart_sync_temp_files.append(temp_path)
          _status('%s: SmartSync applied using English reference.' % (slot['label']))
          _step(78, __language__(33244) % (slot['label']), 'SmartSync applied')
        else:
          _status('%s: SmartSync skipped (already close enough / no mismatch detected).' % (slot['label']))
          _step(78, __language__(33262) % (slot['label']), 'SmartSync skipped: no clear mismatch')

    unknown_candidates = []
    if not slot.get('path') and _is_lucky_download_enabled():
      unknown_candidates = _collect_lucky_unknown_candidates(
        video_dir,
        video_basename,
        slot.get('code', ''),
        max_candidates=3
      )
      _log(
        'lucky single unknown fallback candidates: language=%s count=%d'
        % (slot.get('code', ''), len(unknown_candidates)),
        LOG_INFO
      )

    # Disable search-phase timeout before AI translation — translation can
    # legitimately take several minutes for long subtitle files.
    search_phase_timeout_active = False

    if not slot.get('path') and _is_lucky_ai_translate_enabled() and len(unknown_candidates) == 0:
      def _translation_progress(message):
        _step(84, __language__(33260), message)

      _run_lucky_translate_missing_slots(
        [slot],
        video_dir,
        video_basename,
        english_reference_path,
        exclude_source_paths=[rejected_english_reference_path] if rejected_english_reference_path else None,
        require_english_source=True,
        notify=False,
        progress_callback=_translation_progress
      )
      if slot.get('path') and _as_text(slot.get('origin', '')).lower() == 'translated':
        _status('%s: generated via AI translation from English reference.' % (slot['label']))

    if not slot.get('path') and _is_lucky_download_enabled() and len(unknown_candidates) > 0:
      _step(88, __language__(33300) % (slot['label']))
      _close_progress(progress)
      progress = None

      picker_outcome = ''
      risky_candidate = _prompt_lucky_unknown_candidate(
        slot.get('label', slot.get('code', '')),
        unknown_candidates,
        video_basename
      )
      if risky_candidate:
        progress = _create_lucky_progress()
        _step(89, __language__(33265), 'Downloading selected %s subtitle...' % (slot['label']))
        risky_path = _download_lucky_selected_candidate(video_dir, video_basename, slot, risky_candidate)
        if risky_path:
          slot['path'] = risky_path
          slot['origin'] = 'download_unknown_user'
          _log(
            'lucky single user-selected risky candidate: language=%s provider=%s release=%s reason=%s'
            % (
              slot.get('code', ''),
              _as_text(risky_candidate.get('provider', 'provider')),
              _as_text(risky_candidate.get('release_name', 'subtitle')),
              _as_text(risky_candidate.get('risk_reason', __language__(33284)))
            ),
            LOG_WARNING
          )
          picker_outcome = 'Selected risky candidate: %s (%s)' % (
            _as_text(risky_candidate.get('release_name', 'subtitle')),
            _as_text(risky_candidate.get('provider', 'provider'))
          )
          _status('%s: %s' % (slot['label'], picker_outcome))
          _step(90, __language__(33265), 'Downloaded selected %s subtitle.' % (slot['label']))
          if _is_lucky_smartsync_enabled() and english_reference_path and can_use_reference_for_sync and risky_path.lower() != english_reference_path.lower():
            _step(91, __language__(33262) % (slot['label']), 'Running SmartSync for %s...' % (slot['label']))
            sync_apply = _run_lucky_smartsync_to_reference(english_reference_path, risky_path, force_apply=True)
            if sync_apply.get('applied'):
              slot['path'] = sync_apply.get('path') or risky_path
              slot['origin'] = 'smartsync'
              smartsync_applied_any = True
              for temp_path in sync_apply.get('temp_paths', []):
                smart_sync_temp_files.append(temp_path)
              picker_outcome = '%s | SmartSync applied' % (picker_outcome)
              _status('%s: SmartSync applied after risky selection.' % (slot['label']))
              _step(92, __language__(33244) % (slot['label']), 'SmartSync applied')
            else:
              picker_outcome = '%s | SmartSync skipped' % (picker_outcome)
              _status('%s: SmartSync skipped after risky selection.' % (slot['label']))
              _step(92, __language__(33262) % (slot['label']), 'SmartSync skipped')
        else:
          picker_outcome = __language__(33301) % (slot['label'])
          _status(picker_outcome)
          progress = _create_lucky_progress()
          _step(90, __language__(33265), picker_outcome)
      else:
        _log('lucky single user skipped risky candidates for %s' % (slot.get('code', 'target')), LOG_WARNING)
        picker_outcome = __language__(33303) % (slot['label'])
        _status(picker_outcome)
        progress = _create_lucky_progress()
        _step(90, __language__(33265), picker_outcome)

    _step(94, __language__(33265))
    subtitle1 = slot.get('path')

    if not subtitle1:
      _log('i feel lucky single stop: missing=%s' % (slot.get('label', slot.get('code', 'target'))), LOG_WARNING)
      _close_progress(progress)
      progress = None
      missing_message = __language__(33281) % (slot.get('label', slot.get('code', 'target')))
      _status(missing_message)
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_single_result_summary(
          slot,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
      _offer_lucky_recovery_actions(slot.get('label', slot.get('code', 'target')))
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      return

    _step(100, __language__(33282))
    subtitle1_dir = os.path.dirname(subtitle1) if subtitle1 else video_dir
    finalized = _finalize_selected_subtitle_paths(
      subtitle1,
      None,
      subtitle1_dir=subtitle1_dir,
      smart_sync_temp_files=smart_sync_temp_files,
      show_notifications=False,
      register_download_item=False
    )

    if finalized:
      done_message = __language__(33280) % (slot.get('label', slot.get('code', 'target')))
      _status(done_message)
      _close_progress(progress)
      progress = None
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_single_result_summary(
          slot,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=True
        )
      )
    else:
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      fail_message = __language__(33241)
      _status(fail_message)
      _close_progress(progress)
      progress = None
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_single_result_summary(
          slot,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
  except RuntimeError as exc:
    exc_text = _as_text(exc)
    if exc_text == lucky_cancel_token:
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      _cleanup_lucky_downloaded_files([slot])
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_single_result_summary(
          slot,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
      return
    if exc_text == lucky_timeout_token:
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      _cleanup_lucky_downloaded_files([slot])
      _log('i feel lucky single search phase timed out after %d seconds' % (search_phase_timeout_seconds), LOG_WARNING)
      _status('Search timed out after %d seconds.' % (search_phase_timeout_seconds))
      _close_progress(progress)
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_single_result_summary(
          slot,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
      return
    _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
    _cleanup_lucky_downloaded_files([slot])
    _log('i feel lucky single runtime error: %s' % (exc), LOG_WARNING)
    _show_lucky_center_summary(
      __language__(33230),
      _build_lucky_single_result_summary(
        slot,
        english_preview_tested=english_preview_tested,
        english_preview_in_sync=english_preview_confirmed_sync,
        smartsync_applied=smartsync_applied_any,
        overall_success=False
      )
    )
  except Exception as exc:
    _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
    _cleanup_lucky_downloaded_files([slot])
    _log('i feel lucky single unexpected error: %s' % (exc), LOG_ERROR)
    _show_lucky_center_summary(
      __language__(33230),
      _build_lucky_single_result_summary(
        slot,
        english_preview_tested=english_preview_tested,
        english_preview_in_sync=english_preview_confirmed_sync,
        smartsync_applied=smartsync_applied_any,
        overall_success=False
      )
    )
  finally:
    _close_progress(progress)

def _run_i_feel_lucky_flow():
  video_dir, video_basename = _current_video_context()
  if not video_dir or not video_basename:
    _show_lucky_center_summary(__language__(33230), [__language__(33175)])
    return

  slots = _build_lucky_target_slots()
  if len(slots) != 2:
    # Graceful fallback: if only one preferred language is configured, run the
    # single-subtitle flow instead of showing an error.
    single_slot = _build_lucky_single_target_slot()
    if single_slot and single_slot.get('code'):
      _log('i feel lucky dual: only 1 language configured, falling back to single flow', LOG_INFO)
      _run_i_feel_lucky_single_flow()
      return
    _show_lucky_center_summary(__language__(33230), [__language__(33240)])
    return

  _cleanup_generated_movie_sidecars(video_dir, video_basename)
  _log('i feel lucky start: video_dir=%s video=%s' % (video_dir, video_basename), LOG_INFO)

  progress = _create_lucky_progress()
  smart_sync_temp_files = []
  lucky_cancel_token = '__lucky_cancelled__'
  lucky_timeout_token = '__lucky_timeout__'
  english_preview_confirmed_sync = False
  english_preview_tested = False
  smartsync_applied_any = False
  status_lines = []
  search_phase_start = time.time()
  search_phase_timeout_seconds = 90
  search_phase_timeout_active = True

  def _status(line):
    text = _as_text(line).strip()
    if not text:
      return
    if len(status_lines) > 0 and status_lines[-1] == text:
      return
    status_lines.append(text)

  def _check_search_timeout():
    if not search_phase_timeout_active:
      return
    elapsed = time.time() - search_phase_start
    if elapsed >= search_phase_timeout_seconds:
      _log('lucky search phase timeout after %.1f seconds' % (elapsed), LOG_WARNING)
      raise RuntimeError(lucky_timeout_token)

  def _step(percent, line1='', line2=''):
    if not _update_lucky_progress(progress, percent, line1, line2):
      raise RuntimeError(lucky_cancel_token)
    _check_search_timeout()

  def _attempt_download_for_slot(slot, required_tiers, fallback_to_top, percent, status_label, delay_seconds):
    def _progress_line(message):
      _step(percent, status_label, message)

    result = _download_best_result_for_language(
      video_dir,
      video_basename,
      slot['code'],
      language_label=slot['label'],
      required_tiers=required_tiers,
      fallback_to_top=fallback_to_top,
      notify_errors=False,
      max_write_attempts=8,
      request_delay_seconds=delay_seconds,
      max_provider_attempts=2,
      retry_delay_seconds=0.95,
      progress_callback=_progress_line,
      progress_label=slot['label']
    )
    path = result.get('path')
    if not path:
      return False
    slot['path'] = path
    selected_result = result.get('result') or {}
    sync_tier = _as_text(selected_result.get('sync_tier', 'unknown')).lower()
    if sync_tier not in ['exact', 'likely', 'unknown']:
      sync_tier = 'unknown'
    slot['origin'] = 'download_%s' % (sync_tier)
    slot['last_release'] = _as_text(selected_result.get('release_name', '')).strip()
    slot['last_tier'] = sync_tier
    return True

  try:
    _step(4, __language__(33236), __language__(33251))

    automatch = _auto_match_subtitles(video_dir, video_basename)
    if automatch.get('subtitle1'):
      slots[0]['path'] = automatch.get('subtitle1')
      slots[0]['origin'] = 'local_exact'
      _status('%s: local subtitle found (%s).' % (slots[0]['label'], os.path.basename(automatch.get('subtitle1'))))
    if automatch.get('subtitle2'):
      slots[1]['path'] = automatch.get('subtitle2')
      slots[1]['origin'] = 'local_exact'
      _status('%s: local subtitle found (%s).' % (slots[1]['label'], os.path.basename(automatch.get('subtitle2'))))

    download_request_delay_seconds = 0.0
    if _is_lucky_download_enabled():
      for slot in _lucky_missing_slots(slots):
        status_line = __language__(33258) % (slot['label'])
        _step(18, status_line)
        downloaded = _attempt_download_for_slot(
          slot,
          required_tiers=['exact', 'likely'],
          fallback_to_top=False,
          percent=26,
          status_label=status_line,
          delay_seconds=download_request_delay_seconds
        )
        download_request_delay_seconds = 1.15
        if downloaded:
          release_name = _as_text(slot.get('last_release', '')).strip() or os.path.basename(_as_text(slot.get('path', '')))
          tier_text = _as_text(slot.get('last_tier', 'unknown')).upper()
          _status('%s: downloaded %s candidate (%s).' % (slot['label'], tier_text, release_name))
          _step(34, __language__(33242) % (slot['label']), '%s [%s]' % (release_name, tier_text))

    english_reference_path = ''
    english_reference_tier = ''
    rejected_english_reference_path = ''
    needs_english_reference = len(_lucky_missing_slots(slots)) > 0

    if needs_english_reference:
      _step(42, __language__(33261))

      def _english_progress(message):
        _step(46, __language__(33261), message)

      english_reference = _find_lucky_english_reference(
        video_dir,
        video_basename,
        request_delay_seconds=download_request_delay_seconds,
        allow_unknown_download=False,
        allow_unknown_local=False,
        progress_callback=_english_progress
      )
      english_reference_path = english_reference.get('path')
      english_reference_tier = _as_text(english_reference.get('tier', '')).lower()

      if english_reference_path:
        _status('English reference found (%s).' % (_as_text(english_reference_tier or 'likely').upper()))
        _step(52, __language__(33245) % (_as_text(english_reference_tier or 'likely').upper()))
      else:
        _status('No reliable English reference found.')
        _step(52, __language__(33246))

    # NOTE: Redundant second download attempt removed — same tiers/params as
    # the first attempt would not yield new results.  Unknown-tier candidates
    # are collected later in the flow and offered to the user explicitly.

    can_use_reference_for_sync = english_reference_tier in ['exact', 'likely']
    should_test_english_reference = False
    if english_reference_path and _is_lucky_prompt_english_test_enabled():
      try:
        prompt_message = '%s[CR][CR]%s' % (__language__(33249), __language__(33250))
        should_test_english_reference = __msg_box__.yesno(__language__(33230), prompt_message)
      except Exception:
        should_test_english_reference = False

    if should_test_english_reference and english_reference_path and can_use_reference_for_sync:
      _close_progress(progress)
      progress = None
      preview_result = _run_lucky_english_sync_preview(english_reference_path)
      if preview_result.get('started'):
        english_preview_tested = True
        _focus_video_for_lucky_preview(preview_result.get('state'))
        _log('lucky english preview started: reference=%s' % (english_reference_path), LOG_INFO)
        _let_lucky_preview_play(5000)
        preview_selection = 'cancel'
        try:
          preview_selection = _show_lucky_english_preview_dialog(english_reference_path)
        finally:
          try:
            _restore_lucky_preview_state(preview_result.get('state'))
            _log('lucky english preview restore complete', LOG_INFO)
          except Exception:
            pass

        if preview_selection == 'cancel':
          raise RuntimeError(lucky_cancel_token)

        if preview_selection == 'sync':
          english_preview_confirmed_sync = True
        else:
          rejected_english_reference_path = english_reference_path
          english_reference_path = ''
          english_reference_tier = ''
          can_use_reference_for_sync = False
          _log('lucky english reference rejected by user after preview', LOG_INFO)
          _status('English preview marked as not in sync; reference was rejected.')
          _step(68, __language__(33264), __language__(33270))
      progress = _create_lucky_progress()
      paused_now = _pause_lucky_background_playback()
      if paused_now:
        _status('Playback paused after English preview.')
        _step(68, __language__(33264), 'Playback paused for Lucky processing')
      else:
        _step(68, __language__(33264))

    if _is_lucky_smartsync_enabled() and english_reference_path and can_use_reference_for_sync:
      for slot in slots:
        slot_path = slot.get('path')
        if not slot_path:
          continue
        if slot_path.lower() == english_reference_path.lower():
          continue
        _step(72, __language__(33262) % (slot['label']))
        force_sync_apply = bool(english_preview_confirmed_sync)
        sync_apply = _run_lucky_smartsync_to_reference(english_reference_path, slot_path, force_apply=force_sync_apply)
        if not sync_apply.get('applied'):
          _status('%s: SmartSync skipped (already close enough / no mismatch detected).' % (slot['label']))
          continue
        slot['path'] = sync_apply.get('path') or slot_path
        slot['origin'] = 'smartsync'
        smartsync_applied_any = True
        for temp_path in sync_apply.get('temp_paths', []):
          smart_sync_temp_files.append(temp_path)
        _status('%s: SmartSync applied using English reference.' % (slot['label']))

    unknown_candidates_by_slot = {}
    if len(_lucky_missing_slots(slots)) > 0 and _is_lucky_download_enabled():
      for missing_slot in _lucky_missing_slots(slots):
        slot_key = _as_text(missing_slot.get('slot', missing_slot.get('code', ''))).strip() or missing_slot.get('code', '')
        unknown_candidates = _collect_lucky_unknown_candidates(
          video_dir,
          video_basename,
          missing_slot.get('code', ''),
          max_candidates=3
        )
        unknown_candidates_by_slot[slot_key] = unknown_candidates
        _log(
          'lucky dual unknown fallback candidates: language=%s count=%d'
          % (missing_slot.get('code', ''), len(unknown_candidates)),
          LOG_INFO
        )

    # Disable search-phase timeout before AI translation — translation can
    # legitimately take several minutes for long subtitle files.
    search_phase_timeout_active = False

    if len(_lucky_missing_slots(slots)) > 0 and _is_lucky_ai_translate_enabled():
      ai_slots = []
      for missing_slot in _lucky_missing_slots(slots):
        slot_key = _as_text(missing_slot.get('slot', missing_slot.get('code', ''))).strip() or missing_slot.get('code', '')
        if len(unknown_candidates_by_slot.get(slot_key, [])) > 0:
          continue
        ai_slots.append(missing_slot)

      if len(ai_slots) > 0:
        def _translation_progress(message):
          _step(84, __language__(33260), message)

        _run_lucky_translate_missing_slots(
          ai_slots,
          video_dir,
          video_basename,
          english_reference_path,
          exclude_source_paths=[rejected_english_reference_path] if rejected_english_reference_path else None,
          require_english_source=True,
          notify=False,
          progress_callback=_translation_progress
        )
        for ai_slot in ai_slots:
          if ai_slot.get('path') and _as_text(ai_slot.get('origin', '')).lower() == 'translated':
            _status('%s: generated via AI translation from English reference.' % (ai_slot.get('label', ai_slot.get('code', 'target'))))

    if len(_lucky_missing_slots(slots)) > 0 and _is_lucky_download_enabled():
      _step(88, __language__(33260))
      _close_progress(progress)
      progress = None

      for slot in _lucky_missing_slots(slots):
        slot_key = _as_text(slot.get('slot', slot.get('code', ''))).strip() or slot.get('code', '')
        unknown_candidates = unknown_candidates_by_slot.get(slot_key, [])
        if len(unknown_candidates) == 0:
          continue

        # Ensure the risky-candidate picker is never shown with a stale progress
        # dialog still open from the previous language iteration.
        _close_progress(progress)
        progress = None

        risky_candidate = _prompt_lucky_unknown_candidate(
          slot.get('label', slot.get('code', '')),
          unknown_candidates,
          video_basename
        )
        if not risky_candidate:
          _log('lucky user skipped risky candidates for %s' % (slot.get('code', 'target')), LOG_WARNING)
          _status(__language__(33303) % (slot['label']))
          progress = _create_lucky_progress()
          _step(89, __language__(33265), __language__(33303) % (slot['label']))
          continue

        progress = _create_lucky_progress()
        _step(89, __language__(33265), 'Downloading selected %s subtitle...' % (slot['label']))
        risky_path = _download_lucky_selected_candidate(video_dir, video_basename, slot, risky_candidate)
        if not risky_path:
          _status(__language__(33301) % (slot['label']))
          _step(90, __language__(33265), __language__(33301) % (slot['label']))
          continue

        slot['path'] = risky_path
        slot['origin'] = 'download_unknown_user'
        _log(
          'lucky user-selected risky candidate: language=%s provider=%s release=%s reason=%s'
          % (
            slot.get('code', ''),
            _as_text(risky_candidate.get('provider', 'provider')),
            _as_text(risky_candidate.get('release_name', 'subtitle')),
            _as_text(risky_candidate.get('risk_reason', __language__(33284)))
          ),
          LOG_WARNING
        )
        _status('%s: selected risky candidate (%s).' % (slot['label'], _as_text(risky_candidate.get('release_name', 'subtitle'))))
        _step(90, __language__(33265), 'Downloaded selected %s subtitle.' % (slot['label']))

        if _is_lucky_smartsync_enabled() and english_reference_path and can_use_reference_for_sync and risky_path.lower() != english_reference_path.lower():
          _log('lucky dual smartsync start for %s using reference=%s target=%s' % (slot.get('label', slot.get('code', 'target')), english_reference_path, risky_path), LOG_INFO)
          _step(91, __language__(33262) % (slot['label']), 'Running SmartSync for %s...' % (slot['label']))
          sync_apply = _run_lucky_smartsync_to_reference(english_reference_path, risky_path, force_apply=True)
          if not sync_apply.get('applied'):
            _status('%s: SmartSync skipped after risky selection.' % (slot['label']))
            _step(92, __language__(33262) % (slot['label']), 'SmartSync skipped')
            continue
          slot['path'] = sync_apply.get('path') or risky_path
          slot['origin'] = 'smartsync'
          smartsync_applied_any = True
          for temp_path in sync_apply.get('temp_paths', []):
            smart_sync_temp_files.append(temp_path)
          _status('%s: SmartSync applied after risky selection.' % (slot['label']))
          _step(92, __language__(33244) % (slot['label']), 'SmartSync applied')

      progress = _create_lucky_progress()
      _step(90, __language__(33265))

    _step(94, __language__(33265))
    subtitle1 = slots[0].get('path')
    subtitle2 = slots[1].get('path')

    if not subtitle1 or not subtitle2:
      missing_labels = []
      if not subtitle1:
        missing_labels.append(slots[0].get('label', slots[0].get('code', '')))
      if not subtitle2:
        missing_labels.append(slots[1].get('label', slots[1].get('code', '')))
      missing_text = ', '.join([label for label in missing_labels if label]).strip()
      if not missing_text:
        missing_text = 'unknown'
      _log('i feel lucky strict mode stop: missing=%s' % (missing_text), LOG_WARNING)
      _close_progress(progress)
      progress = None
      missing_message = __language__(33267) % (missing_text)
      _status(missing_message)
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_dual_result_summary(
          slots,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
      _offer_lucky_recovery_actions(missing_text)
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      return

    _step(100, __language__(33266))
    subtitle1_dir = os.path.dirname(subtitle1) if subtitle1 else video_dir
    finalized = _finalize_selected_subtitle_paths(
      subtitle1,
      subtitle2,
      subtitle1_dir=subtitle1_dir,
      smart_sync_temp_files=smart_sync_temp_files,
      show_notifications=False,
      register_download_item=False
    )

    if finalized:
      _status(__language__(33238))
      _close_progress(progress)
      progress = None
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_dual_result_summary(
          slots,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=True
        )
      )
    else:
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      _status(__language__(33241))
      _close_progress(progress)
      progress = None
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_dual_result_summary(
          slots,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
  except RuntimeError as exc:
    exc_text = _as_text(exc)
    if exc_text == lucky_cancel_token:
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      _cleanup_lucky_downloaded_files(slots)
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_dual_result_summary(
          slots,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
      return
    if exc_text == lucky_timeout_token:
      _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
      _cleanup_lucky_downloaded_files(slots)
      _log('i feel lucky search phase timed out after %d seconds' % (search_phase_timeout_seconds), LOG_WARNING)
      _status('Search timed out after %d seconds.' % (search_phase_timeout_seconds))
      _close_progress(progress)
      _show_lucky_center_summary(
        __language__(33230),
        _build_lucky_dual_result_summary(
          slots,
          english_preview_tested=english_preview_tested,
          english_preview_in_sync=english_preview_confirmed_sync,
          smartsync_applied=smartsync_applied_any,
          overall_success=False
        )
      )
      return
    _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
    _cleanup_lucky_downloaded_files(slots)
    _log('i feel lucky runtime error: %s' % (exc), LOG_WARNING)
    _show_lucky_center_summary(
      __language__(33230),
      _build_lucky_dual_result_summary(
        slots,
        english_preview_tested=english_preview_tested,
        english_preview_in_sync=english_preview_confirmed_sync,
        smartsync_applied=smartsync_applied_any,
        overall_success=False
      )
    )
  except Exception as exc:
    _cleanup_lucky_temp_sync_files(smart_sync_temp_files)
    _cleanup_lucky_downloaded_files(slots)
    _log('i feel lucky unexpected error: %s' % (exc), LOG_ERROR)
    _show_lucky_center_summary(
      __language__(33230),
      _build_lucky_dual_result_summary(
        slots,
        english_preview_tested=english_preview_tested,
        english_preview_in_sync=english_preview_confirmed_sync,
        smartsync_applied=smartsync_applied_any,
        overall_success=False
      )
    )
  finally:
    _close_progress(progress)

def _run_dual_subtitle_flow():
  video_dir, video_basename = _current_video_context()
  _cleanup_generated_movie_sidecars(video_dir, video_basename)
  start_dir = _resolve_start_dir(video_dir)

  subtitle1 = None
  subtitle2 = None
  subtitle1_dir = ''
  force_manual_both = False
  smart_sync_temp_files = []

  automatch = _auto_match_subtitles(video_dir, video_basename)
  download_attempt = _attempt_auto_download_for_automatch(automatch, video_dir, video_basename)
  if download_attempt.get('applied'):
    automatch['subtitle1'] = download_attempt.get('subtitle1')
    automatch['subtitle2'] = download_attempt.get('subtitle2')
    automatch = _refresh_automatch_mode_from_slots(automatch)

  _log('dual flow start: video_dir=%s video_basename=%s start_dir=%s automatch_mode=%s' % (video_dir, video_basename, start_dir, automatch['mode']), LOG_DEBUG)
  if automatch['mode'] == 'full':
    subtitle1 = automatch['subtitle1']
    subtitle2 = automatch['subtitle2']
    subtitle1_dir = os.path.dirname(subtitle1)
    _notify(__language__(33035) % (automatch['language1_label'], automatch['language2_label']), NOTIFY_INFO)

  elif automatch['mode'] == 'partial':
    _notify(__language__(33036) % (automatch['found_label'], automatch['missing_label']), NOTIFY_WARNING)
    _notify_manual_translation_hint()
    partial_behavior = _get_partial_match_behavior()

    if partial_behavior == 'manual_both':
      _notify(__language__(33044), NOTIFY_INFO)
      force_manual_both = True

    elif partial_behavior == 'auto_use':
      if automatch['missing'] == 'subtitle2':
        subtitle1 = automatch['subtitle1']
        subtitle1_dir = os.path.dirname(subtitle1)
        title2 = __language__(33006) + ' ' + __language__(33009)
        subtitle2, _ = _browse_for_subtitle(title2, subtitle1_dir)
        if subtitle2 is None and _is_second_subtitle_required():
          _notify(__language__(33040), NOTIFY_WARNING)
          return
      else:
        subtitle2 = automatch['subtitle2']
        browse_dir = os.path.dirname(subtitle2)
        subtitle1, subtitle1_dir = _browse_for_subtitle(__language__(33005), browse_dir)
        if subtitle1 is None:
          if _is_second_subtitle_required():
            _notify(__language__(33040), NOTIFY_WARNING)
            return
          subtitle1 = subtitle2
          subtitle2 = None
          subtitle1_dir = browse_dir

    else:
      message = __language__(33014) % (automatch['found_label'], automatch['missing_label'])
      if __msg_box__.yesno(__scriptname__, message):
        if automatch['missing'] == 'subtitle2':
          subtitle1 = automatch['subtitle1']
          subtitle1_dir = os.path.dirname(subtitle1)
          title2 = __language__(33006) + ' ' + __language__(33009)
          subtitle2, _ = _browse_for_subtitle(title2, subtitle1_dir)
          if subtitle2 is None and _is_second_subtitle_required():
            _notify(__language__(33040), NOTIFY_WARNING)
            return
        else:
          subtitle2 = automatch['subtitle2']
          browse_dir = os.path.dirname(subtitle2)
          subtitle1, subtitle1_dir = _browse_for_subtitle(__language__(33005), browse_dir)
          if subtitle1 is None:
            if _is_second_subtitle_required():
              _notify(__language__(33040), NOTIFY_WARNING)
              return
            subtitle1 = subtitle2
            subtitle2 = None
            subtitle1_dir = browse_dir
      else:
        _notify(__language__(33044), NOTIFY_INFO)
        force_manual_both = True

  elif automatch['mode'] == 'ambiguous':
    _notify(__language__(33038), NOTIFY_WARNING)

  elif automatch['mode'] == 'none':
    _notify(__language__(33037), NOTIFY_WARNING)
    _notify_manual_translation_hint()

  apply_no_match_behavior = automatch['mode'] == 'none'
  if subtitle1 is None and subtitle2 is None:
    subtitle1, subtitle2, subtitle1_dir = _pick_subtitles_with_settings(
      start_dir,
      apply_no_match_behavior=apply_no_match_behavior,
      force_manual_both=force_manual_both
    )
    if subtitle1 is None:
      _log('dual flow ended without subtitle selection', LOG_INFO)
      return

  if subtitle1 is None:
    return

  subtitle1, subtitle2, smart_sync_temp_files = _maybe_run_smart_sync(subtitle1, subtitle2, video_dir, start_dir)
  if subtitle1 is None:
    return

  _finalize_selected_subtitle_paths(
    subtitle1,
    subtitle2,
    subtitle1_dir=subtitle1_dir,
    smart_sync_temp_files=smart_sync_temp_files
  )

action = params.get('action', 'search')

if action == 'manualsearch':
  Search()

elif action == 'search':
  Search()

elif action == 'browsedual':
  _run_dual_subtitle_flow()

elif action == 'downloadmanual':
  _run_manual_download_action()

elif action == 'ifeelluckysingle':
  _run_i_feel_lucky_single_flow()

elif action == 'ifeelluckydual' or action == 'ifeellucky':
  _run_i_feel_lucky_flow()

elif action == 'downloadpick':
  _run_manual_download_pick_action()

elif action == 'smartsyncmanual':
  _run_manual_smart_sync_action()

elif action == 'translatemanual':
  _run_manual_translation_action()

elif action == 'restorebackup':
  _run_restore_backup_action()

elif action == 'settings':
  __addon__.openSettings()
  _log('settings opened', LOG_DEBUG)

else:
  Search()

xbmcplugin.endOfDirectory(int(sys.argv[1]))
