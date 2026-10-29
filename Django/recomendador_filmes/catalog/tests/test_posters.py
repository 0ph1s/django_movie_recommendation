import io
import json
from email.message import Message
from io import StringIO
from unittest import mock
from urllib.error import HTTPError

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from catalog.importers.loader import save_records
from catalog.models import Title
from catalog.posters import AniListClient, PosterSourceError, TmdbClient, request_json

from .factories import sample_catalog


def resposta(dados):
    corpo = io.BytesIO(json.dumps(dados).encode())
    corpo.__enter__ = lambda self=corpo: self
    corpo.__exit__ = lambda *args: False
    return corpo


def erro_http(codigo, retry_after=None):
    cabecalhos = Message()
    if retry_after is not None:
        cabecalhos['Retry-After'] = str(retry_after)
    return HTTPError('https://exemplo', codigo, 'erro', cabecalhos, None)


@mock.patch('catalog.posters.time.sleep')
@mock.patch('catalog.posters.urlopen')
class ClientesTests(SimpleTestCase):
    def test_tmdb_com_chave_v3_monta_a_url_da_capa(self, urlopen, _sleep):
        urlopen.return_value = resposta({'poster_path': '/abc.jpg'})
        url = TmdbClient('chave123').poster_url('movie', '19995')
        self.assertEqual(url, 'https://image.tmdb.org/t/p/w500/abc.jpg')
        requisicao = urlopen.call_args.args[0]
        self.assertEqual(requisicao.full_url, 'https://api.themoviedb.org/3/movie/19995?api_key=chave123')

    def test_tmdb_com_token_v4_usa_bearer_e_rota_de_series(self, urlopen, _sleep):
        urlopen.return_value = resposta({'poster_path': None})
        self.assertEqual(TmdbClient('eyJtoken').poster_url('series', '1396'), '')
        requisicao = urlopen.call_args.args[0]
        self.assertEqual(requisicao.full_url, 'https://api.themoviedb.org/3/tv/1396')
        self.assertEqual(requisicao.get_header('Authorization'), 'Bearer eyJtoken')

    def test_titulo_inexistente_fica_sem_capa(self, urlopen, _sleep):
        urlopen.side_effect = erro_http(404)
        self.assertEqual(TmdbClient('k').poster_url('movie', '1'), '')

    def test_repete_apos_limite_de_requisicoes(self, urlopen, sleep):
        urlopen.side_effect = [erro_http(429, retry_after=3), resposta({'ok': True})]
        self.assertEqual(request_json('https://exemplo'), {'ok': True})
        sleep.assert_called_with(3.0)

    def test_chave_recusada_interrompe(self, urlopen, _sleep):
        urlopen.side_effect = erro_http(401)
        with self.assertRaises(PosterSourceError):
            TmdbClient('errada').poster_url('movie', '1')

    def test_desiste_depois_de_varias_falhas(self, urlopen, _sleep):
        urlopen.side_effect = erro_http(503)
        with self.assertRaises(PosterSourceError):
            request_json('https://exemplo')

    def test_anilist_mapeia_ids_do_mal_para_capas(self, urlopen, _sleep):
        urlopen.return_value = resposta({'data': {'Page': {'media': [
            {'idMal': 1, 'coverImage': {'extraLarge': 'https://anilist/1.png', 'large': 'x'}},
            {'idMal': 5, 'coverImage': {'extraLarge': None, 'large': 'https://anilist/5.png'}},
            {'idMal': 9, 'coverImage': {}},
        ]}}})
        capas = AniListClient().poster_urls(['1', '5', '9'])
        self.assertEqual(capas, {'1': 'https://anilist/1.png', '5': 'https://anilist/5.png'})
        corpo = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(corpo['variables'], {'ids': [1, 5, 9], 'perPage': 3})


class ComandoFetchPostersTests(TestCase):
    def setUp(self):
        save_records(sample_catalog())

    def rodar(self, **opcoes):
        saida, erros = StringIO(), StringIO()
        call_command('fetch_posters', stdout=saida, stderr=erros, **opcoes)
        return saida.getvalue(), erros.getvalue()

    @override_settings(TMDB_API_KEY='')
    @mock.patch.object(AniListClient, 'poster_urls', return_value={'7': 'https://anilist/7.png'})
    def test_sem_chave_busca_so_os_animes(self, poster_urls):
        saida, erros = self.rodar()
        self.assertIn('TMDB_API_KEY não definida', erros)
        self.assertEqual(Title.objects.get(kind='anime', external_id='7').poster_url, 'https://anilist/7.png')
        self.assertEqual(Title.objects.filter(kind='movie').exclude(poster_url='').count(), 0)
        self.assertIn('Capas encontradas: 1', saida)

    @override_settings(TMDB_API_KEY='chave')
    @mock.patch.object(TmdbClient, 'poster_url', side_effect=lambda kind, i: f'https://tmdb/{kind}/{i}.jpg')
    def test_com_chave_preenche_filmes_e_series(self, _poster_url):
        self.rodar(kinds='movie,series')
        self.assertEqual(Title.objects.get(kind='movie', external_id='1').poster_url, 'https://tmdb/movie/1.jpg')
        self.assertEqual(Title.objects.get(kind='series', external_id='9').poster_url, 'https://tmdb/series/9.jpg')

    @override_settings(TMDB_API_KEY='chave')
    @mock.patch.object(TmdbClient, 'poster_url', return_value='https://tmdb/novo.jpg')
    def test_so_busca_quem_nao_tem_capa_a_menos_que_refresh(self, poster_url):
        Title.objects.filter(kind='movie').update(poster_url='https://antigo.jpg')
        self.rodar(kinds='movie')
        poster_url.assert_not_called()
        self.rodar(kinds='movie', refresh=True)
        self.assertEqual(set(Title.objects.filter(kind='movie').values_list('poster_url', flat=True)), {'https://tmdb/novo.jpg'})

    def test_tipo_invalido(self):
        with self.assertRaises(CommandError):
            self.rodar(kinds='filme')

    def test_reimportar_preserva_as_capas_buscadas(self):
        Title.objects.filter(kind='movie', external_id='1').update(poster_url='https://tmdb/capa.jpg')
        save_records(sample_catalog())  # o CSV não traz capa
        self.assertEqual(Title.objects.get(kind='movie', external_id='1').poster_url, 'https://tmdb/capa.jpg')
