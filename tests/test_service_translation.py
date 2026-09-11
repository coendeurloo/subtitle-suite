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
sys.argv = ['service.py', '1', '?action=test']
service = importlib.import_module('service')


class _Response(object):
  def __init__(self, body):
    self.body = body

  def read(self):
    return self.body


def _response(translations):
  return _Response(json.dumps({
    'choices': [{'message': {'content': json.dumps({'translations': translations})}}],
  }).encode('utf-8'))


class OpenAITranslationRequestTests(unittest.TestCase):
  def setUp(self):
    self.original_state = service.OPENAI_RESPONSE_FORMAT_SUPPORTED
    self.original_urlopen = service.urlopen
    self.original_log = service._log

  def tearDown(self):
    service.OPENAI_RESPONSE_FORMAT_SUPPORTED = self.original_state
    service.urlopen = self.original_urlopen
    service._log = self.original_log

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
