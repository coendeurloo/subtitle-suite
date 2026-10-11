import struct
import threading
import unittest
from unittest.mock import Mock, patch

from resources.lib.providers.base import ProviderAuthError, ProviderRequestError
from resources.lib.providers.opensubtitles import OpenSubtitlesProvider
from resources.lib.subtitle_search import clean_filename_title, hash_video_blocks, search_cache_key


def subtitle(file_id=1, language='nl', release='Example.2024.1080p.WEB-DL', **extra):
    attrs = dict(language=language, release=release, download_count=100,
                 files=[{'file_id': file_id, 'file_name': release + '.srt'}])
    attrs.update(extra)
    return {'attributes': attrs}


def response(*items, **extra):
    return dict(data=list(items), total_pages=extra.get('pages', 1))


class SearchHelpersTests(unittest.TestCase):
    def test_short_titles_and_language_words_are_retained(self):
        self.assertEqual(clean_filename_title('It.2017.1080p.BluRay'), 'It')
        self.assertEqual(clean_filename_title('Up.2009.720p.WEB-DL'), 'Up')
        self.assertEqual(clean_filename_title('As.Good.As.It.Gets.1997.x264'), 'As Good As It Gets')

    def test_episode_title_and_release_tags_removed(self):
        self.assertEqual(clean_filename_title('Euphoria.S03E01.Andale.1080p.WEB-DL'), 'Euphoria')
        self.assertEqual(clean_filename_title('The.Show.2x03.Episode.Name'), 'The Show')

    def test_unicode_and_numeric_titles(self):
        self.assertEqual(clean_filename_title('千と千尋の神隠し.2001.1080p.mkv'), '千と千尋の神隠し')
        self.assertEqual(clean_filename_title('1917.2019.1080p'), '1917')
        self.assertEqual(clean_filename_title('2001.A.Space.Odyssey.1968.BluRay'), '2001 A Space Odyssey')

    def test_hash_uses_unsigned_little_endian_and_overflow(self):
        first = struct.pack('<Q', 0xffffffffffffffff) * 8192
        last = struct.pack('<Q', 7) * 8192
        expected = (200000 + (0xffffffffffffffff + 7) * 8192) & 0xffffffffffffffff
        self.assertEqual(hash_video_blocks(200000, bytearray(first), bytearray(last)), '%016x' % expected)
        with self.assertRaises(ValueError):
            hash_video_blocks(200000, first[:-8], last)
        with self.assertRaises(ValueError):
            hash_video_blocks(200000, 'x' * 65536, last)

    def test_cache_distinguishes_unhashed_videos_queries_and_episodes(self):
        base = dict(query='Show', season='01', episode='01')
        key = search_cache_key('opensubtitles', base, 'nl', 120)
        for change in [dict(query='Other'), dict(episode='02'), dict(imdb_id='tt1234567'),
                       dict(video_path='smb://other/video.mkv')]:
            self.assertNotEqual(key, search_cache_key('opensubtitles', dict(base, **change), 'nl', 120))


class OpenSubtitlesSearchTests(unittest.TestCase):
    def setUp(self):
        self.provider = OpenSubtitlesProvider({'enabled': True})
        self.provider._login = Mock(return_value='token')
        self.context = dict(query='Example', imdb_id='tt1234567', year='2024', video_basename='Example.2024.1080p.WEB-DL')

    def run_search(self, payloads, context=None, limit=120):
        self.provider._request_json = Mock(side_effect=payloads)
        return self.provider.search(context or self.context, 'nl', limit)

    def params(self):
        return [call.kwargs['query_params'] for call in self.provider._request_json.call_args_list]

    def test_movie_id_search_does_not_overconstrain_with_title_or_year(self):
        found = self.run_search([response(subtitle())])
        self.assertEqual(len(found), 1)
        self.assertEqual(self.params()[0]['imdb_id'], '1234567')
        self.assertNotIn('query', self.params()[0])
        self.assertNotIn('year', self.params()[0])

    def test_hash_results_survive_title_lookup_and_duplicates(self):
        ctx = dict(self.context, video_hash='abcd1234abcd1234')
        found = self.run_search([response(subtitle(1, release='Different.release', moviehash_match=True)),
                                 response(subtitle(1), subtitle(2))], ctx)
        self.assertEqual([item['file_id'] for item in found], [1, 2])
        self.assertTrue(found[0]['hash_match'])
        self.assertEqual(self.params()[0]['moviehash_match'], 'only')
        self.assertEqual(found[0]['provider_sync_tier'], 'exact')

    def test_episode_and_series_ids_have_separate_fallback_queries(self):
        ctx = dict(self.context, is_tvshow=True, tvshow_title='Euphoria', title='Andale', season='03', episode='01')
        wrong = subtitle(1, feature_details={'season_number': 3, 'episode_number': 2})
        right = subtitle(2, feature_details={'season_number': 3, 'episode_number': 1})
        found = self.run_search([response(wrong), response(right)], ctx)
        self.assertEqual([item['file_id'] for item in found], [2])
        self.assertEqual(self.params()[1]['parent_imdb_id'], '1234567')
        self.assertEqual(self.params()[1]['season_number'], 3)
        self.assertEqual(self.params()[1]['episode_number'], 1)
        self.assertNotIn('imdb_id', self.params()[1])

    def test_tv_text_fallback_uses_show_and_special_season_zero(self):
        ctx = dict(self.context, is_tvshow=True, tvshow_title='Show', title='Episode name', season='00', episode='01')
        found = self.run_search([response(), response(), response(subtitle())], ctx)
        self.assertEqual(len(found), 1)
        params = self.params()[-1]
        self.assertEqual(params['query'], 'Show')
        self.assertEqual(params['season_number'], 0)
        self.assertNotIn('year', params)

    def test_movie_year_and_original_title_fallbacks(self):
        ctx = dict(query='Localized', original_title='Original', title='Localized', year='2024')
        found = self.run_search([response(), response(), response(subtitle(release='Localized.2024'))], ctx)
        self.assertEqual(len(found), 1)
        self.assertEqual([p['query'] for p in self.params()], ['Original', 'Original', 'Localized'])
        self.assertEqual(self.params()[0]['year'], '2024')
        self.assertNotIn('year', self.params()[1])

    def test_extra_page_and_candidates_beyond_old_limit(self):
        page1 = response(*(subtitle(i) for i in range(1, 61)), pages=20)
        page2 = response(subtitle(61, release='Example.2024.1080p.WEB-DL.BEST'), pages=20)
        found = self.run_search([page1, page2])
        self.assertEqual(len(found), 61)
        self.assertEqual(self.params()[-1]['page'], 2)
        self.assertEqual(self.provider._request_json.call_count, 2)

    def test_later_page_is_checked_when_first_page_has_only_other_movies(self):
        wrong = subtitle(1, release='The Peanuts Movie.2015',
                         feature_details=dict(imdb_id=2452042, title='The Peanuts Movie', year=2015))
        right = subtitle(2, release='Example.2024',
                         feature_details=dict(imdb_id=1234567, title='Example', year=2024))
        found = self.run_search([response(wrong, pages=2), response(right, pages=2)])
        self.assertEqual([item['file_id'] for item in found], [2])
        self.assertEqual(self.params()[-1]['page'], 2)

    def test_whole_page_retained_for_local_ranking(self):
        found = self.run_search([response(*(subtitle(i) for i in range(1, 31)))], limit=12)
        self.assertEqual(len(found), 30)

    def test_wrong_language_partial_subtitles_and_all_files(self):
        multi = subtitle(1, files=[dict(file_id=1, file_name='disc1.srt'), dict(file_id=2, file_name='disc2.srt')])
        found = self.run_search([response(subtitle(3, language='en'), subtitle(4, foreign_parts_only=True), multi)])
        self.assertEqual([item['file_id'] for item in found], [1, 2])
        self.assertEqual([item['release_name'] for item in found], ['disc1.srt', 'disc2.srt'])
        self.assertEqual(self.params()[0]['foreign_parts_only'], 'exclude')

    def test_false_string_is_not_a_hash_match(self):
        found = self.run_search([response(subtitle(moviehash_match='false', hearing_impaired='false'))])
        self.assertFalse(found[0]['hash_match'])
        self.assertFalse(found[0]['hearing_impaired'])

    def test_language_variants_and_aliases(self):
        self.assertEqual(self.provider._api_language('dut'), 'nl')
        self.assertEqual(self.provider._api_language('pt'), 'pt-pt')
        self.assertEqual(self.provider._api_language('pt-BR'), 'pt-br')
        self.assertEqual(self.provider._api_language('zh'), 'zh-cn')

    def test_fallback_failure_preserves_verified_results(self):
        ctx = dict(self.context, file_hash='0123456789abcdef')
        found = self.run_search([response(subtitle(moviehash_match=True))] + [ProviderRequestError('network down')] * 3, ctx)
        self.assertTrue(found[0]['hash_match'])

    def test_peanut_butter_search_rejects_other_1985_movies(self):
        ctx = dict(query='The Peanut Butter Solution', title='The Peanut Butter Solution',
                   imdb_id='tt0089789', year='1985', video_basename='The Peanut Butter Solution (1985) [1080p] [BluRay]')
        charlie_brown = subtitle(
            1, release='Youre.a.Good.Man.Charlie.Brown.1985.1080p',
            feature_details=dict(imdb_id=153997, title="You're a Good Man, Charlie Brown",
                                 year=1985, feature_type='Movie'))
        love_circles = subtitle(
            2, release='Love.Circles.1985.BluRay',
            feature_details=dict(imdb_id=87840, title='Love Circles',
                                 year=1985, feature_type='Movie'))
        found = self.run_search([response(), response(charlie_brown, love_circles),
                                 response(charlie_brown, love_circles)], ctx)
        self.assertEqual(found, [])
        self.assertEqual(len(self.params()), 3)

    def test_verified_movie_id_accepts_alternate_title_but_rejects_wrong_id(self):
        ctx = dict(query='The Peanut Butter Solution', imdb_id='tt0089789', year='1985')
        alternate = subtitle(1, release='Opération beurre de pinottes',
                             feature_details=dict(imdb_id=89789, title='Opération beurre de pinottes',
                                                  year=1985, feature_type='Movie'))
        mislabeled = subtitle(2, release='The Peanut Butter Solution.1985',
                              feature_details=dict(imdb_id=123456, title='The Peanut Butter Solution',
                                                   year=1985, feature_type='Movie'))
        found = self.run_search([response(alternate, mislabeled)], ctx)
        self.assertEqual([item['file_id'] for item in found], [1])

    def test_title_fallback_requires_same_movie_and_year(self):
        ctx = dict(query='The Peanut Butter Solution', year='1985')
        matching = subtitle(1, release='A.generic.release',
                            feature_details=dict(title='The Peanut Butter Solution', year=1985))
        other_title = subtitle(2, release='The Peanut Butter Solution.1985',
                               feature_details=dict(title='Love Circles', year=1985))
        other_year = subtitle(3, release='The Peanut Butter Solution.1990',
                              feature_details=dict(title='The Peanut Butter Solution', year=1990))
        no_identity = subtitle(4, release='Another.Film.1985')
        found = self.run_search([response(matching, other_title, other_year, no_identity)], ctx)
        self.assertEqual([item['file_id'] for item in found], [1])

    def test_hash_is_only_verified_when_api_marks_it_as_a_match(self):
        ctx = dict(query='Example', imdb_id='tt1234567', video_hash='0123456789abcdef')
        wrong = subtitle(1, release='Other.Film.2024', moviehash_match=False,
                         feature_details=dict(imdb_id=7654321, title='Other Film', year=2024))
        right = subtitle(2, release='Another.name', moviehash_match=True,
                         feature_details=dict(imdb_id=7654321, title='Other Film', year=2024))
        found = self.run_search([response(wrong, right), response(), response()], ctx)
        self.assertEqual([item['file_id'] for item in found], [2])
        self.assertTrue(found[0]['hash_match'])

    def test_all_failed_searches_report_error_and_auth_errors_stop(self):
        with self.assertRaises(ProviderRequestError):
            self.run_search([ProviderRequestError('down')] * 3)
        with self.assertRaises(ProviderAuthError):
            self.run_search([ProviderAuthError('credentials')])
        self.assertEqual(self.provider._request_json.call_count, 1)

    def test_cancelled_search_does_not_start_queries(self):
        event = threading.Event()
        event.set()
        found = self.run_search([], dict(self.context, cancel_event=event))
        self.assertEqual(found, [])
        self.provider._request_json.assert_not_called()

    def test_expired_deadline_does_not_start_queries(self):
        found = self.run_search([], dict(self.context, deadline_at=0))
        self.assertEqual(found, [])
        self.provider._request_json.assert_not_called()

    def test_network_deadline_clamps_actual_request_timeout(self):
        self.provider._search_deadline = 15
        with patch('resources.lib.providers.opensubtitles.time.monotonic', return_value=10), \
             patch('resources.lib.providers.opensubtitles.urlopen') as opening:
            opening.return_value.read.return_value = b'{"data": []}'
            self.provider._request_json('GET', '/subtitles')
            self.assertEqual(opening.call_args.kwargs['timeout'], 5)
            opening.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
