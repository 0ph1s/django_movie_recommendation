"""Estados de gosto (favorito, curti, não curti, já vi, quero assistir) e o log de eventos."""
import json

import numpy as np
from django.urls import reverse

from api.tests import ApiTestCase
from catalog.models import Title
from recommender.engine import recommend_for_profile
from recommender.models import Interaction, TasteEvent, merge_history, set_state
from recommender.profile import Signal, build_profile

from .test_engine import LIVRE, IndexTestCase

State = Interaction.State


class PesoDosEstadosTests(IndexTestCase):
    def test_favorito_puxa_o_dobro_de_um_curti(self):
        # Mesmos dois títulos e mesma idade; só o peso de um deles muda.
        empate = build_profile(self.indice, [Signal(1, 1.0), Signal(4, 1.0)], 1e6, 0.5)
        favorito = build_profile(self.indice, [Signal(1, 2.0), Signal(4, 1.0)], 1e6, 0.5)
        a, b = self.indice.vector(1), self.indice.vector(4)
        self.assertGreater(float(favorito @ a) - float(favorito @ b), float(empate @ a) - float(empate @ b))

        # Com recência neutra, o perfil com favorito é a média ponderada 2:1 normalizada.
        esperado = (2 * a + b) / 3
        np.testing.assert_allclose(favorito, esperado / np.linalg.norm(esperado), rtol=1e-5)

    def test_peso_zero_nao_muda_o_vetor(self):
        so_curti = build_profile(self.indice, [Signal(1, 1.0)], 6, 0.5)
        com_zeros = build_profile(self.indice, [Signal(1, 1.0), Signal(4, 0.0), Signal(7, 0.0)], 6, 0.5)
        np.testing.assert_allclose(so_curti, com_zeros, rtol=1e-6)

    def test_peso_zero_nao_envelhece_os_curtidos(self):
        # Sem a regra, os dois "já vi" recentes deixariam o curti antigo com peso 1/4 frente ao
        # segundo curti; com ela, os curtidos têm idades 1 e 0.
        base = build_profile(self.indice, [Signal(1, 1.0), Signal(4, 1.0)], 1, 0.5)
        com_vistos = build_profile(
            self.indice, [Signal(1, 1.0), Signal(7, 0.0), Signal(8, 0.0), Signal(4, 1.0)], 1, 0.5,
        )
        np.testing.assert_allclose(base, com_vistos, rtol=1e-6)

    def test_so_peso_zero_nao_forma_perfil(self):
        self.assertIsNone(build_profile(self.indice, [Signal(1, 0.0)], 6, 0.5))

    def test_peso_zero_sai_das_recomendacoes(self):
        recomendacoes, _ = recommend_for_profile(self.indice, [Signal(1, 1.0), Signal(4, 0.0)], LIVRE)
        self.assertNotIn(4, [r.title_id for r in recomendacoes])
        recomendacoes, perfil = recommend_for_profile(self.indice, [Signal(4, 0.0)], LIVRE)
        self.assertIsNone(perfil)
        self.assertNotIn(4, [r.title_id for r in recomendacoes])


class EstadosApiTests(ApiTestCase):
    def marcar(self, titulo, estado, kind='movie'):
        return self.client.post(
            reverse('api:interaction-add'),
            data=json.dumps({'title_id': self.pk(titulo, kind), 'state': estado}),
            content_type='application/json',
        )

    def estados(self):
        return {h['title']['title']: h['state'] for h in self.client.get(reverse('api:profile')).json()['history']}

    def eventos(self):
        return list(TasteEvent.objects.order_by('id').values_list('title__title', 'from_state', 'to_state'))

    def test_cada_estado_e_aceito(self):
        for estado in State.values:
            with self.subTest(estado=estado):
                self.assertEqual(self.marcar('Orbit', estado).status_code, 201)
                self.assertEqual(self.estados(), {'Orbit': estado})

    def test_estado_desconhecido_e_recusado(self):
        resposta = self.marcar('Orbit', 'adorei')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('favorite', resposta.json()['error'])

    def test_formato_antigo_continua_funcionando(self):
        self.curtir('Orbit', -1)
        historico = self.client.get(reverse('api:profile')).json()['history']
        self.assertEqual((historico[0]['state'], historico[0]['signal']), ('dislike', -1))

    def test_curtir_um_titulo_da_watchlist_o_tira_de_la(self):
        self.marcar('Orbit', State.WATCHLIST)
        self.marcar('Orbit', State.LIKE)
        self.assertEqual(self.estados(), {'Orbit': 'like'})
        self.assertEqual(Interaction.objects.count(), 1)

    def test_seen_e_watchlist_nao_formam_perfil_nem_sao_recomendados(self):
        self.marcar('Paris Rain', State.SEEN)
        self.marcar('Summer Letters', State.WATCHLIST)
        dados = self.client.get(reverse('api:recommendations'), {'obscurity': 0}).json()
        self.assertEqual(dados['mode'], 'cold_start')
        recomendados = {r['title'] for r in dados['results']}
        self.assertTrue({'Paris Rain', 'Summer Letters'}.isdisjoint(recomendados))

    def test_favorito_personaliza(self):
        self.marcar('Paris Rain', State.FAVORITE)
        dados = self.client.get(reverse('api:recommendations'), {'obscurity': 0}).json()
        self.assertEqual(dados['mode'], 'profile')
        self.assertEqual(dados['results'][0]['title'], 'Summer Letters')

    def test_cada_mudanca_gera_um_evento(self):
        self.marcar('Orbit', State.WATCHLIST)
        self.marcar('Orbit', State.WATCHLIST)  # repetido: sem evento
        self.marcar('Orbit', State.FAVORITE)
        self.client.delete(reverse('api:interaction-remove', args=[self.pk('Orbit')]))
        self.assertEqual(self.eventos(), [
            ('Orbit', '', 'watchlist'),
            ('Orbit', 'watchlist', 'favorite'),
            ('Orbit', 'favorite', ''),
        ])

    def test_limpar_o_perfil_gera_um_evento_por_titulo(self):
        self.marcar('Orbit', State.LIKE)
        self.marcar('Paris Rain', State.SEEN)
        TasteEvent.objects.all().delete()
        self.client.delete(reverse('api:profile'))
        self.assertEqual(sorted(self.eventos()), [('Orbit', 'like', ''), ('Paris Rain', 'seen', '')])

    def test_remover_sem_sessao_nao_quebra(self):
        resposta = self.client.delete(reverse('api:interaction-remove', args=[self.pk('Orbit')]))
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(TasteEvent.objects.exists())

    def test_mescla_leva_os_eventos_junto(self):
        set_state('s:a', self.pk_obj('Orbit'), State.LIKE)
        set_state('u:9', self.pk_obj('Paris Rain'), State.SEEN)
        merge_history('s:a', 'u:9')
        self.assertEqual(set(TasteEvent.objects.values_list('owner', flat=True)), {'u:9'})
        self.assertEqual(TasteEvent.objects.count(), 2)

    def pk_obj(self, titulo):
        return Title.objects.get(pk=self.pk(titulo))
