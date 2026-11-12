"""Configurações e LGPD: nome público, senha, exportação, exclusão e limpeza dos anônimos."""
import json
from datetime import timedelta
from io import StringIO

from axes.models import AccessAttempt
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from recommender.models import Interaction, TasteEvent, UserPreferences

from .models import User
from .tests import SENHA, ContaTestCase


class ConfiguracoesTestCase(ContaTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('ana@exemplo.com', SENHA, username='ana')
        self.client.force_login(self.user)
        self.url = reverse('accounts:settings')

    def enviar(self, acao, **campos):
        return self.client.post(self.url, {'action': acao, **campos})


class NomePublicoTests(ConfiguracoesTestCase):
    def test_exige_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:export')).status_code, 302)

    def test_troca_e_normaliza(self):
        resposta = self.enviar('username', username='  Ana_Cine ')
        self.assertRedirects(resposta, self.url, fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'ana_cine')

    def test_formato_invalido_reservado_e_em_uso(self):
        User.objects.create_user('bia@exemplo.com', SENHA, username='bia')
        for nome, trecho in [('ab', '3 a 30'), ('com espaço', '3 a 30'), ('ação', '3 a 30'),
                             ('admin', 'reservado'), ('BIA', 'já está em uso')]:
            with self.subTest(nome=nome):
                resposta = self.enviar('username', username=nome)
                self.assertEqual(resposta.status_code, 400)
                self.assertContains(resposta, trecho, status_code=400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'ana')

    def test_manter_o_proprio_nome_e_valido(self):
        self.assertEqual(self.enviar('username', username='ana').status_code, 302)


class SenhaTests(ConfiguracoesTestCase):
    def test_troca_exige_a_atual_e_mantem_a_sessao(self):
        errada = self.enviar('password', old_password='nao-e-esta', new_password1='outra-senha-boa-9',
                             new_password2='outra-senha-boa-9')
        self.assertEqual(errada.status_code, 400)

        certa = self.enviar('password', old_password=SENHA, new_password1='outra-senha-boa-9',
                            new_password2='outra-senha-boa-9')
        self.assertRedirects(certa, self.url, fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('outra-senha-boa-9'))
        self.assertEqual(self.client.get(self.url).status_code, 200)  # continua logado


class ExportacaoTests(ConfiguracoesTestCase):
    def test_exporta_todo_o_historico_sem_a_senha(self):
        self.curtir('Orbit')
        self.curtir('Orbit', -1)
        self.curtir('Paris Rain')
        UserPreferences.objects.create(user=self.user, values={'alpha': 0.4})

        resposta = self.client.get(reverse('accounts:export'))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('attachment; filename="angulo-ana-', resposta['Content-Disposition'])
        dados = json.loads(resposta.content)

        self.assertEqual(dados['account']['email'], 'ana@exemplo.com')
        self.assertEqual(dados['preferences'], {'alpha': 0.4})
        self.assertEqual({i['title']: i['state'] for i in dados['interactions']}, {'Orbit': 'dislike', 'Paris Rain': 'like'})
        self.assertEqual(len(dados['events']), 3)
        self.assertNotIn(self.user.password, resposta.content.decode())
        self.assertNotIn('password', resposta.content.decode())


class ExclusaoTests(ConfiguracoesTestCase):
    def test_senha_errada_nao_exclui(self):
        resposta = self.enviar('delete', password='nao-e-esta')
        self.assertEqual(resposta.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_exclui_tudo_e_encerra_a_sessao(self):
        self.curtir('Orbit')
        self.curtir('Paris Rain', -1)
        UserPreferences.objects.create(user=self.user, values={'alpha': 0.4})
        AccessAttempt.objects.create(username='ana@exemplo.com', ip_address='1.2.3.4', failures_since_start=1,
                                     get_data='', post_data='', http_accept='', path_info='/entrar/', user_agent='')
        outro = User.objects.create_user('bia@exemplo.com', SENHA)
        Interaction.objects.create(owner=outro.owner, title_id=self.pk('Orbit'), state='like')
        dono = self.user.owner

        resposta = self.enviar('delete', password=SENHA)
        self.assertRedirects(resposta, reverse('web:home'), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Interaction.objects.filter(owner=dono).exists())
        self.assertFalse(TasteEvent.objects.filter(owner=dono).exists())
        self.assertFalse(UserPreferences.objects.filter(user_id=self.user.pk).exists())
        self.assertFalse(AccessAttempt.objects.filter(username='ana@exemplo.com').exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        # Os dados de outra conta ficam.
        self.assertTrue(Interaction.objects.filter(owner=outro.owner).exists())


class LimpezaAnonimaTests(ContaTestCase):
    def sessao_com_curtida(self, titulo, expirada=False):
        cliente = self.client_class()
        cliente.post(
            reverse('api:interaction-add'),
            data=json.dumps({'title_id': self.pk(titulo), 'state': 'like'}),
            content_type='application/json',
        )
        chave = cliente.session.session_key
        if expirada:
            Session.objects.filter(session_key=chave).update(expire_date=timezone.now() - timedelta(days=1))
        return f's:{chave}'

    def test_apaga_so_os_orfaos(self):
        viva = self.sessao_com_curtida('Orbit')
        expirada = self.sessao_com_curtida('Paris Rain', expirada=True)
        Interaction.objects.create(owner='s:sumiu', title_id=self.pk('Summer Letters'), state='like')
        TasteEvent.objects.create(owner='s:sumiu', title_id=self.pk('Summer Letters'), to_state='like')
        conta = User.objects.create_user('ana@exemplo.com', SENHA)
        Interaction.objects.create(owner=conta.owner, title_id=self.pk('Orbit'), state='like')

        saida = StringIO()
        call_command('purge_anonymous', stdout=saida)
        self.assertIn('2 perfis anônimos órfãos', saida.getvalue())

        donos = set(Interaction.objects.values_list('owner', flat=True))
        self.assertEqual(donos, {viva, conta.owner})
        self.assertFalse(TasteEvent.objects.filter(owner__in=[expirada, 's:sumiu']).exists())
        self.assertFalse(Session.objects.filter(session_key=expirada[2:]).exists())

    def test_rota_do_cron_exige_o_segredo(self):
        url = reverse('api:cron-purge-anonymous')
        Interaction.objects.create(owner='s:sumiu', title_id=self.pk('Orbit'), state='like')

        with override_settings(CRON_SECRET=''):
            self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION='Bearer ').status_code, 401)
        with override_settings(CRON_SECRET='s3gredo'):
            self.assertEqual(self.client.get(url).status_code, 401)
            self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION='Bearer errado').status_code, 401)
            self.assertEqual(self.client.post(url, HTTP_AUTHORIZATION='Bearer s3gredo').status_code, 405)
            self.assertTrue(Interaction.objects.filter(owner='s:sumiu').exists())

            resposta = self.client.get(url, HTTP_AUTHORIZATION='Bearer s3gredo')
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta.json()['interactions'], 1)
        self.assertFalse(Interaction.objects.filter(owner='s:sumiu').exists())
