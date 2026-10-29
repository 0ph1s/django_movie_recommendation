import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.importers.loader import refresh_popularity_ranks, save_records
from catalog.models import Title
from catalog.tests.factories import sample_catalog
from recommender.config import get_config
from recommender.engine import get_index


class ApiTestCase(TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        configuracao = override_settings(RECOMMENDER={'INDEX_PATH': Path(pasta.name) / 'indice.joblib'})
        configuracao.enable()
        self.addCleanup(configuracao.disable)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

        save_records(sample_catalog())
        refresh_popularity_ranks()
        self.ids = {
            (t.kind, t.title): t.pk for t in Title.objects.all()
        }

    def pk(self, titulo, kind='movie'):
        return self.ids[(kind, titulo)]

    def curtir(self, titulo, sinal=1, kind='movie'):
        return self.client.post(
            reverse('api:interaction-add'),
            data=json.dumps({'title_id': self.pk(titulo, kind), 'signal': sinal}),
            content_type='application/json',
        )


class CatalogoApiTests(ApiTestCase):
    def test_busca_por_titulo(self):
        dados = self.client.get(reverse('api:catalog'), {'q': 'space'}).json()
        self.assertEqual({r['title'] for r in dados['results']}, {'Space Odyssey', 'Space Return', 'Garage Spaceship'})
        self.assertFalse(dados['approximate'])

    def test_busca_tolera_erro_de_digitacao(self):
        dados = self.client.get(reverse('api:catalog'), {'q': 'Pariss Rian'}).json()
        self.assertTrue(dados['approximate'])
        self.assertEqual(dados['results'][0]['title'], 'Paris Rain')

    def test_filtro_por_tipo_e_paginacao(self):
        dados = self.client.get(reverse('api:catalog'), {'kinds': 'anime', 'limit': 1}).json()
        self.assertEqual(dados['count'], 2)
        self.assertEqual(len(dados['results']), 1)
        self.assertEqual(dados['results'][0]['kind'], 'anime')

    def test_parecidos_com_um_titulo(self):
        resposta = self.client.get(reverse('api:title-similar', args=[self.pk('Space Odyssey')]), {'obscurity': 0})
        dados = resposta.json()
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(dados['source']['title'], 'Space Odyssey')
        self.assertEqual(dados['results'][0]['title'], 'Space Return')
        self.assertIn('contributions', dados['results'][0])

    def test_titulo_inexistente(self):
        self.assertEqual(self.client.get(reverse('api:title-similar', args=[999999])).status_code, 404)

    def test_matriz_de_similaridade(self):
        ids = f"{self.pk('Space Odyssey')},{self.pk('Paris Rain')}"
        dados = self.client.get(reverse('api:similarity-matrix'), {'ids': ids}).json()
        self.assertEqual(len(dados['matrix']), 2)
        self.assertAlmostEqual(dados['matrix'][0][0], 1.0, places=3)
        self.assertEqual(self.client.get(reverse('api:similarity-matrix'), {'ids': 'a,b'}).status_code, 400)

    def test_indice_em_memoria_dispensa_o_banco_dentro_do_ttl(self):
        caminho = get_config().index_path
        with override_settings(RECOMMENDER={'INDEX_PATH': caminho, 'FINGERPRINT_TTL': 60}):
            get_config.cache_clear()
            indice = get_index()
            with self.assertNumQueries(0):
                self.assertIs(get_index(), indice)
        get_config.cache_clear()

    def test_catalogo_vazio_responde_503_com_instrucao(self):
        Title.objects.all().delete()
        resposta = self.client.get(reverse('api:recommendations'))
        self.assertEqual(resposta.status_code, 503)
        self.assertIn('import_dataset', resposta.json()['error'])


class PerfilApiTests(ApiTestCase):
    def test_partida_a_frio_usa_so_a_qualidade(self):
        dados = self.client.get(reverse('api:recommendations')).json()
        self.assertEqual(dados['mode'], 'cold_start')
        self.assertIsNone(dados['profile'])
        self.assertTrue(dados['results'])

    def test_curtir_personaliza_as_recomendacoes(self):
        self.assertEqual(self.curtir('Paris Rain').status_code, 201)
        dados = self.client.get(reverse('api:recommendations'), {'obscurity': 0}).json()
        self.assertEqual(dados['mode'], 'profile')
        self.assertEqual(dados['results'][0]['title'], 'Summer Letters')
        self.assertEqual([h['title']['title'] for h in dados['history']], ['Paris Rain'])
        self.assertTrue(dados['profile']['dna'])

    def test_reavaliar_atualiza_sem_duplicar(self):
        self.curtir('Orbit', 1)
        self.curtir('Orbit', -1)
        historico = self.client.get(reverse('api:profile')).json()['history']
        self.assertEqual([(h['title']['title'], h['signal']) for h in historico], [('Orbit', -1)])

    def test_remover_e_limpar_o_perfil(self):
        self.curtir('Orbit')
        self.curtir('Paris Rain')
        resposta = self.client.delete(reverse('api:interaction-remove', args=[self.pk('Orbit')]))
        self.assertEqual([h['title']['title'] for h in resposta.json()['history']], ['Paris Rain'])
        self.assertEqual(self.client.delete(reverse('api:profile')).json()['history'], [])

    def test_perfis_sao_separados_por_sessao(self):
        self.curtir('Orbit')
        outro = self.client_class()
        self.assertEqual(outro.get(reverse('api:profile')).json()['history'], [])

    def test_ler_o_perfil_nao_cria_sessao(self):
        for rota in ('api:profile', 'api:recommendations'):
            with self.subTest(rota=rota):
                resposta = self.client.get(reverse(rota))
                self.assertEqual(resposta.json()['history'], [])
                self.assertNotIn('sessionid', resposta.cookies)
        self.assertIn('sessionid', self.curtir('Orbit').cookies)

    def test_payload_invalido(self):
        for corpo in ['{}', 'nao-e-json', json.dumps({'title_id': self.pk('Orbit'), 'signal': 5})]:
            with self.subTest(corpo=corpo):
                resposta = self.client.post(reverse('api:interaction-add'), data=corpo, content_type='application/json')
                self.assertEqual(resposta.status_code, 400)

    def test_post_exige_csrf(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        resposta = cliente.post(
            reverse('api:interaction-add'),
            data=json.dumps({'title_id': self.pk('Orbit'), 'signal': 1}),
            content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 403)


class PaginasTests(ApiTestCase):
    def test_paginas_renderizam(self):
        for nome in ['web:home', 'web:playground']:
            with self.subTest(pagina=nome):
                resposta = self.client.get(reverse(nome))
                self.assertEqual(resposta.status_code, 200)
                self.assertContains(resposta, 'data-field')

    def test_pagina_404(self):
        resposta = self.client.get('/nao-existe/')
        self.assertEqual(resposta.status_code, 404)
        self.assertContains(resposta, 'Página não encontrada', status_code=404)
        self.assertContains(resposta, '/nao-existe/', status_code=404)
        self.assertEqual(resposta.context['page'], 'not-found')

    def test_404_da_api_continua_em_json(self):
        for caminho in ['/api/nao-existe/', reverse('api:title-detail', args=[999999])]:
            with self.subTest(caminho=caminho):
                resposta = self.client.get(caminho)
                self.assertEqual(resposta.status_code, 404)
                self.assertEqual(resposta['Content-Type'], 'application/json')
                self.assertIn('error', resposta.json())

    def test_titulo_da_pagina_e_so_texto(self):
        resposta = self.client.get(reverse('web:playground'))
        self.assertContains(resposta, '<title>Playground | Ângulo</title>')

    def test_home_mostra_contagem_e_destaques(self):
        resposta = self.client.get(reverse('web:home'))
        self.assertContains(resposta, 'featured-data')
        self.assertEqual(resposta.context['total_titles'], len(sample_catalog()))
