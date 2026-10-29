import json
import tempfile
from io import StringIO
from pathlib import Path

import pandas as pd
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from catalog.importers import read_anime, read_movies, read_series
from catalog.importers.base import canonical_genres, clean_text, parse_names, parse_year, split_space_separated_genres
from catalog.importers.loader import refresh_popularity_ranks, save_records, select_records
from catalog.models import Genre, Title
from recommender.config import get_config

from .factories import sample_catalog, titulo


def escrever_csv(pasta, nome, linhas):
    caminho = Path(pasta) / nome
    pd.DataFrame(linhas).to_csv(caminho, index=False)
    return caminho


class LimpezaTests(SimpleTestCase):
    def test_decodifica_escapes_unicode_literais(self):
        self.assertEqual(clean_text(r'Stellan Skarsgård  '), 'Stellan Skarsgård')

    def test_valores_ausentes_viram_texto_vazio(self):
        for valor in [None, float('nan'), 'UNKNOWN', '  ', 'nan']:
            with self.subTest(valor=valor):
                self.assertEqual(clean_text(valor), '')

    def test_generos_compostos_separados_por_espaco(self):
        self.assertCountEqual(
            split_space_separated_genres('Action Science Fiction TV Movie Drama'),
            ['Action', 'Science Fiction', 'TV Movie', 'Drama'],
        )

    def test_generos_sao_traduzidos_para_o_vocabulario_canonico(self):
        self.assertEqual(
            canonical_genres(['Sci-Fi', 'Action & Adventure', 'Award Winning', 'Action', 'Slice of Life']),
            ['Science Fiction', 'Action', 'Adventure', 'Slice of Life'],
        )

    def test_listas_em_json_literal_python_ou_virgulas(self):
        self.assertEqual(parse_names('[{"id": 1, "name": "Drama"}]'), ['Drama'])
        self.assertEqual(parse_names("[{'name': 'Crime'}]"), ['Crime'])
        self.assertEqual(parse_names('Sunrise, Bones'), ['Sunrise', 'Bones'])

    def test_ano_de_formatos_diferentes(self):
        self.assertEqual(parse_year('2009-12-10'), 2009)
        self.assertEqual(parse_year('Apr 3, 1998 to Apr 24, 1999'), 1998)
        self.assertIsNone(parse_year('UNKNOWN'))


class AdaptadoresTests(SimpleTestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)

    def test_filmes_no_formato_pre_mesclado(self):
        caminho = escrever_csv(self.pasta.name, 'movies.csv', [{
            'id': 19995, 'title': 'Avatar', 'original_title': 'Avatar', 'overview': 'Pandora.',
            'genres': 'Action Adventure Science Fiction', 'keywords': 'space war',
            'cast': r'Sam Worthington Zoe Saldana', 'director': 'James Cameron',
            'release_date': '2009-12-10', 'runtime': 162.0, 'vote_average': 7.2,
            'vote_count': 11800, 'popularity': 150.4, 'tagline': '',
        }])
        [filme] = list(read_movies(caminho))
        self.assertEqual(filme.genres, ['Science Fiction', 'Action', 'Adventure'])
        self.assertEqual((filme.year, filme.runtime, filme.director), (2009, 162, 'James Cameron'))

    def test_filmes_no_formato_original_com_creditos(self):
        filmes = escrever_csv(self.pasta.name, 'tmdb_5000_movies.csv', [{
            'id': 1, 'title': 'Heat', 'genres': json.dumps([{'id': 80, 'name': 'Crime'}]),
            'keywords': json.dumps([{'id': 1, 'name': 'heist'}]), 'release_date': '1995-12-15',
            'vote_average': 7.7, 'vote_count': 1886, 'popularity': 70,
        }])
        creditos = escrever_csv(self.pasta.name, 'tmdb_5000_credits.csv', [{
            'movie_id': 1, 'title': 'Heat',
            'cast': json.dumps([{'name': 'Al Pacino'}, {'name': 'Robert De Niro'}]),
            'crew': json.dumps([{'name': 'Michael Mann', 'job': 'Director'}, {'name': 'X', 'job': 'Editor'}]),
        }])
        [filme] = list(read_movies(filmes, credits_path=creditos))
        self.assertEqual(filme.genres, ['Crime'])
        self.assertEqual(filme.keywords, 'heist')
        self.assertEqual(filme.cast, 'Al Pacino, Robert De Niro')
        self.assertEqual(filme.director, 'Michael Mann')

    def test_series_ignoram_conteudo_adulto(self):
        caminho = escrever_csv(self.pasta.name, 'tv.csv', [
            {'id': 1, 'name': 'Dark', 'genres': 'Crime, Sci-Fi & Fantasy', 'created_by': 'Baran bo Odar',
             'networks': 'Netflix', 'type': 'Scripted', 'first_air_date': '2017-12-01', 'adult': 'False',
             'vote_count': 10, 'vote_average': 8, 'popularity': 1},
            {'id': 2, 'name': 'Adulto', 'adult': 'True'},
        ])
        [serie] = list(read_series(caminho))
        self.assertEqual(serie.genres, ['Crime', 'Science Fiction', 'Fantasy'])
        self.assertEqual(serie.keywords, 'Netflix')  # "Scripted" não acrescenta nada

    def test_animes_preferem_titulo_em_ingles_e_filtram_adultos(self):
        caminho = escrever_csv(self.pasta.name, 'anime.csv', [
            {'anime_id': 1, 'Name': 'Shingeki no Kyojin', 'English name': 'Attack on Titan',
             'Genres': 'Action, Award Winning', 'Type': 'TV', 'Source': 'Manga', 'Aired': 'Apr 7, 2013 to Sep 29, 2013',
             'Studios': 'Wit Studio', 'Score': '8.55', 'Scored By': '2800000', 'Members': '3900000', 'Rating': 'R - 17+'},
            {'anime_id': 2, 'Name': 'X', 'English name': 'UNKNOWN', 'Genres': 'Hentai', 'Type': 'OVA'},
            {'anime_id': 3, 'Name': 'Clipe', 'English name': 'UNKNOWN', 'Genres': 'Music', 'Type': 'Music'},
        ])
        [anime] = list(read_anime(caminho))
        self.assertEqual((anime.title, anime.original_title), ('Attack on Titan', 'Shingeki no Kyojin'))
        self.assertEqual(anime.genres, ['Animation', 'Action'])
        self.assertEqual((anime.year, anime.director, anime.keywords), (2013, 'Wit Studio', 'Manga'))
        self.assertEqual((anime.vote_count, anime.popularity), (2800000, 3900000.0))


class GravacaoTests(TestCase):
    def test_upsert_nao_duplica_e_atualiza_generos(self):
        save_records(sample_catalog())
        registros = sample_catalog()
        registros[0].title = 'Space Odyssey (remaster)'
        registros[0].genres = ['Drama']
        save_records(registros)

        self.assertEqual(Title.objects.count(), len(registros))
        filme = Title.objects.get(source='tmdb', kind='movie', external_id='1')
        self.assertEqual(filme.title, 'Space Odyssey (remaster)')
        self.assertEqual([g.name for g in filme.genres.all()], ['Drama'])

    def test_percentil_de_popularidade_e_calculado_por_tipo(self):
        save_records(sample_catalog())
        refresh_popularity_ranks()
        # O anime com 900 mil membros e o filme mais popular ficam ambos no topo do seu tipo.
        self.assertEqual(Title.objects.get(external_id='7', kind='anime').popularity_rank, 1.0)
        self.assertEqual(Title.objects.get(external_id='1', kind='movie').popularity_rank, 1.0)

    def test_selecao_aplica_minimo_de_votos_e_limite(self):
        selecionados = select_records(sample_catalog(), min_votes=1000, limit=2)
        self.assertEqual([r.title for r in selecionados], ['Star Pilots', 'Space Odyssey'])


class ComandoImportTests(TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

    def test_importa_tres_fontes_e_constroi_o_indice(self):
        filmes = escrever_csv(self.pasta.name, 'm.csv', [
            {'id': i, 'title': f'Filme {i}', 'genres': 'Drama', 'overview': f'Story number {i} about family.',
             'vote_count': 10 * i, 'vote_average': 6, 'popularity': i} for i in range(1, 6)
        ])
        series = escrever_csv(self.pasta.name, 's.csv', [
            {'id': 1, 'name': 'Serie', 'genres': 'Drama', 'overview': 'A family drama.', 'vote_count': 5, 'popularity': 1},
        ])
        animes = escrever_csv(self.pasta.name, 'a.csv', [
            {'anime_id': 1, 'Name': 'Anime', 'Genres': 'Drama', 'Synopsis': 'A family story.', 'Scored By': 5, 'Members': 9},
        ])
        indice = Path(self.pasta.name) / 'indice.joblib'
        with override_settings(RECOMMENDER={'INDEX_PATH': indice}):
            get_config.cache_clear()
            call_command('import_dataset', movies=filmes, series=series, anime=animes, min_votes=20, stdout=StringIO())

        self.assertEqual(Title.objects.filter(kind='movie').count(), 4)  # o de 10 votos ficou de fora
        self.assertEqual(Title.objects.filter(kind='series').count(), 0)  # 5 votos < 20
        self.assertTrue(indice.is_file())
        self.assertTrue(Genre.objects.filter(name='Drama').exists())
