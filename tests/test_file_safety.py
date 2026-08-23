# -*- coding: utf-8 -*-

import os
import shutil
import tempfile
import unittest

from resources.lib.file_safety import AtomicReplaceError, copy_and_replace_atomically


def _copy_file(source_path, target_path):
    shutil.copyfile(source_path, target_path)
    return True


def _replace_file(source_path, target_path):
    os.replace(source_path, target_path)
    return True


def _validate_srt(path):
    with open(path, 'r', encoding='utf-8') as subtitle_file:
        content = subtitle_file.read()
    if '-->' not in content:
        raise ValueError('not an SRT subtitle')


class AtomicRestoreTests(unittest.TestCase):
    def test_valid_backup_replaces_target_after_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            target_path = os.path.join(directory, 'movie.en.srt')
            backup_path = os.path.join(directory, 'movie.en.srt.bak')
            with open(target_path, 'w', encoding='utf-8') as target_file:
                target_file.write('1\n00:00:00,000 --> 00:00:01,000\nOriginal\n')
            with open(backup_path, 'w', encoding='utf-8') as backup_file:
                backup_file.write('1\n00:00:00,000 --> 00:00:01,000\nRestored\n')

            copy_and_replace_atomically(
                backup_path,
                target_path,
                _copy_file,
                _replace_file,
                os.path.getsize,
                _validate_srt,
                os.remove,
            )

            with open(target_path, 'r', encoding='utf-8') as target_file:
                self.assertIn('Restored', target_file.read())

    def test_invalid_backup_leaves_existing_target_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            target_path = os.path.join(directory, 'movie.en.srt')
            backup_path = os.path.join(directory, 'movie.en.srt.bak')
            original = '1\n00:00:00,000 --> 00:00:01,000\nOriginal\n'
            with open(target_path, 'w', encoding='utf-8') as target_file:
                target_file.write(original)
            with open(backup_path, 'w', encoding='utf-8') as backup_file:
                backup_file.write('not a subtitle')

            with self.assertRaises(ValueError):
                copy_and_replace_atomically(
                    backup_path,
                    target_path,
                    _copy_file,
                    _replace_file,
                    os.path.getsize,
                    _validate_srt,
                    os.remove,
                )

            with open(target_path, 'r', encoding='utf-8') as target_file:
                self.assertEqual(original, target_file.read())

    def test_failed_atomic_replace_leaves_existing_target_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            target_path = os.path.join(directory, 'movie.en.srt')
            backup_path = os.path.join(directory, 'movie.en.srt.bak')
            original = '1\n00:00:00,000 --> 00:00:01,000\nOriginal\n'
            with open(target_path, 'w', encoding='utf-8') as target_file:
                target_file.write(original)
            with open(backup_path, 'w', encoding='utf-8') as backup_file:
                backup_file.write('1\n00:00:00,000 --> 00:00:01,000\nRestored\n')

            with self.assertRaises(AtomicReplaceError):
                copy_and_replace_atomically(
                    backup_path,
                    target_path,
                    _copy_file,
                    lambda source_path, destination_path: False,
                    os.path.getsize,
                    _validate_srt,
                    os.remove,
                )

            with open(target_path, 'r', encoding='utf-8') as target_file:
                self.assertEqual(original, target_file.read())
