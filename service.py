# -*- coding: utf-8 -*-

import os
import re
import sys
import json
import xbmc
import xbmcaddon
import xbmcgui,xbmcplugin
import xbmcvfs
import shutil

import uuid
import chardet

try:
  from urllib.request import Request, urlopen
  from urllib.error import HTTPError, URLError
except ImportError:
  from urllib2 import Request, urlopen, HTTPError, URLError

if sys.version_info[0] == 2:
    p2 = True
else:
    unicode = str
    p2 = False

from resources.lib.dualsubs import mergesubs
from resources.lib import smartsync

__addon__ = xbmcaddon.Addon()
__author__     = __addon__.getAddonInfo('author')
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')
__version__    = __addon__.getAddonInfo('version')
__language__   = __addon__.getLocalizedString

LANGUAGE_CODE_REGEX = re.compile(r'\(([a-z]{2})\)\s*$', re.IGNORECASE)
NOTIFY_INFO = getattr(xbmcgui, 'NOTIFICATION_INFO', '')
NOTIFY_WARNING = getattr(xbmcgui, 'NOTIFICATION_WARNING', '')
NOTIFY_ERROR = getattr(xbmcgui, 'NOTIFICATION_ERROR', '')
LOG_DEBUG = getattr(xbmc, 'LOGDEBUG', 0)
LOG_INFO = getattr(xbmc, 'LOGINFO', getattr(xbmc, 'LOGNOTICE', 1))
LOG_WARNING = getattr(xbmc, 'LOGWARNING', 2)
LOG_ERROR = getattr(xbmc, 'LOGERROR', 4)
OPENAI_CHAT_ENDPOINT = 'https://api.openai.com/v1/chat/completions'
FENCED_JSON_REGEX = re.compile(r'^```(?:json)?\s*(.*?)\s*```$', re.DOTALL)

try:
    translatePath = xbmcvfs.translatePath
except AttributeError:
    translatePath = xbmc.translatePath

__cwd__        = translatePath(__addon__.getAddonInfo('path'))
if p2:
    __cwd__ = __cwd__.decode("utf-8")

__resource__   = translatePath(os.path.join(__cwd__, 'resources', 'lib'))
if p2:
    __resource__ = __resource__.decode("utf-8")

__profile__    = translatePath(__addon__.getAddonInfo('profile'))
if p2:
    __profile__ = __profile__.decode("utf-8")

__temp__       = translatePath(os.path.join(__profile__, 'temp', ''))
if p2:
    __temp__ = __temp__.decode("utf-8")

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
except:
  window = ''

def AddItem(name, url):
  listitem = xbmcgui.ListItem(label="", label2=name)
  listitem.setProperty("sync", "false")
  listitem.setProperty("hearing_imp", "false")
  xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def Search():
  AddItem(__language__(33004), "plugin://%s/?action=browsedual" % (__scriptid__))
  AddItem(__language__(33008), "plugin://%s/?action=settings" % (__scriptid__))

def get_params(string=""):
  param = {}
  if string == "":
    if len(sys.argv) > 2:
      paramstring = sys.argv[2]
    else:
      paramstring = ""
  else:
    paramstring = string
  if len(paramstring) >= 2:
    params = paramstring
    cleanedparams = params.replace('?', '')
    if params[len(params) - 1] == '/':
      params = params[0:len(params) - 2]
    pairsofparams = cleanedparams.split('&')
    param = {}
    for i in range(len(pairsofparams)):
      splitparams = {}
      splitparams = pairsofparams[i].split('=')
      if len(splitparams) == 2:
        param[splitparams[0]] = splitparams[1]

  return param

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

def _equal_text(setting_value, message_id):
  return setting_value == str(message_id) or setting_value == __language__(message_id)

def _notify(message, icon=NOTIFY_INFO, timeout=4000):
  try:
    __msg_box__.notification(__scriptname__, message, icon, timeout)
  except:
    try:
      xbmc.executebuiltin(u'Notification(%s,%s)' % (__scriptname__, message))
    except:
      pass

def _log(message, level=LOG_INFO):
  try:
    xbmc.log('[%s] %s' % (__scriptid__, message), level)
  except:
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
  except:
    pass

  if path and not path.endswith('/'):
    try:
      if xbmcvfs.exists(path + '/'):
        return True
    except:
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
  except:
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
    return match.group(1).lower()

  language_value = language_value.strip().lower()
  if re.match(r'^[a-z]{2}$', language_value):
    return language_value

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
    if p2:
      if isinstance(value, unicode):
        return value
      return value.decode('utf-8', 'replace')
    if isinstance(value, bytes):
      return value.decode('utf-8', 'replace')
  except:
    pass

  try:
    return unicode(value)
  except:
    return str(value)

def _to_utf8_bytes(text):
  if text is None:
    text = ''

  if p2:
    if isinstance(text, unicode):
      return text.encode('utf-8')
    return text

  if isinstance(text, bytes):
    return text
  return _as_text(text).encode('utf-8')

def _get_int_setting(setting_id, default_value, minimum_value, maximum_value):
  value = __addon__.getSetting(setting_id)
  try:
    parsed = int(value)
  except:
    parsed = default_value

  if parsed < minimum_value:
    return minimum_value
  if parsed > maximum_value:
    return maximum_value
  return parsed

def _is_ai_translation_enabled():
  return __addon__.getSetting('enable_ai_translation') == 'true'

def _is_smart_sync_enabled():
  setting = __addon__.getSetting('enable_smart_sync')
  if setting == '':
    return True
  return setting == 'true'

def _get_openai_api_key():
  try:
    return __addon__.getSetting('openai_api_key').strip()
  except:
    return ''

def _get_openai_model():
  model = __addon__.getSetting('openai_model')
  if not model:
    model = 'gpt-4.1-mini'
  return model.strip()

def _get_translation_batch_size():
  return _get_int_setting('translation_batch_size', 25, 5, 100)

def _get_translation_timeout_seconds():
  return _get_int_setting('openai_timeout_seconds', 60, 15, 300)

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
  except:
    pass

  try:
    progress.update(percent, line1)
    return
  except:
    pass

  try:
    progress.update(percent)
  except:
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
    except:
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
  if len(translations) != len(lines):
    raise RuntimeError('OpenAI returned %d translations for %d lines.' % (len(translations), len(lines)))

  normalized = []
  for item in translations:
    normalized.append(_as_text(item))
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
    detected = chardet.detect(raw_data)
    encoding = detected.get('encoding')
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

  match = re.match(r'^(.*?)([._-])([a-z]{2})$', source_base, re.IGNORECASE)
  if match:
    translated_base = '%s%s%s' % (match.group(1), match.group(2), target_language_code.lower())
  else:
    translated_base = '%s-%s' % (source_base, target_language_code.lower())

  if translated_base.lower() == source_base.lower():
    translated_base = '%s-translated-%s' % (source_base, target_language_code.lower())

  return os.path.join(source_directory, '%s.srt' % (translated_base))

def _guess_language_code_from_path(path):
  filename = os.path.basename(path)
  base = os.path.splitext(filename)[0]
  match = re.search(r'[._-]([a-z]{2})$', base, re.IGNORECASE)
  if match:
    return match.group(1).lower()
  return 'auto'

def _list_srt_files(folder_path):
  if not folder_path:
    return []

  try:
    file_names = xbmcvfs.listdir(folder_path)[1]
  except:
    return []

  candidates = []
  for file_name in file_names:
    if file_name.lower().endswith('.srt'):
      candidates.append(os.path.join(folder_path, file_name))

  candidates.sort(key=lambda item: os.path.basename(item).lower())
  return candidates

def _select_translation_source_subtitle(video_dir, fallback_dir=''):
  source_dir = video_dir
  candidates = _list_srt_files(source_dir)
  if len(candidates) == 0 and fallback_dir and fallback_dir != video_dir:
    source_dir = fallback_dir
    candidates = _list_srt_files(source_dir)

  if len(candidates) == 0:
    _notify(__language__(33077), NOTIFY_WARNING)
    _log('translation source selection failed: no .srt files in video/fallback dir', LOG_WARNING)
    return None

  labels = []
  for path in candidates:
    labels.append(os.path.basename(path))

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
  except:
    return path

def _load_subtitle_for_processing(subtitle_path):
  pysubs2 = _load_pysubs2()
  local_copy = _copy_subtitle_to_temp(subtitle_path)
  encoding = _detect_text_encoding(local_copy)

  try:
    subtitle_data = pysubs2.load(local_copy, encoding=encoding)
  except:
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

def _select_smart_sync_target(subtitle1, subtitle2):
  options = [
    __language__(33091) % (_safe_basename(subtitle1)),
    __language__(33092) % (_safe_basename(subtitle2)),
  ]
  selected = __msg_box__.select(__language__(33090), options)
  if selected is None or selected < 0:
    _log('smart sync target selection cancelled', LOG_INFO)
    return None
  if selected == 0:
    return subtitle1
  return subtitle2

def _collect_smart_sync_reference_candidates(target_path, subtitle1, subtitle2, video_dir, start_dir):
  selected_candidates = []
  if subtitle1 and subtitle1.lower() != target_path.lower():
    selected_candidates.append((__language__(33093) % (_safe_basename(subtitle1)), subtitle1))
  if subtitle2 and subtitle2.lower() != target_path.lower():
    selected_candidates.append((__language__(33093) % (_safe_basename(subtitle2)), subtitle2))

  folder_candidates = []
  for candidate_dir in _unique_paths([video_dir, start_dir]):
    for path in _list_srt_files(candidate_dir):
      if path.lower() == target_path.lower():
        continue
      folder_candidates.append((__language__(33094) % (_safe_basename(path)), path))

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

def _select_smart_sync_reference(target_path, subtitle1, subtitle2, video_dir, start_dir):
  candidates = _collect_smart_sync_reference_candidates(target_path, subtitle1, subtitle2, video_dir, start_dir)
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

  reference_path = candidates[selected][1]
  if reference_path.lower() == target_path.lower():
    _notify(__language__(33097), NOTIFY_WARNING)
    return None
  return reference_path

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
    except:
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
    except:
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

def _apply_synced_subtitle_to_target(target_path, synced_subs):
  synced_temp = _save_subtitle_to_temp(synced_subs)
  backup_path = '%s.bak' % (target_path)

  try:
    if xbmcvfs.exists(backup_path):
      xbmcvfs.delete(backup_path)
    if not xbmcvfs.copy(target_path, backup_path):
      raise RuntimeError('backup copy failed')

    if not xbmcvfs.copy(synced_temp, target_path):
      try:
        if not xbmcvfs.exists(target_path):
          xbmcvfs.copy(backup_path, target_path)
      except:
        pass
      raise RuntimeError('target write failed')

    xbmcvfs.delete(synced_temp)
    return {
      'play_path': target_path,
      'persisted': True,
      'temp_path': '',
      'backup_path': backup_path,
    }
  except Exception as exc:
    _log('smart sync persist failed for %s (%s)' % (target_path, exc), LOG_WARNING)
    return {
      'play_path': synced_temp,
      'persisted': False,
      'temp_path': synced_temp,
      'backup_path': backup_path,
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
    _log('smart sync mismatch not detected: median=%s offset=%s' % (mismatch.get('raw_median_error_ms'), mismatch.get('estimated_global_offset_ms')), LOG_DEBUG)
    return subtitle1, subtitle2, []

  start_message = __language__(33098) % (mismatch.get('raw_median_error_ms', 0), mismatch.get('estimated_global_offset_ms', 0))
  selected_action = __msg_box__.select(start_message, [__language__(33084), __language__(33085)])
  if selected_action != 1:
    _log('smart sync skipped by user after mismatch prompt', LOG_INFO)
    return subtitle1, subtitle2, []

  target_path = _select_smart_sync_target(subtitle1, subtitle2)
  if target_path is None:
    return subtitle1, subtitle2, []
  reference_path = _select_smart_sync_reference(target_path, subtitle1, subtitle2, video_dir, start_dir)
  if reference_path is None:
    return subtitle1, subtitle2, []

  try:
    local_result = _run_smart_sync_local(reference_path, target_path)
  except Exception as exc:
    _log('smart sync local stage failed: %s' % (exc), LOG_WARNING)
    _notify(__language__(33109), NOTIFY_WARNING)
    return subtitle1, subtitle2, []

  _notify(__language__(33107) % (_smart_sync_confidence_percent(local_result), local_result.get('median_error_ms', 0)), NOTIFY_INFO)

  chosen_result = local_result
  if local_result.get('low_confidence'):
    low_conf_title = __language__(33099) % (_smart_sync_confidence_percent(local_result), local_result.get('median_error_ms', 0))
    low_conf_choice = __msg_box__.select(low_conf_title, [__language__(33110), __language__(33111), __language__(33112)])
    if low_conf_choice == 2 or low_conf_choice < 0:
      _log('smart sync skipped due low confidence user choice', LOG_INFO)
      return subtitle1, subtitle2, []

    if low_conf_choice == 1:
      ai_result = None
      try:
        ai_result = _run_smart_sync_ai(reference_path, target_path)
      except Exception as exc:
        _log('smart sync ai stage failed: %s' % (exc), LOG_WARNING)
        ai_result = None

      if ai_result is not None:
        chosen_result = ai_result
        _notify(__language__(33102), NOTIFY_INFO)
      else:
        fallback_choice = __msg_box__.select(__language__(33105), [__language__(33110), __language__(33112)])
        if fallback_choice != 0:
          return subtitle1, subtitle2, []

  sync_apply = _apply_synced_subtitle_to_target(target_path, chosen_result['synced_subs'])

  updated_subtitle1 = subtitle1
  updated_subtitle2 = subtitle2
  if target_path.lower() == subtitle1.lower():
    updated_subtitle1 = sync_apply['play_path']
  elif target_path.lower() == subtitle2.lower():
    updated_subtitle2 = sync_apply['play_path']

  method_label = _smart_sync_method_label(chosen_result.get('method', 'local'))
  if sync_apply['persisted']:
    _notify(__language__(33108) % (method_label), NOTIFY_INFO)
  else:
    _notify(__language__(33113), NOTIFY_WARNING)

  temp_paths = []
  if sync_apply.get('temp_path'):
    temp_paths.append(sync_apply['temp_path'])
  return updated_subtitle1, updated_subtitle2, temp_paths

def _load_pysubs2():
  try:
    import pysubs2
  except:
    from lib import pysubs2
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
    except:
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
      except:
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
    if xbmcvfs.exists(translated_path):
      xbmcvfs.delete(translated_path)
    if not xbmcvfs.copy(temp_output, translated_path):
      raise RuntimeError(__language__(33071))

    _log('ai translation wrote subtitle=%s model=%s' % (translated_path, model), LOG_INFO)
    return translated_path
  finally:
    if progress is not None:
      try:
        progress.close()
      except:
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

def _match_subtitle_name(subtitle_name, video_basename, language_code, strict):
  name_lower = subtitle_name.lower()
  base_lower = video_basename.lower()
  lang_lower = language_code.lower()

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
  suffixes = ['.%s' % (lang_lower), '-%s' % (lang_lower), '_%s' % (lang_lower)]
  if strict:
    return tail_lower in suffixes

  for suffix in suffixes:
    if tail_lower.endswith(suffix):
      return True
  return False

def _find_subtitle_matches(video_dir, video_basename, language_code, strict):
  if not video_dir or not video_basename or not language_code:
    return []

  try:
    files = xbmcvfs.listdir(video_dir)[1]
  except:
    return []

  matches = []
  seen = {}
  for subtitle_name in files:
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

  while True:
    subtitlefile = __msg_box__.browse(1, title, "video", ".zip|.srt", False, False, browse_dir, False)
    if subtitlefile is None or subtitlefile == '' or subtitlefile == browse_dir:
      return None, browse_dir

    selected_dir = os.path.dirname(subtitlefile)
    if subtitlefile.lower().endswith('.zip'):
      extracted_file = unzip(subtitlefile, [ ".srt" ])
      if extracted_file is None:
        browse_dir = selected_dir
        continue
      return extracted_file, selected_dir

    return subtitlefile, selected_dir

def _remember_last_used_dir(path):
  if not _is_usable_browse_dir(path):
    return

  try:
    __addon__.setSetting('last_used_subtitle_dir', path)
  except:
    pass

def _prepare_and_merge_subtitles(subs):
  substemp = []
  try:
    for sub in subs:
      # Python can fail to read subtitles from special Kodi locations (for example smb://).
      # Copy each selected subtitle to a local temporary file first.
      subtemp = os.path.join(__temp__, "%s" % (str(uuid.uuid4())))
      if not xbmcvfs.copy(sub, subtemp):
        raise RuntimeError(__language__(33043))
      substemp.append(subtemp)
    merged = mergesubs(substemp)
    _log('merged subtitles: count=%d output=%s' % (len(subs), merged), LOG_INFO)
    return merged
  finally:
    for subtemp in substemp:
      xbmcvfs.delete(subtemp)

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

def _run_dual_subtitle_flow():
  video_dir, video_basename = _current_video_context()
  start_dir = _resolve_start_dir(video_dir)

  subtitle1 = None
  subtitle2 = None
  subtitle1_dir = ''
  force_manual_both = False
  smart_sync_temp_files = []

  automatch = _auto_match_subtitles(video_dir, video_basename)
  _log('dual flow start: video_dir=%s video_basename=%s start_dir=%s automatch_mode=%s' % (video_dir, video_basename, start_dir, automatch['mode']), LOG_DEBUG)
  translation_applied = False
  translation_plan = _prompt_ai_translation_plan(automatch, video_dir, start_dir)
  translation_result = _run_ai_translation_plan(translation_plan, automatch)
  if translation_result['status'] == 'success':
    subtitle1 = translation_result['subtitle1']
    subtitle2 = translation_result['subtitle2']
    if subtitle1 is not None:
      subtitle1_dir = os.path.dirname(subtitle1)
    elif subtitle2 is not None:
      subtitle1 = subtitle2
      subtitle2 = None
      subtitle1_dir = os.path.dirname(subtitle1)
    translation_applied = subtitle1 is not None
    _log('ai translation applied: subtitle1=%s subtitle2=%s' % (subtitle1, subtitle2), LOG_INFO)

  if not translation_applied:
    if automatch['mode'] == 'full':
      subtitle1 = automatch['subtitle1']
      subtitle2 = automatch['subtitle2']
      subtitle1_dir = os.path.dirname(subtitle1)
      _notify(__language__(33035) % (automatch['language1_label'], automatch['language2_label']), NOTIFY_INFO)

    elif automatch['mode'] == 'partial':
      _notify(__language__(33036) % (automatch['found_label'], automatch['missing_label']), NOTIFY_WARNING)
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
    _notify(__language__(33042), NOTIFY_ERROR)
    __msg_box__.ok(__language__(32531), str(exc))
    return
  finally:
    for temp_sync_path in smart_sync_temp_files:
      try:
        if temp_sync_path and temp_sync_path.startswith(__temp__):
          xbmcvfs.delete(temp_sync_path)
      except:
        pass

  Download(finalfile)
  if len(subs) > 1:
    _notify(__language__(33041), NOTIFY_INFO)
  else:
    _notify(__language__(33045), NOTIFY_INFO)

action = params.get('action', 'search')

if action == 'manualsearch':
  Search()

elif action == 'search':
  Search()

elif action == 'browsedual':
  _run_dual_subtitle_flow()

elif action == 'settings':
  __addon__.openSettings()
  _log('settings opened', LOG_DEBUG)

else:
  Search()

xbmcplugin.endOfDirectory(int(sys.argv[1]))
