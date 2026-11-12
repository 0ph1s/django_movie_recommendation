"""Página de perfil: insights (estatísticas, DNA, radar, títulos que te definem, conforto,
watchlist, modo "e se"), avatar ASCII e as páginas /perfil/ e /bem-vindo/."""
import json
from unittest.mock import patch

from django.conf import settings
from django.urls import reverse

from api.tests import ApiTestCase
from catalog.models import Title
from recommender.avatar import RAMP, SIZE, avatar_grid
from recommender.config import get_config
from recommender.models import Interaction

State = Interaction.State


class InsightsTestCase(ApiTestCase):
    def marcar(self, titulo, estado=State.LIKE, kind='movie'):
        return self.client.post(
            reverse('api:interaction-add'),
            data=json.dumps({'title_id': self.pk(titulo, kind), 'state': estado}),
            content_type='application/json',
        )

    def insights(self, **params):
        resposta = self.client.get(reverse('api:profile-insights'), params)
        self.assertEqual(resposta.status_code, 200)
        return resposta.json()

    def curtir_varios(self, n):
        titulos = [('Space Odyssey', 'movie'), ('Orbit', 'movie'), ('Paris Rain', 'movie'),
                   ('Star Pilots', 'anime'), ('Office Days', 'series'), ('Summer Letters', 'movie'),
                   ('Space Return', 'movie'), ('Space Odyssey', 'anime')]
        for titulo, kind in titulos[:n]:
            self.marcar(titulo, kind=kind)


class DesbloqueioTests(InsightsTestCase):
    def test_perfil_vazio_fica_todo_bloqueado(self):
        dados = self.insights()
        self.assertEqual(dados['counts'], {'positives': 0, 'rated': 0, 'total': 0})
        self.assertFalse(any(trava['unlocked'] for trava in dados['locks'].values()))
        self.assertIsNone(dados['dna'])
        self.assertIsNone(dados['stats'])
        self.assertTrue(dados['avatar']['empty'])

    def test_limiares_de_cada_secao(self):
        self.curtir_varios(2)
        dados = self.insights()
        self.assertTrue(dados['locks']['map']['unlocked'])
        self.assertFalse(dados['locks']['dna']['unlocked'])
        self.assertEqual((dados['locks']['dna']['have'], dados['locks']['dna']['need']), (2, 3))

        self.curtir_varios(3)
        dados = self.insights()
        self.assertTrue(dados['locks']['dna']['unlocked'])
        self.assertTrue(dados['dna']['dna'])
        self.assertTrue(dados['radar']['axes'])
        self.assertFalse(dados['locks']['comfort']['unlocked'])

    def test_watchlist_nao_conta_como_avaliacao(self):
        self.curtir_varios(4)
        self.marcar('Summer Letters', State.WATCHLIST)
        self.assertFalse(self.insights()['locks']['stats']['unlocked'])
        self.marcar('Space Return', State.SEEN)
        self.assertTrue(self.insights()['locks']['stats']['unlocked'])


class SecoesTests(InsightsTestCase):
    def test_estatisticas_e_horas(self):
        Title.objects.filter(pk=self.pk('Space Odyssey')).update(runtime=120)
        Title.objects.filter(pk=self.pk('Office Days', 'series')).update(runtime=30, episodes=20)
        self.curtir_varios(5)  # Star Pilots (anime) fica sem duração
        stats = self.insights()['stats']
        self.assertEqual(stats['by_kind'], {'movie': 3, 'series': 1, 'anime': 1})
        self.assertEqual(stats['hours'], round((120 + 600) / 60))
        self.assertEqual(stats['hours_missing'], 3)  # Orbit, Paris Rain, Star Pilots
        self.assertEqual(stats['favorite_decade'], 2010)

    def test_titulos_que_te_definem(self):
        self.curtir_varios(3)
        self.marcar('Space Return', State.FAVORITE)
        definem = self.insights()['defining']
        self.assertAlmostEqual(sum(d['share'] for d in definem), 1.0, places=2)
        self.assertEqual(definem[0]['title']['title'], 'Space Return')
        self.assertEqual(definem[0]['state'], 'favorite')

    def test_radar_compara_com_o_catalogo(self):
        self.curtir_varios(3)
        eixos = {e['genre']: e for e in self.insights()['radar']['axes']}
        self.assertIn('Science Fiction', eixos)
        self.assertGreater(eixos['Science Fiction']['user'], 0)
        self.assertAlmostEqual(sum(e['catalog'] for e in eixos.values()) <= 1.0, True)

    def test_conforto(self):
        self.curtir_varios(8)
        conforto = self.insights()['comfort']
        self.assertGreater(conforto['eclecticism'], 0)
        self.assertLessEqual(conforto['eclecticism'], 1)
        self.assertGreaterEqual(conforto['dispersion'], 0)

    @patch('recommender.insights.BLIND_MIN_GOOD', 1)
    @patch('recommender.insights.GOOD_RATING', 0.0)
    @patch('recommender.insights.GOOD_VOTES', 0.0)
    def test_pontos_cegos_so_onde_nao_ha_nada_seu(self):
        # O catálogo de teste tem 9 títulos: com 8 curtidos não sobraria ponto cego. O limiar
        # da seção cai para 1 e o perfil fica só em ficção científica.
        self.curtir_varios(2)
        with self.settings(RECOMMENDER={**settings.RECOMMENDER, 'UNLOCK_COMFORT': 1}):
            get_config.cache_clear()
            pontos = self.insights()['comfort']['blind_spots']
        get_config.cache_clear()
        self.assertTrue(pontos)
        rotulos = {p['label'] for p in pontos}
        self.assertTrue(rotulos.isdisjoint({'Science Fiction', 'Adventure', 'Thriller', 'filmes', 'anos 2010'}))
        self.assertLessEqual(len(pontos), 4)
        for tipo in ('genre', 'kind', 'decade'):
            self.assertLessEqual(sum(p['type'] == tipo for p in pontos), 2)
        historico = {
            t.pk for t in Title.objects.filter(interactions__isnull=False)
        }
        for ponto in pontos:
            self.assertNotIn(ponto['suggestion']['id'], historico)
            self.assertNotEqual(ponto['label'], 'Science Fiction')

    def test_watchlist_com_match(self):
        self.curtir_varios(2)  # só ficção científica
        self.marcar('Space Return', State.WATCHLIST)
        self.marcar('Summer Letters', State.WATCHLIST)
        lista = self.insights()['watchlist']
        self.assertEqual([w['title']['title'] for w in lista], ['Space Return', 'Summer Letters'])
        self.assertTrue(all(0 <= w['match'] <= 1 for w in lista))
        self.assertGreater(lista[0]['match'], lista[1]['match'])


class ModoESeTests(InsightsTestCase):
    def test_excluir_recalcula_sem_gravar(self):
        self.curtir_varios(4)
        antes = self.insights()
        alvo = self.pk('Paris Rain')
        depois = self.insights(exclude=str(alvo))

        self.assertEqual(depois['excluded'], [alvo])
        self.assertEqual(
            [e['genre'] for e in antes['radar']['axes']], [e['genre'] for e in depois['radar']['axes']],
        )
        self.assertNotEqual(antes['radar'], depois['radar'])
        self.assertEqual(depois['whatif']['titles'], ['Paris Rain'])
        self.assertIn(depois['whatif']['genre'], {'Romance', 'Comedy'})
        self.assertTrue(next(d for d in depois['defining'] if d['title_id'] == alvo)['excluded'])
        self.assertEqual(Interaction.objects.count(), 4)
        self.assertEqual(self.insights()['radar'], antes['radar'])

    def test_excluir_todos_os_curtidos(self):
        self.curtir_varios(3)
        ids = ','.join(str(self.pk(t)) for t in ('Space Odyssey', 'Orbit', 'Paris Rain'))
        dados = self.insights(exclude=ids)
        self.assertTrue(dados['whatif']['empty'])
        self.assertIsNone(dados['dna'])

    def test_exclude_invalido(self):
        resposta = self.client.get(reverse('api:profile-insights'), {'exclude': 'abc'})
        self.assertEqual(resposta.status_code, 400)


class AvatarTests(InsightsTestCase):
    def test_grade_e_simetrica_e_usa_a_rampa(self):
        resumo = {'dna': [{'token': 'g:science_fiction', 'weight': 1.0}, {'token': 'c:ana', 'weight': 0.4}],
                  'kinds': {'movie': 0.2, 'anime': 0.8}}
        grade = avatar_grid(resumo)
        self.assertEqual(len(grade['rows']), SIZE)
        for linha in grade['rows']:
            self.assertEqual(len(linha), SIZE)
            self.assertEqual(linha, linha[::-1])
            self.assertTrue(set(linha) <= set(RAMP))
        self.assertEqual(grade['ink'], 'silver')
        self.assertEqual(avatar_grid(resumo), grade)

    def test_svg_com_etag_que_muda_com_o_gosto(self):
        url = reverse('api:profile-avatar')
        vazio = self.client.get(url)
        self.assertEqual(vazio['Content-Type'], 'image/svg+xml; charset=utf-8')
        self.assertIn(b'<svg', vazio.content)

        self.curtir_varios(2)
        primeiro = self.client.get(url)
        self.assertNotEqual(primeiro['ETag'], vazio['ETag'])
        self.assertEqual(self.client.get(url, HTTP_IF_NONE_MATCH=primeiro['ETag']).status_code, 304)

        self.marcar('Office Days', State.FAVORITE, kind='series')
        self.assertNotEqual(self.client.get(url)['ETag'], primeiro['ETag'])


class PaginasDePerfilTests(InsightsTestCase):
    def test_perfil_anonimo(self):
        resposta = self.client.get(reverse('web:profile'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Este perfil vive só neste navegador')
        self.assertContains(resposta, 'id="profile-data"')

    def test_perfil_com_dados_embutidos(self):
        self.curtir_varios(3)
        resposta = self.client.get(reverse('web:profile'))
        self.assertEqual(resposta.context['insights']['counts']['positives'], 3)

    def test_cabecalho_tem_o_link_do_perfil(self):
        resposta = self.client.get(reverse('web:home'))
        self.assertContains(resposta, reverse('api:profile-avatar'))
        self.assertContains(resposta, f'href="{reverse("web:profile")}"')
