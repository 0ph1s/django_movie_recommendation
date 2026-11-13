"""Foto de perfil: padrão, envio (com reprocessamento e sem metadados), remoção e LGPD."""
import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from .data import delete_user_data
from .models import DEFAULT_PHOTO, ProfilePhoto, User
from .test_settings import ConfiguracoesTestCase
from .tests import SENHA as SENHA_TESTE


def imagem(formato='JPEG', tamanho=(800, 600), cor=(200, 40, 40), exif=True):
    saida = io.BytesIO()
    figura = Image.new('RGB', tamanho, cor)
    extra = {}
    if exif and formato == 'JPEG':
        dados = Image.Exif()
        dados[0x010F] = 'Camera de teste'          # Make
        dados[0x8825] = {2: (23.0, 33.0, 0.0)}    # GPSInfo: latitude
        extra['exif'] = dados.tobytes()
    figura.save(saida, formato, **extra)
    nome = {'JPEG': 'foto.jpg', 'PNG': 'foto.png', 'WEBP': 'foto.webp'}[formato]
    return SimpleUploadedFile(nome, saida.getvalue(), content_type=f'image/{formato.lower()}')


class FotoDePerfilTests(ConfiguracoesTestCase):
    def enviar_foto(self, arquivo):
        return self.client.post(self.url, {'action': 'photo', 'photo': arquivo})

    def test_sem_foto_usa_a_padrao(self):
        self.assertEqual(self.user.photo_version, 0)
        self.assertIn(DEFAULT_PHOTO, self.user.photo_url)
        self.assertContains(self.client.get(reverse('web:home')), DEFAULT_PHOTO)
        self.assertEqual(self.client.get(reverse('accounts:photo')).status_code, 404)

    def test_envio_recorta_em_webp_quadrado_sem_metadados(self):
        resposta = self.enviar_foto(imagem())
        self.assertRedirects(resposta, self.url)

        self.user.refresh_from_db()
        self.assertGreater(self.user.photo_version, 0)
        self.assertIn(f'?v={self.user.photo_version}', self.user.photo_url)

        foto = self.client.get(reverse('accounts:photo'))
        self.assertEqual(foto.status_code, 200)
        self.assertEqual(foto['Content-Type'], 'image/webp')
        guardada = Image.open(io.BytesIO(foto.content))
        self.assertEqual((guardada.format, guardada.size), ('WEBP', (384, 384)))
        self.assertFalse(guardada.getexif())
        self.assertNotIn(b'Camera de teste', foto.content)

        # O cabeçalho passa a mostrar a foto enviada.
        self.assertContains(self.client.get(reverse('web:home')), self.user.photo_url)

    def test_png_com_transparencia_e_webp_sao_aceitos(self):
        saida = io.BytesIO()
        Image.new('RGBA', (300, 500), (0, 0, 0, 0)).save(saida, 'PNG')
        self.assertRedirects(self.enviar_foto(SimpleUploadedFile('t.png', saida.getvalue())), self.url)
        self.assertRedirects(self.enviar_foto(imagem('WEBP')), self.url)

    def test_recusa_o_que_nao_e_imagem(self):
        for arquivo in (
            SimpleUploadedFile('foto.png', b'isto nao e uma imagem'),
            SimpleUploadedFile('foto.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
            imagem('JPEG').__class__('foto.gif', _gif(), content_type='image/gif'),
        ):
            resposta = self.enviar_foto(arquivo)
            self.assertEqual(resposta.status_code, 400, arquivo.name)
        self.assertEqual(self.enviar_foto(SimpleUploadedFile('x.jpg', b'')).status_code, 400)
        self.assertFalse(ProfilePhoto.objects.exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.photo_version, 0)

    def test_sem_arquivo_pede_uma_imagem(self):
        resposta = self.client.post(self.url, {'action': 'photo'})
        self.assertContains(resposta, 'Escolha uma imagem.', status_code=400)

    def test_remover_volta_a_padrao(self):
        self.enviar_foto(imagem())
        self.assertRedirects(self.client.post(self.url, {'action': 'photo_remove'}), self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.photo_version, 0)
        self.assertFalse(ProfilePhoto.objects.exists())

    def test_foto_exige_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:photo')).status_code, 302)

    def test_exportacao_inclui_e_exclusao_apaga_a_foto(self):
        self.enviar_foto(imagem())
        dados = json.loads(self.client.get(reverse('accounts:export')).content)
        self.assertTrue(dados['account']['profile_photo'].startswith('data:image/webp;base64,'))
        delete_user_data(User.objects.get(pk=self.user.pk))
        self.assertFalse(ProfilePhoto.objects.exists())


def _gif():
    saida = io.BytesIO()
    Image.new('RGB', (10, 10)).save(saida, 'GIF')
    return saida.getvalue()


class EnvioSemRecarregarTests(ConfiguracoesTestCase):
    """Com JavaScript, a página envia por fetch (X-Requested-With: fetch) e recebe JSON."""

    def ajax(self, **dados):
        return self.client.post(self.url, dados, HTTP_X_REQUESTED_WITH='fetch')

    def test_foto_devolve_o_estado_novo_da_conta(self):
        resposta = self.ajax(action='photo', photo=imagem())
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados['ok'])
        self.assertEqual(dados['message'], 'Foto de perfil atualizada.')
        self.user.refresh_from_db()
        self.assertEqual(dados['account'], {'username': 'ana', 'photo_url': self.user.photo_url, 'has_photo': True})

        removida = self.ajax(action='photo_remove').json()
        self.assertFalse(removida['account']['has_photo'])
        self.assertIn(DEFAULT_PHOTO, removida['account']['photo_url'])

    def test_erros_voltam_por_campo(self):
        resposta = self.ajax(action='photo', photo=SimpleUploadedFile('x.png', b'nada'))
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(list(resposta.json()['errors']), ['photo'])

        nome = self.ajax(action='username', username='admin')
        self.assertEqual(nome.status_code, 400)
        self.assertIn('username', nome.json()['errors'])

        senha = self.ajax(action='password', old_password='errada', new_password1='x', new_password2='y')
        self.assertEqual(senha.status_code, 400)
        self.assertIn('old_password', senha.json()['errors'])

    def test_nome_e_senha(self):
        nome = self.ajax(action='username', username='Ana_Nova').json()
        self.assertEqual(nome['account']['username'], 'ana_nova')
        senha = self.ajax(action='password', old_password=SENHA_TESTE, new_password1='outra-senha-boa-9',
                          new_password2='outra-senha-boa-9')
        self.assertEqual(senha.status_code, 200)
        self.assertEqual(senha.json()['message'], 'Senha trocada.')
        # A sessão continua válida depois de trocar a senha.
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_sem_javascript_continua_redirecionando(self):
        self.assertRedirects(self.client.post(self.url, {'action': 'photo', 'photo': imagem()}), self.url)
