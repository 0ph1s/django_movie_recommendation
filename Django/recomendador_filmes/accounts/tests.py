import json
from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from api.tests import ApiTestCase
from catalog.models import Title
from recommender.models import Interaction, UserPreferences, merge_history

from .models import User

SENHA = 'cosseno-similar-42'


class ContaTestCase(ApiTestCase):
    def criar_conta(self, email='ana@exemplo.com', senha=SENHA, **extra):
        return self.client.post(reverse('accounts:signup'), {'email': email, 'password': senha, **extra})

    def entrar(self, email='ana@exemplo.com', senha=SENHA, **extra):
        return self.client.post(reverse('accounts:login'), {'username': email, 'password': senha, **extra})

    def mensagens(self, resposta):
        return [str(m) for m in resposta.context['messages']] if resposta.context else []

    def historico(self, dono):
        return {i.title.title: i.signal for i in Interaction.objects.filter(owner=dono).select_related('title')}


class CadastroTests(ContaTestCase):
    def test_cria_conta_com_username_gerado_e_ja_entra(self):
        resposta = self.criar_conta(email='Ana@Exemplo.COM')
        self.assertRedirects(resposta, reverse('web:playground'), fetch_redirect_response=False)

        user = User.objects.get()
        self.assertEqual(user.email, 'ana@exemplo.com')
        self.assertRegex(user.username, r'^cinefilo_\d{4,}$')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_email_repetido_e_recusado_sem_diferenciar_maiusculas(self):
        User.objects.create_user('ana@exemplo.com', SENHA)
        resposta = self.criar_conta(email='ANA@exemplo.com')
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('Já existe uma conta', resposta.content.decode())
        self.assertEqual(User.objects.count(), 1)

    def test_senha_fraca_e_recusada(self):
        resposta = self.criar_conta(senha='12345678')
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_usernames_gerados_nao_colidem(self):
        nomes = {User.objects.create_user(f'p{i}@exemplo.com', SENHA).username for i in range(20)}
        self.assertEqual(len(nomes), 20)

    def test_next_externo_e_ignorado(self):
        resposta = self.criar_conta(next='https://malicioso.example/roubo')
        self.assertRedirects(resposta, reverse('web:playground'), fetch_redirect_response=False)

    def test_next_interno_e_respeitado(self):
        resposta = self.criar_conta(next='/?origem=teste')
        self.assertRedirects(resposta, '/?origem=teste', fetch_redirect_response=False)


class LoginTests(ContaTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('ana@exemplo.com', SENHA)

    def test_entra_pelo_email_em_qualquer_caixa(self):
        resposta = self.entrar(email='ANA@exemplo.com')
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_senha_errada_mostra_erro(self):
        resposta = self.entrar(senha='errada-mas-longa')
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('E-mail ou senha incorretos.', resposta.content.decode())

    def test_cinco_erros_bloqueiam_ate_a_senha_certa(self):
        for _ in range(4):
            self.assertEqual(self.entrar(senha='errada-mas-longa').status_code, 200)
        self.assertEqual(self.entrar(senha='errada-mas-longa').status_code, 429)
        bloqueado = self.entrar()
        self.assertEqual(bloqueado.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_sair_exige_post_e_limpa_a_sessao(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        self.client.post(reverse('accounts:logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logado_e_redirecionado_ao_abrir_entrar(self):
        self.client.force_login(self.user)
        resposta = self.client.get(reverse('accounts:login'))
        self.assertRedirects(resposta, reverse('web:playground'), fetch_redirect_response=False)


class MesclaTests(ContaTestCase):
    def test_cadastro_traz_o_historico_da_sessao(self):
        self.curtir('Space Odyssey')
        self.curtir('Paris Rain', sinal=-1)
        resposta = self.criar_conta()
        user = User.objects.get()

        self.assertEqual(self.historico(user.owner), {'Space Odyssey': 1, 'Paris Rain': -1})
        self.assertFalse(Interaction.objects.filter(owner__startswith='s:').exists())
        seguinte = self.client.get(resposta.url)
        self.assertIn('2 títulos da sessão foram somados ao seu perfil.', self.mensagens(seguinte))

    def test_login_mescla_e_a_avaliacao_mais_recente_vence(self):
        user = User.objects.create_user('ana@exemplo.com', SENHA)
        antigo = timezone.now() - timedelta(days=3)
        Interaction.objects.create(owner=user.owner, title_id=self.pk('Space Odyssey'), signal=1)
        Interaction.objects.create(owner=user.owner, title_id=self.pk('Space Return'), signal=1)
        Interaction.objects.filter(owner=user.owner).update(updated_at=antigo)

        self.curtir('Space Odyssey', sinal=-1)   # mais recente que a da conta: vence
        self.curtir('Paris Rain')                # só na sessão: entra
        self.entrar()

        self.assertEqual(
            self.historico(user.owner),
            {'Space Odyssey': -1, 'Space Return': 1, 'Paris Rain': 1},
        )

    def test_conta_vence_quando_e_mais_recente(self):
        user = User.objects.create_user('ana@exemplo.com', SENHA)
        self.curtir('Space Odyssey', sinal=-1)
        sessao = f's:{self.client.session.session_key}'
        Interaction.objects.filter(owner=sessao).update(updated_at=timezone.now() - timedelta(days=1))
        Interaction.objects.create(owner=user.owner, title_id=self.pk('Space Odyssey'), signal=1)

        self.entrar()
        self.assertEqual(self.historico(user.owner), {'Space Odyssey': 1})

    def test_mescla_preserva_a_ordem_cronologica(self):
        Interaction.objects.create(owner='s:x', title_id=self.pk('Space Odyssey'), signal=1)
        Interaction.objects.create(owner='u:1', title_id=self.pk('Paris Rain'), signal=1)
        Interaction.objects.filter(owner='s:x').update(updated_at=timezone.now() - timedelta(days=2))
        self.assertEqual(merge_history('s:x', 'u:1'), 1)
        ordem = list(Interaction.objects.filter(owner='u:1').values_list('title__title', flat=True))
        self.assertEqual(ordem, ['Space Odyssey', 'Paris Rain'])

    def test_historico_da_conta_segue_a_pessoa(self):
        self.criar_conta()
        self.curtir('Space Odyssey')
        self.client.post(reverse('accounts:logout'))
        self.assertEqual(self.client.get(reverse('api:profile')).json()['history'], [])

        self.entrar()
        historico = self.client.get(reverse('api:profile')).json()['history']
        self.assertEqual([h['title']['title'] for h in historico], ['Space Odyssey'])


class PreferenciasTests(ContaTestCase):
    url = reverse('api:preferences')

    def put(self, dados):
        return self.client.put(self.url, data=json.dumps(dados), content_type='application/json')

    def test_padroes_sem_nada_salvo(self):
        dados = self.client.get(self.url).json()
        self.assertFalse(dados['customized'])
        self.assertEqual(dados['values'], dados['defaults'])

    def test_anonimo_salva_na_sessao_e_valores_sao_limitados(self):
        dados = self.put({'alpha': 0.4, 'diversity': 5, 'kinds': ['anime', 'xyz']}).json()
        self.assertTrue(dados['customized'])
        self.assertEqual(dados['values']['alpha'], 0.4)
        self.assertEqual(dados['values']['diversity'], 0.8)
        self.assertEqual(dados['values']['kinds'], ['anime'])
        self.assertFalse(UserPreferences.objects.exists())

    def test_todos_os_tipos_equivalem_ao_padrao(self):
        dados = self.put({'kinds': ['movie', 'series', 'anime']}).json()
        self.assertFalse(dados['customized'])

    def test_valor_invalido_e_recusado(self):
        self.assertEqual(self.put({'alpha': 'muito'}).status_code, 400)

    def test_restaurar_padrao(self):
        self.put({'alpha': 0.4})
        dados = self.client.delete(self.url).json()
        self.assertFalse(dados['customized'])

    def test_conta_nova_herda_as_preferencias_da_sessao(self):
        self.put({'alpha': 0.4})
        self.criar_conta()
        self.assertEqual(UserPreferences.objects.get().values, {'alpha': 0.4})
        self.assertEqual(self.client.get(self.url).json()['values']['alpha'], 0.4)

    def test_conta_existente_mantem_as_suas(self):
        user = User.objects.create_user('ana@exemplo.com', SENHA)
        UserPreferences.objects.create(user=user, values={'alpha': 0.9})
        self.put({'alpha': 0.4})
        self.entrar()
        self.assertEqual(self.client.get(self.url).json()['values']['alpha'], 0.9)

    def test_conta_sem_ajustes_herda_os_da_sessao(self):
        User.objects.create_user('ana@exemplo.com', SENHA)
        self.put({'obscurity': 0.5})
        self.entrar()
        self.assertEqual(self.client.get(self.url).json()['values']['obscurity'], 0.5)

    def test_playground_nasce_com_as_preferencias(self):
        self.put({'alpha': 0.4})
        html = self.client.get(reverse('web:playground')).content.decode()
        self.assertIn('value="0.4" data-param="alpha"', html)


class OfertaDeContaTests(ContaTestCase):
    def oferta(self):
        return self.client.get(reverse('api:profile')).json()['account_offer']

    def marcar(self, n):
        titulos = list(Title.objects.values_list('title', 'kind'))
        for titulo, kind in titulos[:n]:
            self.curtir(titulo, kind=kind)

    def test_aparece_com_cinco_titulos(self):
        self.marcar(4)
        self.assertFalse(self.oferta())
        self.marcar(5)
        self.assertTrue(self.oferta())

    @patch('api.views.OFFER_AGAIN', 7)
    def test_dispensada_volta_uma_vez_no_segundo_limiar(self):
        # O catálogo de teste é pequeno: o segundo limiar (15 em produção) cai para 7 aqui.
        self.marcar(5)
        self.client.post(reverse('api:account-offer-dismiss'))
        self.assertFalse(self.oferta())
        self.marcar(6)
        self.assertFalse(self.oferta())
        self.marcar(7)
        self.assertTrue(self.oferta())
        self.client.post(reverse('api:account-offer-dismiss'))
        self.marcar(8)
        self.assertFalse(self.oferta())

    def test_logado_nunca_ve(self):
        self.criar_conta()
        self.marcar(6)
        self.assertFalse(self.oferta())

