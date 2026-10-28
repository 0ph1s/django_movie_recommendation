from django.test import SimpleTestCase
from django.urls import reverse

from .forms import MAXIMO_RECOMENDACOES
from .recomendador import recomendar


class RecomendadorTests(SimpleTestCase):
    def test_retorna_quantidade_pedida(self):
        filme, recomendacoes = recomendar('Avatar', 5)
        self.assertEqual(filme['titulo'], 'Avatar')
        self.assertEqual(len(recomendacoes), 5)

    def test_busca_ignora_maiusculas_e_espacos(self):
        filme, _ = recomendar('  the dark knight ', 1)
        self.assertEqual(filme['titulo'], 'The Dark Knight')

    def test_filme_inexistente(self):
        self.assertEqual(recomendar('xyzxyzxyz', 5), (None, []))

    def test_titulo_duplicado_usa_o_mais_popular(self):
        filme, _ = recomendar('Batman', 1)
        self.assertEqual(filme['ano'], '1989')

    def test_nao_recomenda_o_proprio_filme_nem_repete(self):
        filme, recomendacoes = recomendar('Batman', 30)
        titulos = [r['titulo'] for r in recomendacoes]
        self.assertNotIn(filme['titulo'], titulos)
        self.assertEqual(len(titulos), len(set(titulos)))


class IndexViewTests(SimpleTestCase):
    def test_get_exibe_formulario(self):
        resposta = self.client.get(reverse('index'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'name="filme"')

    def test_post_valido_lista_recomendacoes(self):
        resposta = self.client.post(reverse('index'), {'filme': 'avatar', 'quantidade': 3})
        self.assertEqual(len(resposta.context['recomendacoes']), 3)
        self.assertContains(resposta, 'Recomendações para "Avatar" (2009)')

    def test_post_filme_nao_encontrado(self):
        resposta = self.client.post(reverse('index'), {'filme': 'xyzxyzxyz', 'quantidade': 3})
        self.assertContains(resposta, 'não encontrado')

    def test_quantidade_invalida_nao_gera_erro_500(self):
        for quantidade in ['', 'abc', '0', '-3', str(MAXIMO_RECOMENDACOES + 1)]:
            with self.subTest(quantidade=quantidade):
                resposta = self.client.post(
                    reverse('index'), {'filme': 'Avatar', 'quantidade': quantidade}
                )
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.context['recomendacoes'], [])
                self.assertTrue(resposta.context['form'].errors)
