# -*- coding: utf-8 -*-

import io
import json
import importlib
import sys
import types
import unittest
from urllib.error import HTTPError


def _install_kodi_stubs():
  xbmc = types.ModuleType('xbmc')
  xbmc.LOGDEBUG = 0
  xbmc.LOGINFO = 1
  xbmc.LOGNOTICE = 1
  xbmc.LOGWARNING = 2
  xbmc.LOGERROR = 4
  xbmc.log = lambda message, level=0: None
  xbmc.convertLanguage = lambda code, language_format: code

  class Addon(object):
    def getAddonInfo(self, key):
      return {
        'author': 'tests',
        'id': 'service.subtitles.subtitlesuite',
        'name': 'Subtitle Suite',
        'path': '.',
        'profile': '.',
        'version': '2.9.18',
      }.get(key, '')

    def getSetting(self, key):
      return ''

    def setSetting(self, key, value):
      pass

    def openSettings(self):
      pass

    def getLocalizedString(self, message_id):
      return str(message_id)

  xbmcaddon = types.ModuleType('xbmcaddon')
  xbmcaddon.Addon = Addon

  class Dialog(object):
    def notification(self, *args, **kwargs):
      pass

  class ListItem(object):
    def __init__(self, *args, **kwargs):
      pass

    def setProperty(self, *args, **kwargs):
      pass

  xbmcgui = types.ModuleType('xbmcgui')
  xbmcgui.Dialog = Dialog
  xbmcgui.ListItem = ListItem
  xbmcgui.NOTIFICATION_INFO = 'info'
  xbmcgui.NOTIFICATION_WARNING = 'warning'
  xbmcgui.NOTIFICATION_ERROR = 'error'

  xbmcplugin = types.ModuleType('xbmcplugin')
  xbmcplugin.addDirectoryItem = lambda *args, **kwargs: True
  xbmcplugin.endOfDirectory = lambda *args, **kwargs: None
  xbmcvfs = types.ModuleType('xbmcvfs')
  xbmcvfs.translatePath = lambda path: path
  xbmcvfs.exists = lambda path: False
  xbmcvfs.listdir = lambda path: ([], [])
  xbmcvfs.mkdirs = lambda path: True
  xbmcvfs.copy = lambda source, destination: True
  xbmcvfs.delete = lambda path: True

  sys.modules.update({
    'xbmc': xbmc,
    'xbmcaddon': xbmcaddon,
    'xbmcgui': xbmcgui,
    'xbmcplugin': xbmcplugin,
    'xbmcvfs': xbmcvfs,
  })


_install_kodi_stubs()
sys.argv = ['service.py', '1', '?action=settings']
service = importlib.import_module('service')


class _Response(object):
  def __init__(self, body):
    self.body = body
    self.offset = 0

  def read(self, size=-1):
    if size < 0:
      size = len(self.body) - self.offset
    part = self.body[self.offset:self.offset + size]
    self.offset += len(part)
    return part


def _response(translations):
  return _Response(json.dumps({
    'choices': [{'message': {'content': json.dumps({'translations': translations})}}],
  }).encode('utf-8'))


class OpenAITranslationRequestTests(unittest.TestCase):
  def setUp(self):
    self.original_state = service.OPENAI_RESPONSE_FORMAT_SUPPORTED
    self.original_urlopen = service.urlopen
    self.original_log = service._log
    self.original_sleep = service.time.sleep

  def tearDown(self):
    service.OPENAI_RESPONSE_FORMAT_SUPPORTED = self.original_state
    service.urlopen = self.original_urlopen
    service._log = self.original_log
    service.time.sleep = self.original_sleep

  def test_schema_rejection_is_remembered_for_later_blocks(self):
    payloads = []
    warnings = []

    def fake_urlopen(request, timeout):
      payloads.append(json.loads(request.data.decode('utf-8')))
      if len(payloads) == 1:
        raise HTTPError(
          request.full_url,
          400,
          'Bad Request',
          {},
          io.BytesIO(b'{"error":{"message":"response_format is unsupported"}}'),
        )
      return _response(['Hallo'])

    service.OPENAI_RESPONSE_FORMAT_SUPPORTED = None
    service.urlopen = fake_urlopen
    service._log = lambda message, level: warnings.append((message, level))

    self.assertEqual(
      ['Hallo'],
      service._openai_translate_lines(['Hello'], 'en', 'nl', 'key', 'model', 10),
    )
    self.assertEqual(
      ['Hallo'],
      service._openai_translate_lines(['Hello'], 'en', 'nl', 'key', 'model', 10),
    )

    self.assertIn('response_format', payloads[0])
    self.assertNotIn('response_format', payloads[1])
    self.assertNotIn('response_format', payloads[2])
    self.assertEqual(False, service.OPENAI_RESPONSE_FORMAT_SUPPORTED)
    self.assertEqual(1, len([item for item in warnings if 'schema rejected' in item[0]]))

  def test_unsupported_state_omits_response_format_on_first_attempt(self):
    payloads = []

    def fake_urlopen(request, timeout):
      payloads.append(json.loads(request.data.decode('utf-8')))
      return _response(['Hallo'])

    service.OPENAI_RESPONSE_FORMAT_SUPPORTED = False
    service.urlopen = fake_urlopen

    self.assertEqual(
      ['Hallo'],
      service._openai_translate_lines(['Hello'], 'en', 'nl', 'key', 'model', 10),
    )
    self.assertNotIn('response_format', payloads[0])

  def test_transient_read_timeout_is_retried_before_failing(self):
    calls = []
    logs = []

    def fake_urlopen(request, timeout):
      calls.append(timeout)
      if len(calls) == 1:
        raise TimeoutError('The read operation timed out')
      return _response(['Hallo'])

    service.OPENAI_RESPONSE_FORMAT_SUPPORTED = False
    service.urlopen = fake_urlopen
    service.time.sleep = lambda seconds: None
    service._log = lambda message, level: logs.append((message, level))

    self.assertEqual(
      ['Hallo'],
      service._openai_translate_lines(['Hello'], 'en', 'nl', 'key', 'model', 10),
    )
    self.assertEqual([10, 10], calls)
    self.assertTrue(any('transient network error' in message for message, _ in logs))


class _SubtitleLine(object):
  def __init__(self, text):
    self.text = text


class _SubtitleData(list):
  def __init__(self, lines):
    super(_SubtitleData, self).__init__(lines)
    self.saved = False

  def save(self, path, encoding=None, format_=None):
    self.saved = True


class _Progress(object):
  def create(self, *args, **kwargs):
    pass

  def iscanceled(self):
    return False

  def update(self, *args, **kwargs):
    pass

  def close(self):
    pass


class SubtitleTranslationBlockTests(unittest.TestCase):
  def _run_translation(self, translation_response, line_texts=None):
    if line_texts is None:
      line_texts = ['line %d' % index for index in range(1, 6)]
    data = _SubtitleData([_SubtitleLine(text) for text in line_texts])
    logs = []
    notifications = []
    contexts = []
    originals = {}

    def patch(name, value):
      originals[name] = getattr(service, name)
      setattr(service, name, value)

    def fake_translate(lines, source_code, target_code, api_key, model, timeout, context=None):
      contexts.append({
        'request': list(lines),
        'previous_translated_lines': list(context.get('previous_translated_lines') or []),
      })
      return translation_response(lines)

    patch('_get_openai_api_key', lambda: 'key')
    patch('_get_openai_model', lambda: 'model')
    patch('_get_translation_batch_size', lambda: 2)
    patch('_get_translation_timeout_seconds', lambda: 10)
    patch('_load_pysubs2', lambda: types.SimpleNamespace(load=lambda *args, **kwargs: data))
    patch('_copy_subtitle_to_temp', lambda path: 'source.srt')
    patch('_detect_text_encoding', lambda path: 'utf-8')
    patch('_current_video_metadata', lambda: {})
    patch('_current_video_context', lambda: ('', 'movie.mkv'))
    patch('_extract_season_episode', lambda basename: ('', ''))
    patch('_extract_release_year', lambda basename: '')
    patch('_replace_file_with_dualsubs_backup', lambda *args, **kwargs: None)
    patch('_build_translated_subtitle_path', lambda source, target: 'translated.srt')
    patch('_openai_translate_lines', fake_translate)
    progress_updates = []
    patch('_progress_update', lambda *args, **kwargs: progress_updates.append(args[1]))
    patch('_log_timing', lambda event, started_at, details='': logs.append(('timing', event, details)))
    patch('_log', lambda message, level: logs.append((level, message)))
    patch('_notify', lambda message, icon, timeout=4000: notifications.append((message, icon)))
    patch('__language__', lambda message_id: {
      33064: 'Translating',
      33072: 'AI translation cancelled.',
      33312: 'AI translation kept the source language for %d block(s).',
    }.get(message_id, str(message_id)))
    patch('xbmcgui', types.SimpleNamespace(DialogProgress=_Progress))
    patch('OPENAI_RESPONSE_FORMAT_SUPPORTED', True)
    patch('xbmcvfs', types.SimpleNamespace(delete=lambda path: True))

    try:
      result = service._translate_subtitle_file('source.srt', 'en', 'nl')
      return data, logs, notifications, contexts, result, progress_updates
    finally:
      for name, value in originals.items():
        setattr(service, name, value)

  def test_permanent_block_failure_aborts_without_writing_output(self):
    def translate_response(lines):
      if lines[0] == 'line 3':
        raise RuntimeError('permanent failure')
      return ['translated %s' % line for line in lines]

    with self.assertRaises(RuntimeError) as error:
      self._run_translation(translate_response)

    self.assertIn('failed at block', str(error.exception))

  def test_failed_batch_is_split_until_all_lines_translate(self):
    def translate_response(lines):
      if len(lines) > 1 and lines[0] == 'line 3':
        raise RuntimeError('batch too large')
      return ['vertaald %s' % line for line in lines]

    data, _, _, contexts, result, progress_updates = self._run_translation(translate_response)
    self.assertEqual('translated.srt', result)
    self.assertTrue(data.saved)
    self.assertEqual(['vertaald line %d' % index for index in range(1, 6)],
                     [line.text for line in data])
    self.assertGreaterEqual(len([item for item in contexts if item['request'] == ['line 3', 'line 4']]), 2)
    self.assertEqual(100, progress_updates[-1])
    self.assertTrue(all(percent < 100 for percent in progress_updates[:-1]))

  def test_cancellation_during_block_aborts_translation(self):
    def translate_response(lines):
      raise service.JobCancelled('cancelled')

    with self.assertRaises(service.JobCancelled):
      self._run_translation(translate_response)

  def test_source_echo_failure_does_not_split_into_unsafe_small_chunks(self):
    requests = []

    def translate_response(lines):
      requests.append(list(lines))
      return list(lines)

    with self.assertRaises(RuntimeError):
      self._run_translation(translate_response, [
        'I am right here with you', 'We are going to the place',
        'Something else happens', 'This is another line', 'The last line',
      ])

    first = ['I am right here with you', 'We are going to the place']
    self.assertEqual([first, first], requests)

  def test_progress_is_weighted_by_source_text_and_finishes_after_save(self):
    lines = ['a' * 100, 'b', 'c', 'd', 'e']
    data, _, _, _, _, progress_updates = self._run_translation(
      lambda chunk: ['vertaald ' + line for line in chunk], lines,
    )
    self.assertTrue(data.saved)
    self.assertEqual(0, progress_updates[0])
    self.assertGreater(progress_updates[1], 90)
    self.assertEqual(100, progress_updates[-1])


class ChangeSubtitlePairActionTests(unittest.TestCase):
  def test_can_pick_dutch_and_english_when_russian_is_also_available(self):
    originals = {}

    def patch(name, value):
      originals[name] = getattr(service, name)
      setattr(service, name, value)

    selected_options = []
    finalized = []
    paths = ['/films/Movie.2024.ru.srt', '/films/Movie.2024.en.srt', '/films/Movie.2024.nl.srt']
    try:
      patch('_current_video_context', lambda: ('/films', 'Movie.2024'))
      patch('_list_srt_files', lambda folder, include_generated: paths)
      patch('_detect_language_from_filename', lambda path: path.split('.')[-2])
      patch('_parse_language_code', lambda setting: 'nl' if setting.endswith('_1') else 'ru')
      patch('_finalize_selected_subtitle_paths', lambda first, second, **kwargs: finalized.append((first, second)))
      patch('__msg_box__', types.SimpleNamespace(select=lambda heading, options: selected_options.append(options) or 1))
      service._run_change_subtitle_pair_action()
    finally:
      for name, value in originals.items():
        setattr(service, name, value)

    self.assertIn('[NL]', selected_options[0][1])
    self.assertIn('[EN]', selected_options[0][1])
    self.assertEqual([('/films/Movie.2024.nl.srt', '/films/Movie.2024.en.srt')], finalized)
