from dataclasses import asdict

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from catalog.tests.factories import sample_catalog
from recommender.config import RecommenderConfig
from recommender.engine import (
    HybridParams,
    build_index,
    describe_profile,
    mmr,
    recommend_for_profile,
    similar_to,
    similarity_matrix,
)
from recommender.features import split_run_on_names
from recommender.profile import DISLIKE, LIKE, Signal, build_profile, recency_weights
from recommender.quality import bayesian_rating


def catalog_frame():
    """DataFrame no formato de engine._load_catalog, com id = external_id + 100 * tipo."""
    linhas = []
    for registro in sample_catalog():
        dados = asdict(registro)
        dados['id'] = int(registro.external_id)
        linhas.append(dados)
    df = pd.DataFrame(linhas)
    df['year'] = pd.to_numeric(df['year'], errors='coerce')
    return df


# Sem filtros que escondam o título de 3 votos, a não ser que o teste peça.
LIVRE = HybridParams(k=10, alpha=1.0, obscurity=0.0, diversity=0.0)


class IndexTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = RecommenderConfig()
        cls.indice = build_index(catalog_frame(), cls.config)

    def titulos(self, recomendacoes):
        nomes = dict(zip(catalog_frame()['id'], catalog_frame()['title']))
        return [nomes[r.title_id] for r in recomendacoes]


class FeaturesTests(IndexTestCase):
    def test_linhas_tem_norma_unitaria(self):
        normas = np.sqrt(self.indice.matrix.multiply(self.indice.matrix).sum(axis=1)).A1
        np.testing.assert_allclose(normas, 1.0, rtol=1e-5)

    def test_similaridade_se_decompoe_por_bloco(self):
        [rec, *_] = similar_to(self.indice, 1, LIVRE)
        self.assertAlmostEqual(sum(rec.contributions.values()), rec.similarity, places=5)

    def test_nomes_sem_separador_sao_agrupados(self):
        self.assertEqual(
            split_run_on_names('Sam Worthington Samuel L. Jackson Benicio del Toro Robert Downey Jr. Zoe Saldana'),
            ['Sam Worthington', 'Samuel L. Jackson', 'Benicio del Toro', 'Robert Downey Jr.', 'Zoe Saldana'],
        )

    def test_matriz_de_similaridade_e_simetrica_com_diagonal_um(self):
        ids, matriz = similarity_matrix(self.indice, [1, 2, 4])
        self.assertEqual(ids, [1, 2, 4])
        np.testing.assert_allclose(matriz, matriz.T, atol=1e-6)
        np.testing.assert_allclose(np.diag(matriz), 1.0, rtol=1e-5)
        self.assertGreater(matriz[0, 1], matriz[0, 2])  # sci-fi x sci-fi > sci-fi x romance


class SimilaresTests(IndexTestCase):
    def test_parecidos_compartilham_genero_e_direcao(self):
        nomes = self.titulos(similar_to(self.indice, 1, LIVRE))
        self.assertEqual(nomes[0], 'Space Return')
        self.assertLess(nomes.index('Space Return'), nomes.index('Paris Rain') if 'Paris Rain' in nomes else 99)

    def test_nao_recomenda_o_proprio_titulo_nem_a_mesma_obra_de_outra_fonte(self):
        ids = [r.title_id for r in similar_to(self.indice, 1, LIVRE)]
        self.assertNotIn(1, ids)
        self.assertNotIn(8, ids)  # 'Space Odyssey' (2014) do MyAnimeList

    def test_explicacao_traz_tokens_em_comum(self):
        [rec, *_] = similar_to(self.indice, 1, LIVRE)
        rotulos = {m['label'] for m in rec.reasons}
        self.assertIn('Ridley Scott', rotulos)

    def test_filtro_de_obscuridade_remove_titulo_com_poucos_votos(self):
        com_obscuros = [r.title_id for r in similar_to(self.indice, 1, LIVRE)]
        sem_obscuros = [r.title_id for r in similar_to(self.indice, 1, HybridParams(k=10, obscurity=0.2, diversity=0))]
        self.assertIn(6, com_obscuros)
        self.assertNotIn(6, sem_obscuros)

    def test_alfa_baixo_favorece_qualidade(self):
        so_similaridade = similar_to(self.indice, 1, LIVRE)
        com_qualidade = similar_to(self.indice, 1, HybridParams(k=10, alpha=0.0, obscurity=0.0, diversity=0))
        self.assertEqual([r.score for r in com_qualidade], sorted([r.score for r in com_qualidade], reverse=True))
        self.assertNotEqual([r.title_id for r in so_similaridade], [r.title_id for r in com_qualidade])

    def test_filtro_por_tipo(self):
        resultados = similar_to(self.indice, 1, HybridParams(k=10, obscurity=0, kinds=('anime',)))
        self.assertEqual({self.indice.kinds[self.indice.row_of[r.title_id]] for r in resultados}, {'anime'})

    def test_parametros_fora_da_faixa_sao_ajustados(self):
        params = HybridParams(k=500, alpha=3, rating_weight=-1, obscurity=2, diversity=5, kinds=('movie', 'x')).clamped()
        self.assertEqual((params.k, params.alpha, params.rating_weight), (50, 1.0, 0.0))
        self.assertEqual((params.obscurity, params.diversity, params.kinds), (0.95, 0.9, ('movie',)))


class MMRTests(SimpleTestCase):
    def test_diversidade_evita_itens_redundantes(self):
        from scipy import sparse

        vetores = sparse.csr_matrix(np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32))
        scores = np.array([1.0, 0.99, 0.6])
        self.assertEqual(list(mmr(vetores, scores, 2, 0.0)), [0, 1])
        self.assertEqual(list(mmr(vetores, scores, 2, 0.5)), [0, 2])


class PerfilTests(IndexTestCase):
    def test_pesos_de_recencia_dobram_a_cada_meia_vida(self):
        pesos = recency_weights(3, half_life=1)
        np.testing.assert_allclose(pesos, [0.25, 0.5, 1.0])

    def test_sem_curtidas_nao_ha_perfil(self):
        self.assertIsNone(build_profile(self.indice, [Signal(1, DISLIKE)], 6, 0.5))
        recomendacoes, perfil = recommend_for_profile(self.indice, [], LIVRE)
        self.assertIsNone(perfil)
        self.assertEqual([r.similarity for r in recomendacoes], [0.0] * len(recomendacoes))

    def test_perfil_recomenda_vizinhos_do_que_foi_curtido(self):
        recomendacoes, perfil = recommend_for_profile(self.indice, [Signal(4, LIKE)], LIVRE)
        self.assertEqual(self.titulos(recomendacoes)[0], 'Summer Letters')
        self.assertAlmostEqual(float(np.linalg.norm(perfil)), 1.0, places=5)

    def test_nao_curti_afasta_o_perfil(self):
        so_like = build_profile(self.indice, [Signal(1, LIKE)], 6, 0.5)
        com_dislike = build_profile(self.indice, [Signal(1, LIKE), Signal(2, DISLIKE)], 6, 0.5)
        vizinho = self.indice.vector(2)
        self.assertLess(float(com_dislike @ vizinho), float(so_like @ vizinho))

    def test_historico_fica_fora_das_recomendacoes(self):
        recomendacoes, _ = recommend_for_profile(self.indice, [Signal(1, LIKE), Signal(3, LIKE)], LIVRE)
        self.assertTrue({1, 3, 8}.isdisjoint(r.title_id for r in recomendacoes))

    def test_resumo_do_perfil(self):
        _, perfil = recommend_for_profile(self.indice, [Signal(1, LIKE), Signal(7, LIKE)], LIVRE)
        resumo = describe_profile(self.indice, perfil)
        self.assertEqual(resumo['dna'][0]['label'], 'Science Fiction')
        self.assertAlmostEqual(sum(resumo['blocks'].values()), 1.0, places=5)
        self.assertGreater(resumo['kinds']['anime'], 0)
        self.assertGreater(resumo['kinds']['movie'], 0)


class QualidadeTests(SimpleTestCase):
    def test_rating_bayesiano_puxa_poucos_votos_para_a_media(self):
        poucos, muitos = bayesian_rating([9.5, 9.5], [3, 30000], m=1000, c=6.5)
        self.assertLess(poucos, 7.0)
        self.assertGreater(muitos, 9.0)
