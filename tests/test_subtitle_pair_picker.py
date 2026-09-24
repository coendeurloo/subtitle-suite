import unittest

from resources.lib.subtitle_pair_picker import build_subtitle_pairs, subtitle_matches_video


class SubtitlePairPickerTests(unittest.TestCase):
    def test_episode_only_shows_current_show_and_episode(self):
        video = 'The.Show.S02E03.1080p.WEB-DL'
        self.assertTrue(subtitle_matches_video(video, '/shows/The.Show.S02E03.nl.srt'))
        self.assertTrue(subtitle_matches_video(video, '/shows/S02E03.ru.srt'))
        self.assertFalse(subtitle_matches_video(video, '/shows/The.Show.S02E04.en.srt'))
        self.assertFalse(subtitle_matches_video(video, '/shows/Other.Show.S02E03.en.srt'))

    def test_movie_title_and_year_filter_unrelated_subtitles(self):
        video = 'Example.Movie.2024.1080p.BluRay'
        self.assertTrue(subtitle_matches_video(video, '/movies/Example.Movie.2024.nl.srt'))
        self.assertTrue(subtitle_matches_video(video, '/movies/Example.Movie-translated-ru.srt'))
        self.assertFalse(subtitle_matches_video(video, '/movies/Example.Movie.2023.en.srt'))
        self.assertFalse(subtitle_matches_video(video, '/movies/Other.Movie.2024.en.srt'))
        self.assertFalse(subtitle_matches_video(video, '/movies/Example.Movie.2024.dual.srt'))

    def test_numeric_movie_title_and_language_suffix(self):
        self.assertTrue(subtitle_matches_video('1917', '/movies/1917.en.srt'))
        self.assertTrue(subtitle_matches_video('It.2017', '/movies/It.nl.srt'))

    def test_pairs_prioritize_preferred_language_and_skip_same_language(self):
        entries = [
            {'path': '/film.en.srt', 'code': 'en'},
            {'path': '/film.ru.srt', 'code': 'ru'},
            {'path': '/film.nl.srt', 'code': 'nl'},
            {'path': '/film.nl.alt.srt', 'code': 'nl'},
        ]
        pairs = build_subtitle_pairs(entries, ('nl', 'ru'))
        self.assertEqual(('nl', 'ru'), (pairs[0][0]['code'], pairs[0][1]['code']))
        self.assertTrue(any((first['code'], second['code']) == ('nl', 'en')
                            for first, second in pairs))
        self.assertFalse(any(first['code'] == second['code'] for first, second in pairs))


if __name__ == '__main__':
    unittest.main()
