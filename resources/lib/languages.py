# -*- coding: utf-8 -*-
#
# Canonical language code maps shared across providers and the main service.
# All providers should import from here instead of maintaining their own copies.

ISO3_TO_ISO2 = {
    'afr': 'af', 'sqi': 'sq', 'alb': 'sq', 'ara': 'ar', 'hye': 'hy', 'arm': 'hy', 'aze': 'az',
    'eus': 'eu', 'baq': 'eu', 'bel': 'be', 'ben': 'bn', 'bos': 'bs', 'bul': 'bg', 'cat': 'ca',
    'zho': 'zh', 'chi': 'zh', 'hrv': 'hr', 'ces': 'cs', 'cze': 'cs', 'dan': 'da', 'nld': 'nl',
    'dut': 'nl', 'eng': 'en', 'est': 'et', 'fin': 'fi', 'fra': 'fr', 'fre': 'fr', 'glg': 'gl',
    'kat': 'ka', 'geo': 'ka', 'deu': 'de', 'ger': 'de', 'ell': 'el', 'gre': 'el', 'heb': 'he',
    'hin': 'hi', 'hun': 'hu', 'isl': 'is', 'ice': 'is', 'ind': 'id', 'gle': 'ga', 'ita': 'it',
    'jpn': 'ja', 'kaz': 'kk', 'kor': 'ko', 'lav': 'lv', 'lit': 'lt', 'mkd': 'mk', 'mac': 'mk',
    'msa': 'ms', 'may': 'ms', 'nor': 'no', 'fas': 'fa', 'per': 'fa', 'pol': 'pl', 'por': 'pt',
    'ron': 'ro', 'rum': 'ro', 'rus': 'ru', 'srp': 'sr', 'slk': 'sk', 'slo': 'sk', 'slv': 'sl',
    'spa': 'es', 'swe': 'sv', 'tam': 'ta', 'tha': 'th', 'tur': 'tr', 'ukr': 'uk', 'urd': 'ur',
    'vie': 'vi', 'cym': 'cy', 'wel': 'cy',
}

# Reverse map: canonical ISO-639-1 → preferred ISO-639-2/B code
ISO2_TO_ISO3 = {
    'af': 'afr', 'sq': 'alb', 'ar': 'ara', 'hy': 'arm', 'az': 'aze', 'eu': 'baq', 'be': 'bel',
    'bn': 'ben', 'bs': 'bos', 'bg': 'bul', 'ca': 'cat', 'zh': 'chi', 'hr': 'hrv', 'cs': 'cze',
    'da': 'dan', 'nl': 'dut', 'en': 'eng', 'et': 'est', 'fi': 'fin', 'fr': 'fre', 'gl': 'glg',
    'ka': 'geo', 'de': 'ger', 'el': 'gre', 'he': 'heb', 'hi': 'hin', 'hu': 'hun', 'is': 'ice',
    'id': 'ind', 'ga': 'gle', 'it': 'ita', 'ja': 'jpn', 'kk': 'kaz', 'ko': 'kor', 'lv': 'lav',
    'lt': 'lit', 'mk': 'mac', 'ms': 'may', 'no': 'nor', 'fa': 'per', 'pl': 'pol', 'pt': 'por',
    'ro': 'rum', 'ru': 'rus', 'sr': 'srp', 'sk': 'slo', 'sl': 'slv', 'es': 'spa', 'sv': 'swe',
    'ta': 'tam', 'th': 'tha', 'tr': 'tur', 'uk': 'ukr', 'ur': 'urd', 'vi': 'vie', 'cy': 'wel',
}

# All known ISO-639-1 codes used throughout the addon
KNOWN_LANGUAGE_CODES = set(ISO2_TO_ISO3.keys())

# Maps each ISO-639-1 code to all valid aliases (ISO-639-2 variants)
LANGUAGE_CODE_ALIASES = {
    'af': ['afr'], 'sq': ['sqi', 'alb'], 'ar': ['ara'], 'hy': ['hye', 'arm'], 'az': ['aze'],
    'eu': ['eus', 'baq'], 'be': ['bel'], 'bn': ['ben'], 'bs': ['bos'], 'bg': ['bul'],
    'ca': ['cat'], 'zh': ['zho', 'chi'], 'hr': ['hrv'], 'cs': ['ces', 'cze'], 'da': ['dan'],
    'nl': ['nld', 'dut'], 'en': ['eng'], 'et': ['est'], 'fi': ['fin'], 'fr': ['fra', 'fre'],
    'gl': ['glg'], 'ka': ['kat', 'geo'], 'de': ['deu', 'ger'], 'el': ['ell', 'gre'],
    'he': ['heb'], 'hi': ['hin'], 'hu': ['hun'], 'is': ['isl', 'ice'], 'id': ['ind'],
    'ga': ['gle'], 'it': ['ita'], 'ja': ['jpn'], 'kk': ['kaz'], 'ko': ['kor'], 'lv': ['lav'],
    'lt': ['lit'], 'mk': ['mkd', 'mac'], 'ms': ['msa', 'may'], 'no': ['nor'], 'fa': ['fas', 'per'],
    'pl': ['pol'], 'pt': ['por'], 'ro': ['ron', 'rum'], 'ru': ['rus'], 'sr': ['srp'],
    'sk': ['slk', 'slo'], 'sl': ['slv'], 'es': ['spa'], 'sv': ['swe'], 'ta': ['tam'],
    'th': ['tha'], 'tr': ['tur'], 'uk': ['ukr'], 'ur': ['urd'], 'vi': ['vie'], 'cy': ['cym', 'wel'],
}


def iso3_to_iso2(code):
    """Convert an ISO-639-2 code to its canonical ISO-639-1 equivalent, or return the input unchanged."""
    return ISO3_TO_ISO2.get(code.lower().strip(), code)


def normalize_language_code(value):
    """
    Normalize any language code string to a canonical ISO-639-1 two-letter code.
    Handles ISO-639-1, ISO-639-2, and BCP-47 subtags (e.g. 'pt-BR' → 'pt').
    Returns an empty string if the input is empty or unrecognizable.
    """
    if not value:
        return ''
    text = str(value).strip().lower().split('-')[0]
    if len(text) == 2:
        return text
    if len(text) == 3:
        return ISO3_TO_ISO2.get(text, text)
    return text
