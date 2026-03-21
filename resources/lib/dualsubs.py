# -*- coding: utf-8 -*-

import xbmc
import xbmcvfs
import xbmcaddon
import xbmcgui
import os
import codecs
import uuid
from json import loads, dumps

try:
    import chardet
except Exception:
    chardet = None

translatePath = xbmcvfs.translatePath

try:
    import pysubs2
except Exception:
    from resources.lib import pysubs2

from resources.lib.charset_normalizer.api import from_path

__addon__ = xbmcaddon.Addon()
__language__ = __addon__.getLocalizedString
__profile__ = translatePath(__addon__.getAddonInfo('profile'))
__temp__ = translatePath(os.path.join(__profile__, 'temp', ''))
__msg_box__ = xbmcgui.Dialog()

LOG_DEBUG = getattr(xbmc, 'LOGDEBUG', 0)
LOG_WARNING = getattr(xbmc, 'LOGWARNING', 2)


def _log(message, level=LOG_DEBUG):
    try:
        xbmc.log('[%s] %s' % (__addon__.getAddonInfo('id'), message), level)
    except Exception:
        pass


def _equal_text(t1, t2):
    return t1 == str(t2) or t1 == __language__(t2)


def mergesubs(file):
    if len(file) < 2:
        bottom_top = True
        bottom_bottom = False
        left_right = False
    else:
        bottom_top = _equal_text(__addon__.getSetting('subtitle_locations'), 32507)   # 'Bottom-Top'
        bottom_bottom = _equal_text(__addon__.getSetting('subtitle_locations'), 32509) # 'Bottom-Bottom'
        left_right = _equal_text(__addon__.getSetting('subtitle_locations'), 32508)   # 'Bottom, Left-Right'

    subs = [pysubs2.SSAFile.from_string('', 'srt')]
    bottom = not __addon__.getSetting('dualsub_swap') == 'true'

    for sub in file:
        try:
            result = pysubs2.load(sub, encoding=_charset_detect(sub, bottom))
        except Exception as e:
            __msg_box__.ok(__language__(32531), str(e))
            raise e
        subs.append(result)
        bottom = not bottom

    ass = os.path.join(__temp__, '%s.ass' % str(uuid.uuid4()))

    top_style = pysubs2.SSAStyle()
    bottom_style = top_style.copy()
    if bottom_top:
        top_style.alignment = 8
    else:
        top_style.alignment = 2
    if left_right:
        top_style.marginl = 200
        bottom_style.marginr = 200
    top_style.fontsize = int(__addon__.getSetting('top_fontsize'))
    if __addon__.getSetting('top_bold') == 'true':
        top_style.bold = 1
    top_style.fontname = _fontname(str(__addon__.getSetting('top_font')))
    if _equal_text(__addon__.getSetting('top_color'), 32533):   # 'Yellow'
        top_style.primarycolor = pysubs2.Color(255, 255, 0, 0)
    elif _equal_text(__addon__.getSetting('top_color'), 32532): # 'White'
        top_style.primarycolor = pysubs2.Color(255, 255, 255, 0)
        top_style.secondarycolor = pysubs2.Color(255, 255, 255, 0)
    if __addon__.getSetting('top_background') == 'true':
        top_style.backcolor = pysubs2.Color(0, 0, 0, 128)
        top_style.outlinecolor = pysubs2.Color(0, 0, 0, 128)
        top_style.borderstyle = 4
    top_style.shadow = int(__addon__.getSetting('top_shadow'))
    top_style.outline = int(__addon__.getSetting('top_outline'))
    top_style.marginv = int(__addon__.getSetting('top_verticalmargin'))
    if bottom_bottom:
        delta = int(__addon__.getSetting('top_fontsize'))
        if int(__addon__.getSetting('bottom_fontsize')) > delta:
            delta = int(__addon__.getSetting('bottom_fontsize'))
        delta = max(0, (delta - 17) * 2) if delta > 17 else 0
        top_style.marginv = top_style.marginv + 40 + delta
    bottom_style.alignment = 2
    bottom_style.fontsize = int(__addon__.getSetting('bottom_fontsize'))
    if __addon__.getSetting('bottom_bold') == 'true':
        bottom_style.bold = 1
    bottom_style.fontname = _fontname(str(__addon__.getSetting('bottom_font')))
    if _equal_text(__addon__.getSetting('bottom_color'), 32533):   # 'Yellow'
        bottom_style.primarycolor = pysubs2.Color(255, 255, 0, 0)
    elif _equal_text(__addon__.getSetting('bottom_color'), 32532): # 'White'
        bottom_style.primarycolor = pysubs2.Color(255, 255, 255, 0)
    if __addon__.getSetting('bottom_background') == 'true':
        bottom_style.backcolor = pysubs2.Color(0, 0, 0, 128)
        bottom_style.outlinecolor = pysubs2.Color(0, 0, 0, 128)
        bottom_style.borderstyle = 4
    bottom_style.shadow = int(__addon__.getSetting('bottom_shadow'))
    bottom_style.outline = int(__addon__.getSetting('bottom_outline'))
    bottom_style.marginv = int(__addon__.getSetting('bottom_verticalmargin'))

    if __addon__.getSetting('dualsub_swap') == 'true':
        subs[0].styles['top-style'] = bottom_style
        subs[0].styles['bottom-style'] = top_style
    else:
        subs[0].styles['top-style'] = top_style
        subs[0].styles['bottom-style'] = bottom_style

    if __addon__.getSetting('autoShft') == 'true':
        timeThresh = int(__addon__.getSetting('autoShftAmt'))
    else:
        timeThresh = -1

    l1 = len(subs[1])
    l2 = len(subs[2]) if len(subs) >= 3 else 0
    i = j = 0
    prevStart1 = -1
    prevEnd1 = 999999
    prevIndex2 = -1
    prevIndexBottom = -1
    prevIndexTop = -1
    minTime = int(__addon__.getSetting('minTime'))

    while i < l1 or j < l2:
        if i < l1:
            line1 = subs[1][i]
            line1.style = u'bottom-style'
            prevIndexBottom = _set_min_time(minTime, prevIndexBottom, subs, line1)
            subs[0].append(line1)

        if timeThresh < 0:
            j = i
            if j < l2:
                line2 = subs[2][j]
                line2.style = u'top-style'
                prevIndexTop = _set_min_time(minTime, prevIndexTop, subs, line2)
                subs[0].append(line2)
        else:
            while j < l2:
                line2 = subs[2][j]
                if i < l1 and line2.start > line1.start + timeThresh:
                    break
                line2.style = u'top-style'
                if i < l1:
                    if abs(line2.start - line1.start) <= timeThresh:
                        if prevIndex2 < 0 or line1.start > subs[0][prevIndex2].end:
                            line2.start = line1.start
                        else:
                            line2.start = subs[0][prevIndex2].end + 10
                    if abs(line2.end - line1.end) <= timeThresh:
                        line2.end = line1.end
                if prevIndex2 >= 0 and subs[0][prevIndex2].start == prevStart1:
                    if line2.start > prevEnd1:
                        subs[0][prevIndex2].end = prevEnd1
                    else:
                        subs[0][prevIndex2].end = line2.start - 10
                prevIndex2 = len(subs[0])
                prevIndexTop = _set_min_time(minTime, prevIndexTop, subs, line2)
                subs[0].append(line2)
                j += 1

            if i < l1:
                prevStart1 = line1.start
                prevEnd1 = line1.end
            else:
                prevStart1 = -1
                prevEnd1 = 999999

        i += 1

    _set_min_time(minTime, prevIndexBottom, subs, None)
    _set_min_time(minTime, prevIndexTop, subs, None)

    subs[0].save(ass, format_='ass')
    return ass


def _fontname(name):
    if name != '<Kodi Subtitles Font>':
        return name

    command = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'Settings.GetSettingValue',
        'params': {'setting': 'subtitles.fontname'},
    }
    name = ''
    try:
        result = loads(xbmc.executeJSONRPC(dumps(command)))
        if 'result' in result and 'value' in result['result']:
            name = result['result']['value']
    except Exception:
        name = ''

    if name.upper() == 'DEFAULT':
        __msg_box__.ok('', __language__(32535))
        raise RuntimeError(__language__(32535))

    if not name:
        __msg_box__.ok('', __language__(32536))
        raise RuntimeError(__language__(32536))

    return name


def _charset_detect(filename, bottom):
    setting = 'bottom_characterset' if bottom else 'top_characterset'
    encoding = __addon__.getSetting(setting)

    if encoding == 'Auto':
        encoding = 'Auto Chardet'

    if encoding == 'Auto Charset_normalizer':
        try:
            results = from_path(filename)
            result = results.best()
            encoding = result.encoding if (result is not None and result.encoding) else 'utf-8'
            if encoding == 'utf-8':
                _log('charset_normalizer returned no encoding; fallback utf-8', LOG_WARNING)
        except Exception as ex:
            encoding = 'utf-8'
            _log('charset_normalizer detection failed (%s); fallback utf-8' % ex, LOG_WARNING)

    elif encoding == 'Auto Chardet':
        if chardet is not None:
            with open(filename, 'rb') as fi:
                rawdata = fi.read()
            detected = chardet.detect(rawdata)
            encoding = detected.get('encoding') or 'utf-8'
            if encoding.lower() == 'gb2312':  # Decoding may fail using GB2312
                encoding = 'gbk'
        else:
            try:
                results = from_path(filename)
                result = results.best()
                encoding = result.encoding if (result is not None and result.encoding) else 'utf-8'
                if encoding == 'utf-8':
                    _log('charset_normalizer fallback returned no encoding; fallback utf-8', LOG_WARNING)
            except Exception as ex:
                encoding = 'utf-8'
                _log('charset_normalizer fallback failed (%s); fallback utf-8' % ex, LOG_WARNING)
    else:
        # see https://docs.python.org/3/library/codecs.html
        choices = {
            'Arabic (ISO)': 'iso-8859-6', 'Arabic (Windows)': 'windows-1256',
            'Baltic (ISO)': 'iso-8859-13', 'Baltic (Windows)': 'windows-1257',
            'Central Europe (ISO)': 'iso-8859-2', 'Central Europe (Windows)': 'windows-1250',
            'Chinese Simplified': 'gb2312', 'Chinese Simplified (ISO)': 'gb2312',
            'Chinese Traditional (Big5)': 'cp950', 'Cyrillic (ISO)': 'iso-8859-5',
            'Cyrillic (Windows)': 'windows-1251', 'Greek (ISO)': 'iso-8859-7',
            'Greek (Windows)': 'windows-1253', 'Hebrew (ISO)': 'iso-8859-8',
            'Hebrew (Windows)': 'windows-1255', 'Hong Kong (Big5-HKSCS)': 'big5-hkscs',
            'Japanese (Shift-JIS)': 'csshiftjis', 'Korean': 'iso2022_kr',
            'Nordic Languages (ISO)': 'iso-8859-10', 'South Europe (ISO)': 'ISO-8859-3',
            'Thai (ISO)': 'iso-8859-11', 'Thai (Windows)': 'cp874',
            'Turkish (ISO)': 'iso-8859-9', 'Turkish (Windows)': 'windows-1254',
            'UTF8': 'utf8', 'UTF16': 'utf16', 'UTF32': 'utf32',
            'Vietnamese (Windows)': 'windows-1258', 'Western Europe (ISO)': 'iso-8859-15',
            'Western Europe (Windows)': 'windows-1252',
        }
        encoding = choices.get(encoding, 'utf-8')

    try:
        codecs.lookup(encoding)
    except Exception:
        _log('invalid codec "%s"; fallback utf-8' % encoding, LOG_WARNING)
        encoding = 'utf-8'

    return encoding


def _set_min_time(minTime, prevIndex, subs, line1):
    if minTime > 0 and prevIndex >= 0:
        line0 = subs[0][prevIndex]
        length = max(line0.end - line0.start, minTime)
        if line1 is not None and line0.start + length > line1.start:
            length = line1.start - line0.start - 50
        line0.end = line0.start + length
    return len(subs[0])
