import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from test_service_translation import service
from resources.lib import pysubs2
from resources.lib.background_jobs import JobCancelled


class LuckySmartSyncTests(unittest.TestCase):
    def test_lucky_download_continues_after_timing_rejection(self):
        candidates = [
            {'provider_key': 'os', 'file_id': 1, 'sync_tier': 'exact'},
            {'provider_key': 'os', 'file_id': 2, 'sync_tier': 'likely'},
        ]
        validator = Mock()
        with patch.object(service, '_build_download_context', return_value={}), patch.object(
            service, '_search_download_results', return_value=candidates
        ), patch.object(
            service, '_write_download_payload_to_target', side_effect=['', 'episode.nl.srt']
        ) as write:
            result = service._download_best_result_for_language(
                'tv', 'episode', 'nl', language_label='Dutch', required_tiers=['exact', 'likely'],
                fallback_to_top=False, validate_candidate=validator
            )
        self.assertEqual(result['result']['file_id'], 2)
        self.assertEqual([entry.args[2]['file_id'] for entry in write.call_args_list], [1, 2])

    def test_saved_timing_is_invalidated_when_reference_or_output_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media, source, reference, output = [root / name for name in ('episode.mp4', 'nl.srt', 'en.srt', 'nl.smartsync.srt')]
            for path in (media, source, reference, output):
                path.write_bytes(b'original')

            def stat(path):
                info = Path(path).stat()
                return Mock(st_size=lambda: info.st_size, st_mtime=lambda: info.st_mtime)

            def open_vfs(path):
                handle = open(path, 'rb')
                return Mock(readBytes=handle.read, close=handle.close)

            slots = [{'code': 'nl', 'path': str(output), 'source_path': str(source), 'timing': 'synced'}]
            local_slots = [{'code': 'nl', 'path': str(source)}]
            with patch.multiple(service, __profile__=directory,
                                _current_video_file_path=lambda: str(media),
                                _compute_file_hash_and_size=lambda _: ('hash', 8)), patch.object(
                service.xbmcvfs, 'Stat', side_effect=stat, create=True
            ), patch.object(service.xbmcvfs, 'File', side_effect=open_vfs, create=True):
                service._save_lucky_timing_cache(slots, str(reference))
                self.assertEqual(service._load_lucky_timing_cache(local_slots, str(reference)), [str(output)])
                for path in (reference, output, source):
                    path.write_bytes(b'modified')
                    self.assertIsNone(service._load_lucky_timing_cache(local_slots, str(reference)))
                    path.write_bytes(b'original')

    def test_lucky_checks_both_local_tracks_against_english(self):
        slots = [
            {'slot': 'subtitle1', 'code': 'nl', 'label': 'Dutch', 'path': ''},
            {'slot': 'subtitle2', 'code': 'ru', 'label': 'Russian', 'path': ''},
        ]
        with patch.multiple(
            service,
            _current_video_context=lambda: ('tv', 'Girls - S02E07'),
            _cleanup_generated_movie_sidecars=lambda *_: None,
            _create_lucky_progress=lambda: None,
            _update_lucky_progress=lambda *_: True,
            _is_lucky_download_enabled=lambda: False,
            _is_lucky_smartsync_enabled=lambda: True,
            _is_lucky_prompt_english_test_enabled=lambda: False,
            _auto_match_subtitles=lambda *_: {'subtitle1': 'tv/nl.srt', 'subtitle2': 'tv/ru.srt'},
            _show_lucky_center_summary=lambda *_: None,
            __language__=lambda key: '%s' if key in (33245, 33262) else str(key),
        ), patch.object(
            service, '_find_lucky_english_reference', return_value={'path': 'tv/en.srt', 'tier': 'exact'}
        ) as find, patch.object(
            service, '_run_lucky_smartsync_to_reference',
            side_effect=[{'applied': True, 'path': 'tv/nl.smartsync.srt'}, {'applied': False}]
        ) as sync, patch.object(service, '_finalize_lucky_dual_display', return_value=True) as finalize:
            service._run_lucky_acquisition(slots)

        find.assert_called_once()
        self.assertEqual(sync.call_args_list, [
            call('tv/en.srt', 'tv/nl.srt', force_apply=False),
            call('tv/en.srt', 'tv/ru.srt', force_apply=False),
        ])
        finalize.assert_called_once_with('tv/nl.smartsync.srt', 'tv/ru.srt', 'tv', [], preserve_timing=True)

    def test_lucky_retries_keep_using_the_unmodified_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Girls - S02E07.nl.srt'
            source.write_bytes(b'1\n00:00:01,000 --> 00:00:02,000\nHallo\n')
            original = source.read_bytes()
            synced = pysubs2.load(str(source))
            synced[0].shift(ms=1000)
            with patch.multiple(
                service.xbmcvfs,
                exists=lambda path: Path(path).exists(),
                mkdirs=lambda path: Path(path).mkdir(exist_ok=True),
                delete=lambda path: Path(path).unlink(),
            ), patch.object(service, '__temp__', directory), patch.object(
                service, '_stage_and_replace_subtitle', side_effect=lambda src, dst, _: shutil.copyfile(src, dst)
            ), patch.object(
                service, '_run_smart_sync_local', return_value={'synced_subs': synced}
            ) as analyze:
                results = [service._run_lucky_smartsync_to_reference('en.srt', str(source), force_apply=True)
                           for _ in range(2)]
                output = root / 'DualSubtitles' / 'Girls - S02E07.nl.smartsync.srt'
                self.assertEqual(service._build_merged_ass_output_path(str(output)),
                                 str(output.parent / 'Girls - S02E07.dual.ass'))

            self.assertEqual(analyze.call_args_list, [
                call('en.srt', str(source), progress=None, prefer_simple_alignment=True)
            ] * 2)
            self.assertEqual([result['path'] for result in results], [str(output)] * 2)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(pysubs2.load(str(output))[0].start, 2000)
            self.assertFalse(list(output.parent.glob('*.bak')))

    def test_cancel_lucky_sync_closes_visible_progress_without_saving(self):
        dialog = Mock()
        with patch.object(service, '_create_smart_sync_progress', return_value=dialog), patch.object(
            service, '_run_smart_sync_local', side_effect=JobCancelled()
        ) as analyze, patch.object(service, '_save_synced_subtitle_as_new_file') as save:
            with self.assertRaises(JobCancelled):
                service._run_lucky_smartsync_to_reference('en.srt', 'ru.srt')
        analyze.assert_called_once_with('en.srt', 'ru.srt', progress=dialog, prefer_simple_alignment=True)
        dialog.close.assert_called_once()
        save.assert_not_called()


class SubtitlePlaybackTests(unittest.TestCase):
    def test_dual_subtitles_are_loaded_once_without_seeking(self):
        output = 'DualSubtitles/episode.dual.ass'
        for handle, register, accepted, expected_handoff in (
            ('1', True, True, True),
            ('1', True, False, True),
            ('-1', True, True, False),
            ('1', False, True, False),
        ):
            with self.subTest(handle=handle, register=register, accepted=accepted):
                player = Mock()
                with patch.object(service.sys, 'argv', ['service.py', handle]), patch.object(
                    service.xbmc, 'Player', return_value=player, create=True
                ), patch.object(service, 'Download', return_value=accepted) as handoff, patch.object(
                    service, '_prepare_and_merge_subtitles', return_value=output
                ), patch.object(service, '_enforce_dual_bottom_stack_visibility'):
                    self.assertTrue(service._finalize_selected_subtitle_paths(
                        'episode.nl.srt', 'episode.ru.srt',
                        show_notifications=False, register_download_item=register
                    ))

                if expected_handoff:
                    handoff.assert_called_once_with(output)
                else:
                    handoff.assert_not_called()
                if expected_handoff and accepted:
                    player.setSubtitles.assert_not_called()
                else:
                    player.setSubtitles.assert_called_once_with(output)
                player.seekTime.assert_not_called()
                self.assertNotIn(call(False), player.showSubtitles.call_args_list)


class RussianSubtitleValidationTests(unittest.TestCase):
    @staticmethod
    def subtitle_bytes(russian_count, english_count, encoding='utf-8'):
        subtitles = pysubs2.SSAFile()
        for index, text in enumerate(['Это действительно хорошая история.'] * russian_count +
                                     ['This is the rest of the story.'] * english_count):
            subtitles.append(pysubs2.SSAEvent(start=index * 2000, end=index * 2000 + 1000, text=text))
        return subtitles.to_string('srt').encode(encoding)

    def test_russian_with_some_foreign_dialogue_is_allowed(self):
        for encoding in ('utf-8', 'utf-16', 'cp1251'):
            self.assertFalse(service._russian_subtitle_has_language_mismatch(self.subtitle_bytes(60, 15, encoding)))

    def test_mixed_russian_download_is_rejected_before_writing(self):
        provider = Mock()
        provider.download.return_value = {'content_bytes': self.subtitle_bytes(20, 40)}
        with patch.object(service, '_replace_file_with_dualsubs_backup') as write:
            with self.assertRaises(service.SubtitleLanguageMismatch):
                service._write_download_payload_to_target({'video_dir': 'tv'}, 'ru', {'_provider_ref': provider})
        write.assert_not_called()

    def test_existing_mislabeled_track_is_excluded_from_local_matches(self):
        name = 'Girls.S02E07'
        context = Mock()
        context.list_directory_files.return_value = [name + '.ru.srt']
        context.read_subtitle_sample.return_value = self.subtitle_bytes(0, 40)
        with patch.object(service, '_get_action_video_context', return_value=context):
            self.assertEqual(service._find_subtitle_matches('tv', name, 'ru', strict=True), [])
        context.read_subtitle_sample.assert_called_once()
