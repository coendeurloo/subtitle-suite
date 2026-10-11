# -*- coding: utf-8 -*-
"""Keep validated translation progress without publishing an incomplete SRT."""

import hashlib
import json
import os
import tempfile


class TranslationCheckpoint:
    def __init__(self, directory, source_path, source_identity, source_code, target_code, model):
        digest = hashlib.sha256()
        digest.update(json.dumps(
            [1, source_identity, source_code, target_code, model],
            ensure_ascii=False,
        ).encode('utf-8'))
        with open(source_path, 'rb') as source:
            for chunk in iter(lambda: source.read(65536), b''):
                digest.update(chunk)
        self.directory = directory
        self.path = os.path.join(directory, digest.hexdigest() + '.json')

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as source:
                payload = json.load(source)
            lines = payload.get('translations')
            if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
                return []
            return lines
        except (OSError, ValueError, AttributeError):
            return []

    def save(self, translations):
        os.makedirs(self.directory, exist_ok=True)
        descriptor, staged_path = tempfile.mkstemp(prefix='.translation-', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
                json.dump({'translations': translations}, destination, ensure_ascii=False)
            os.replace(staged_path, self.path)
        finally:
            if os.path.exists(staged_path):
                os.unlink(staged_path)

    def clear(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
