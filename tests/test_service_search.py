import io
import struct
import unittest
from unittest.mock import Mock, patch

# Reuse the Kodi stub harness; these tests never connect to a Kodi installation.
from test_service_translation import service
from resources.lib.providers.opensubtitles import OpenSubtitlesProvider


class ServiceSearchTests(unittest.TestCase):
    def setUp(self):
        self.context = service.VideoContext('smb://server/video.mkv', 'smb://server/', 'video')
        self.context_patch = patch.object(service, '_get_action_video_context', return_value=self.context)
        self.context_patch.start()
        self.addCleanup(self.context_patch.stop)

    def test_network_hash_uses_two_binary_reads_and_seek(self):
        data = struct.pack('<Q', 3) * 16384 + b'abcdefgh' * 8192
        handle = io.BytesIO(data)
        vfs = Mock()
        vfs.size.return_value = len(data)
        vfs.readBytes.side_effect = lambda size: bytearray(handle.read(size))
        vfs.seek.side_effect = handle.seek
        expected = (len(data) + 3 * 8192 + struct.unpack('<Q', b'abcdefgh')[0] * 8192) & 0xffffffffffffffff
        with patch.object(service.xbmcvfs, 'File', return_value=vfs, create=True):
            result = service._compute_file_hash_and_size(self.context.video_path)
            self.assertEqual(result, ('%016x' % expected, len(data)))
            self.assertEqual(vfs.readBytes.call_count, 2)
            vfs.read.assert_not_called()
            vfs.close.assert_called_once()
            self.assertEqual(service._compute_file_hash_and_size(self.context.video_path), result)
            self.assertEqual(vfs.readBytes.call_count, 2)

    def test_incomplete_network_file_does_not_claim_hash_match(self):
        vfs = Mock()
        vfs.size.return_value = 200000
        vfs.readBytes.return_value = bytearray(b'x' * 10)
        vfs.seek.return_value = 200000 - 65536
        with patch.object(service.xbmcvfs, 'File', return_value=vfs, create=True), \
             patch.object(service.os.path, 'getsize', side_effect=OSError()):
            self.assertEqual(service._compute_file_hash_and_size(self.context.video_path)[0], '')
            vfs.close.assert_called_once()

    def test_metadata_uses_imdb_unique_id_and_keeps_specials(self):
        player = Mock()
        tag = player.getVideoInfoTag.return_value
        tag.getUniqueID.return_value = 'tt1234567'
        tag.getTitle.return_value = 'Episode Name'
        tag.getOriginalTitle.return_value = ''
        tag.getTVShowTitle.return_value = 'Show'
        tag.getSeason.return_value = 0
        tag.getEpisode.return_value = 1
        tag.getYear.return_value = 2024
        tag.getGenres.return_value = []
        tag.getCast.return_value = []
        with patch.object(service.xbmc, 'Player', return_value=player, create=True):
            metadata = service._current_video_metadata()
        self.assertEqual(metadata['imdb_id'], 'tt1234567')
        self.assertEqual(metadata['season'], '00')
        self.assertEqual(metadata['episode'], '01')
        self.assertEqual(metadata['tvshow_title'], 'Show')
        tag.getIMDBNumber.assert_not_called()

    def test_untyped_scraper_number_is_not_mistaken_for_imdb(self):
        player = Mock()
        tag = player.getVideoInfoTag.return_value
        tag.getUniqueID.return_value = ''
        tag.getIMDBNumber.return_value = '12345678'
        tag.getTitle.return_value = 'Movie'
        tag.getTVShowTitle.return_value = ''
        tag.getOriginalTitle.return_value = ''
        tag.getSeason.return_value = -1
        tag.getEpisode.return_value = -1
        tag.getGenres.return_value = []
        tag.getCast.return_value = []
        with patch.object(service.xbmc, 'Player', return_value=player, create=True), \
             patch.object(service.xbmc, 'getInfoLabel', return_value='', create=True):
            self.assertEqual(service._current_video_metadata()['imdb_id'], '')

    def test_episode_context_prefers_show_metadata_over_noisy_filename(self):
        metadata = dict(title='Andale', tvshow_title='Euphoria', season='03', episode='01', imdb_id='tt11559986', year='2026')
        with patch.object(service, '_current_video_metadata', return_value=metadata), \
             patch.object(service, '_compute_file_hash_and_size', return_value=('', 0)):
            context = service._build_download_context('/shows/', 'video')
        self.assertEqual(context['query'], 'Euphoria')
        self.assertTrue(context['is_tvshow'])
        self.assertEqual(context['season'], '03')
        self.assertEqual(context['episode'], '01')

    def test_episode_filename_is_useful_without_metadata(self):
        with patch.object(service, '_current_video_metadata', return_value={}), \
             patch.object(service, '_compute_file_hash_and_size', return_value=('', 0)):
            context = service._build_download_context('/shows/', 'Euphoria.S03E01.Andale.1080p.WEB-DL')
        self.assertEqual(context['query'], 'Euphoria')
        self.assertEqual(context['episode'], '01')

    def test_movie_filename_metadata_is_cleaned_and_numeric_title_year_is_correct(self):
        video = '1917.2019.1080p.BluRay'
        with patch.object(service, '_current_video_metadata', return_value=dict(title=video, year='0')), \
             patch.object(service, '_compute_file_hash_and_size', return_value=('', 0)):
            context = service._build_download_context('/movies/', video)
        self.assertEqual(context['query'], '1917')
        self.assertEqual(context['year'], '2019')
        provider = OpenSubtitlesProvider({'enabled': True})
        self.assertEqual(provider._search_plans(context)[0][1]['query'], '1917')

    def test_verified_hash_overrides_name_guesses_and_ranks_first(self):
        video = 'Example.Movie.2024.1080p.WEB-DL'
        hash_match = dict(language='nl', release_name='Different.Movie.1080p.BluRay',
                          provider_sync_tier='exact', hash_match=True, provider_score=1)
        name_match = dict(language='nl', release_name=video, provider_score=100)
        ranked = service._rank_download_results(video, 'nl', [name_match, hash_match])
        self.assertIs(ranked[0], hash_match)
        self.assertFalse(hash_match['hard_conflict'])

    def test_episode_search_rejects_same_episode_number_from_another_series(self):
        provider = OpenSubtitlesProvider({'enabled': True})
        context = {'is_tvshow': True, 'season': '02', 'episode': '07', 'parent_imdb_id': 'tt1234567'}
        def result(file_id, show_id):
            return {'attributes': {'language': 'nl', 'feature_details': {
                'season_number': 2, 'episode_number': 7, 'parent_imdb_id': show_id,
            }, 'files': [{'file_id': file_id, 'file_name': 'Episode.srt'}]}}

        matches = provider._normalize_search_results(
            [result(1, 9999999), result(2, 1234567), result(3, None)], context, 'nl'
        )
        self.assertEqual([match['file_id'] for match in matches], [2, 3])

    def test_full_candidate_pool_ranked_before_display_limit_and_cache_is_specific(self):
        provider = OpenSubtitlesProvider({'enabled': True})
        pool = [dict(file_id=i, language='nl', release_name='Example.Movie.2024',
                     provider_key='opensubtitles', provider_score=100) for i in range(1, 25)]
        best = dict(file_id=25, language='nl', release_name='Exact file', provider_key='opensubtitles',
                    provider_sync_tier='exact', hash_match=True, provider_score=1)
        provider.search = Mock(return_value=pool + [best])
        context = dict(query='Example Movie', video_basename='Example.Movie.2024.1080p.WEB-DL')
        with patch.object(service, '_get_ready_download_providers', return_value=[provider]), \
             patch.object(service, '_get_download_max_results', return_value=12):
            results = service._search_download_results(context, 'nl')
            self.assertEqual(len(results), 12)
            self.assertEqual(results[0]['file_id'], 25)
            self.assertEqual(provider.search.call_args.args[2], 120)
            service._search_download_results(context, 'nl')
            self.assertEqual(provider.search.call_count, 1)
            service._search_download_results(dict(context, query='Another Movie'), 'nl')
            self.assertEqual(provider.search.call_count, 2)

    def test_human_and_trusted_results_win_when_sync_evidence_is_equal(self):
        base = dict(language='nl', release_name='Example.2024.1080p.WEB-DL', provider_score=100)
        ai = dict(base, ai_translated=True)
        human = dict(base)
        trusted = dict(base, from_trusted=True)
        self.assertEqual(service._rank_download_results(base['release_name'], 'nl', [ai, human, trusted]),
                         [trusted, human, ai])


if __name__ == '__main__':
    unittest.main()
