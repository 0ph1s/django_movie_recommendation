"""Mapa do gosto: projeção SVD + t-SNE, pontos da API, centro do perfil no mapa."""
import json
from io import StringIO

import numpy as np
from django.core.management import call_command
from django.urls import reverse

from api.tests import ApiTestCase
from catalog.models import Title
from recommender.engine import get_index
from recommender.models import Interaction
from recommender.projection import build_map, compute_projection

State = Interaction.State


class MapaTestCase(ApiTestCase):
    def marcar(self, titulo, estado=State.LIKE, kind='movie'):
        return self.client.post(
            reverse('api:interaction-add'),
            data=json.dumps({'title_id': self.pk(titulo, kind), 'state': estado}),
            content_type='application/json',
        )

    def insights(self, **params):
        return self.client.get(reverse('api:profile-insights'), params).json()


class ProjecaoTests(MapaTestCase):
    def test_projecao_e_reprodutivel_e_normalizada(self):
        indice = get_index()
        a = compute_projection(indice)
        b = compute_projection(indice)
        self.assertEqual(a.shape, (indice.size, 2))
        np.testing.assert_allclose(a, b)
        self.assertLessEqual(float(np.abs(a).max()), 1.0 + 1e-6)
        np.testing.assert_allclose(a.mean(axis=0), [0, 0], atol=1e-5)

    def test_gravar_nao_invalida_o_indice(self):
        indice = get_index()
        self.assertEqual(build_map(indice), indice.size)
        self.assertFalse(Title.objects.filter(map_x__isnull=True).exists())
        self.assertIs(get_index(), indice)

    def test_comando_build_index_projeta_e_no_map_pula(self):
        saida = StringIO()
        call_command('build_index', '--no-map', stdout=saida)
        self.assertFalse(Title.objects.filter(map_x__isnull=False).exists())
        call_command('build_index', stdout=saida)
        self.assertFalse(Title.objects.filter(map_x__isnull=True).exists())
        self.assertIn('Mapa:', saida.getvalue())


class PontosApiTests(MapaTestCase):
    def test_sem_projecao_a_lista_vem_vazia(self):
        dados = self.client.get(reverse('api:map-points')).json()
        self.assertEqual(dados['ids'], [])

    def test_colunas_compactas_com_etag(self):
        build_map(get_index())
        resposta = self.client.get(reverse('api:map-points'))
        dados = resposta.json()
        n = Title.objects.count()
        self.assertEqual(len(dados['ids']), n)
        self.assertEqual(len(dados['x']), n)
        self.assertEqual(len(dados['kinds']), n)
        self.assertTrue(set(dados['kinds']) <= {'m', 's', 'a'})
        self.assertTrue(all(-1000 <= v <= 1000 for v in dados['x'] + dados['y']))
        self.assertIn('public', resposta['Cache-Control'])
        repetida = self.client.get(reverse('api:map-points'), HTTP_IF_NONE_MATCH=resposta['ETag'])
        self.assertEqual(repetida.status_code, 304)


class MapaNoPerfilTests(MapaTestCase):
    def test_sem_projecao_o_mapa_fica_oculto(self):
        self.marcar('Orbit')
        dados = self.insights()
        self.assertFalse(dados['map_available'])
        self.assertIsNone(dados['map'])
        self.assertContains(self.client.get(reverse('web:profile')), 'data-section="map" hidden')

    def test_pontos_centro_e_vizinhos(self):
        build_map(get_index())
        self.marcar('Orbit')
        self.marcar('Space Return', State.FAVORITE)
        self.marcar('Paris Rain', State.DISLIKE)
        mapa = self.insights()['map']

        self.assertEqual(
            {(p['title_id'], p['state']) for p in mapa['points']},
            {(self.pk('Orbit'), 'like'), (self.pk('Space Return'), 'favorite'), (self.pk('Paris Rain'), 'dislike')},
        )
        self.assertTrue(-1 <= mapa['center']['x'] <= 1 and -1 <= mapa['center']['y'] <= 1)
        vistos = {self.pk(t) for t in ('Orbit', 'Space Return', 'Paris Rain')}
        self.assertTrue(mapa['neighbors'])
        self.assertTrue(vistos.isdisjoint(n['id'] for n in mapa['neighbors']))

    def test_centro_e_a_media_dos_mais_proximos(self):
        build_map(get_index())
        self.marcar('Orbit')
        with self.settings_patch_neighbors(1):
            mapa = self.insights()['map']
        orbita = Title.objects.get(pk=self.pk('Orbit'))
        # Com 1 vizinho, o centro cai sobre o título mais próximo do perfil: o próprio curtido.
        self.assertAlmostEqual(mapa['center']['x'], orbita.map_x, places=3)
        self.assertAlmostEqual(mapa['center']['y'], orbita.map_y, places=3)

    def test_centro_se_move_no_modo_e_se(self):
        build_map(get_index())
        self.marcar('Orbit')
        self.marcar('Summer Letters')
        # Com 9 títulos no catálogo de teste, a média dos 10 mais próximos seria sempre a de
        # todos (o centro do mapa); com 2, o centro acompanha o perfil.
        with self.settings_patch_neighbors(2):
            antes = self.insights()['map']['center']
            depois = self.insights(exclude=str(self.pk('Summer Letters')))['map']['center']
        self.assertNotEqual(antes, depois)

    def test_mapa_bloqueado_sem_positivos(self):
        build_map(get_index())
        self.marcar('Orbit', State.WATCHLIST)
        dados = self.insights()
        self.assertTrue(dados['map_available'])
        self.assertFalse(dados['locks']['map']['unlocked'])
        self.assertIsNone(dados['map'])

    def settings_patch_neighbors(self, n):
        from unittest.mock import patch

        return patch('recommender.insights.MAP_CENTER_NEIGHBORS', n)
