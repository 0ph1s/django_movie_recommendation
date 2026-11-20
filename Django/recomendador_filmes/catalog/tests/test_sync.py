# catalog/tests/test_sync.py
"""Catálogo pelas APIs (TMDB e AniList): normalização, descoberta e o comando sync_catalog."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from catalog.importers import api
from catalog.importers.api import AniListCatalog, TmdbCatalog, normalize_anilist, normalize_tmdb
from catalog.importers.loader import save_records
from catalog.models import Title

from .factories import sample_catalog

FILME = {
    'id': 27205, 'title': 'Inception', 'original_title': 'Inception', 'release_date': '2010-07-15',
    'overview': 'A thief who steals corporate secrets through dream-sharing technology.',
    'tagline': 'Your mind is the scene of the crime.', 'runtime': 148,
    'genres': [{'name': 'Action'}, {'name': 'Science Fiction'}],
    'vote_average': 8.4, 'vote_count': 36000, 'popularity': 90.5, 'poster_path': '/inception.jpg',
    'credits': {'cast': [{'name': f'Ator {i}'} for i in range(12)],
                'crew': [{'name': 'Christopher Nolan', 'job': 'Director'}, {'name': 'Hans Zimmer', 'job': 'Music'}]},
    'keywords': {'keywords': [{'name': 'dream'}, {'name': 'heist'}]},
}
SERIE = {
    'id': 1396, 'name': 'Breaking Bad', 'original_name': 'Breaking Bad', 'first_air_date': '2008-01-20',
    'overview': 'A chemistry teacher turns to cooking meth.', 'genres': [{'name': 'Drama'}, {'name': 'Crime'}],
    'episode_run_time': [47], 'number_of_episodes': 62, 'type': 'Scripted',
    'created_by': [{'name': 'Vince Gilligan'}], 'networks': [{'name': 'AMC'}],
    'vote_average': 8.9, 'vote_count': 15000, 'popularity': 300.0, 'poster_path': '/bb.jpg',
    'aggregate_credits': {'cast': [{'name': 'Bryan Cranston'}, {'name': 'Aaron Paul'}]},
    'keywords': {'results': [{'name': 'drug dealer'}]},
}
ANIME = {
    'idMal': 1535, 'title': {'english': 'Death Note', 'romaji': 'DEATH NOTE'},
    'description': 'A shinigami drops a notebook.<br><br>(Source: Crunchyroll)', 'format': 'TV',
    'source': 'MANGA', 'genres': ['Mystery', 'Psychological', 'Supernatural', 'Thriller'],
    'tags': [{'name': 'Detective', 'rank': 90}, {'name': 'Gore', 'rank': 50},
             {'name': 'Plot twist', 'rank': 95, 'isMediaSpoiler': True}],
    'studios': {'nodes': [{'name': 'Madhouse'}]}, 'episodes': 37, 'duration': 23,
    'averageScore': 84, 'popularity': 900000, 'startDate': {'year': 2006},
    'coverImage': {'extraLarge': 'https://anilist/dn.jpg'},
    'stats': {'scoreDistribution': [{'amount': 1000}, {'amount': 2500}]},
}


class NormalizacaoTests(SimpleTestCase):
    def test_filme_do_tmdb(self):
        r = normalize_tmdb('movie', FILME)
        self.assertEqual((r.kind, r.source, r.external_id, r.title), ('movie', 'tmdb', '27205', 'Inception'))
        self.assertEqual(r.original_title, '')            # igual ao título: não repete
        self.assertEqual(r.director, 'Christopher Nolan')
        self.assertEqual(len(r.cast.split(', ')), 8)
        self.assertEqual(r.keywords, 'dream heist')
        self.assertEqual(r.genres, ['Action', 'Science Fiction'])
        self.assertEqual((r.year, r.runtime, r.vote_count), (2010, 148, 36000))
        self.assertTrue(r.poster_url.endswith('/inception.jpg'))

    def test_serie_do_tmdb(self):
        r = normalize_tmdb('series', SERIE)
        self.assertEqual(r.director, 'Vince Gilligan')
        self.assertEqual(r.keywords, 'drug dealer AMC')
        self.assertEqual((r.year, r.runtime, r.episodes), (2008, 47, 62))
        self.assertEqual(r.cast, 'Bryan Cranston, Aaron Paul')

    def test_adulto_ou_vazio_fica_de_fora(self):
        self.assertIsNone(normalize_tmdb('movie', {**FILME, 'adult': True}))
        self.assertIsNone(normalize_tmdb('movie', None))

    def test_anime_da_anilist(self):
        r = normalize_anilist(ANIME)
        self.assertEqual((r.kind, r.source, r.external_id), ('anime', 'mal', '1535'))
        self.assertEqual((r.title, r.original_title), ('Death Note', 'DEATH NOTE'))
        self.assertEqual(r.overview, 'A shinigami drops a notebook.')   # sem HTML nem "(Source: …)"
        self.assertEqual(r.keywords, 'Manga Detective')                  # sem spoiler nem tag fraca
        self.assertEqual(r.genres[0], 'Animation')
        self.assertEqual((r.vote_average, r.vote_count, r.runtime, r.episodes), (8.4, 3500, 23, 37))
        self.assertEqual(r.director, 'Madhouse')

    def test_anime_sem_id_do_mal_ou_adulto_fica_de_fora(self):
        self.assertIsNone(normalize_anilist({**ANIME, 'idMal': None}))
        self.assertIsNone(normalize_anilist({**ANIME, 'genres': ['Hentai']}))

    def test_descoberta_tira_anime_das_series_e_para_no_limite(self):
        cliente = TmdbCatalog('chave')
        paginas = [
            {'total_pages': 3, 'results': [
                {'id': 1, 'genre_ids': [18]},
                {'id': 2, 'genre_ids': [16], 'original_language': 'ja'},      # anime: vem da AniList
                {'id': 3, 'genre_ids': [16], 'original_language': 'en'},
            ]},
            {'total_pages': 3, 'results': [{'id': 4}, {'id': 5}]},
        ]
        with mock.patch.object(api, 'request_json', side_effect=paginas) as chamada:
            itens = cliente.discover('series', 3)
        self.assertEqual([i['id'] for i in itens], [1, 3, 4])
        self.assertEqual(chamada.call_count, 2)
        self.assertIn('api_key=chave', chamada.call_args_list[0].args[0])
        self.assertIn('language=en-US', chamada.call_args_list[0].args[0])
        self.assertIn('first_air_date.lte=', chamada.call_args_list[0].args[0])   # só o que já estreou

    def test_anilist_pede_so_o_que_ja_estreou(self):
        self.assertIn('status_in: [RELEASING, FINISHED]', api._ANILIST_QUERY)

    def test_anilist_pagina_ate_o_limite(self):
        pagina = {'data': {'Page': {'pageInfo': {'hasNextPage': True},
                                     'media': [{**ANIME, 'idMal': i} for i in range(1, 51)]}}}
        with mock.patch.object(api, 'request_json', return_value=pagina) as chamada:
            registros = AniListCatalog(por_minuto=6000).popular(75)
        self.assertEqual(len(registros), 75)
        self.assertEqual(chamada.call_count, 2)


@override_settings(TMDB_API_KEY='chave')
class ComandoSyncTests(TestCase):
    def setUp(self):
        save_records(sample_catalog())   # filmes 1–6 do TMDB e o anime 7 do MAL

    def rodar(self, **opcoes):
        saida = StringIO()
        call_command('sync_catalog', stdout=saida, no_index=True, **opcoes)
        return saida.getvalue()

    def descoberta(self, kind, limite, *, desde=None, **_):
        if kind == 'series' or desde:
            return []
        # O filme 1 já existe (só números novos); o 27205 é novo (pede detalhes).
        return [
            {'id': 1, 'vote_average': 9.1, 'vote_count': 99999, 'popularity': 500, 'poster_path': '/novo.jpg'},
            {'id': 27205, 'vote_average': 8.4, 'vote_count': 36000, 'popularity': 90.5},
        ][:limite]

    @mock.patch.object(AniListCatalog, 'popular', return_value=[normalize_anilist(ANIME)])
    def test_novos_com_detalhes_existentes_so_com_numeros(self, _popular):
        with mock.patch.object(TmdbCatalog, 'discover', side_effect=self.descoberta), \
             mock.patch.object(TmdbCatalog, 'details', return_value=FILME) as detalhes:
            saida = self.rodar()

        detalhes.assert_called_once_with('movie', '27205')
        existente = Title.objects.get(source='tmdb', kind='movie', external_id='1')
        self.assertEqual((existente.vote_count, existente.vote_average), (99999, 9.1))
        self.assertTrue(existente.poster_url.endswith('/novo.jpg'))
        self.assertEqual(existente.title, 'Space Odyssey')       # sem --full, o resto não muda
        novo = Title.objects.get(external_id='27205')
        self.assertEqual((novo.title, novo.director), ('Inception', 'Christopher Nolan'))
        self.assertTrue(novo.genres.filter(name='Science Fiction').exists())
        self.assertTrue(Title.objects.filter(kind='anime', external_id='1535').exists())
        self.assertGreater(Title.objects.get(external_id='27205').popularity_rank, 0)
        self.assertIn('+2', saida)

    @mock.patch.object(AniListCatalog, 'popular', return_value=[])
    def test_full_detalha_tambem_os_existentes(self, _popular):
        with mock.patch.object(TmdbCatalog, 'discover', side_effect=self.descoberta), \
             mock.patch.object(TmdbCatalog, 'details', side_effect=lambda k, i: {**FILME, 'id': int(i)}) as detalhes:
            self.rodar(full=True)
        self.assertEqual(detalhes.call_count, 2)
        self.assertEqual(Title.objects.get(external_id='1').title, 'Inception')

    @override_settings(TMDB_API_KEY='')
    def test_sem_chave_filmes_e_series_recusam(self):
        with self.assertRaises(CommandError):
            self.rodar()

    @override_settings(TMDB_API_KEY='')
    @mock.patch.object(AniListCatalog, 'popular', return_value=[normalize_anilist(ANIME)])
    def test_so_animes_dispensa_a_chave(self, _popular):
        self.rodar(kinds='anime')
        self.assertTrue(Title.objects.filter(kind='anime', external_id='1535').exists())
