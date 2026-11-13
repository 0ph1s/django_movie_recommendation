import secrets

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

USERNAME_PREFIX = 'cinefilo'
DEFAULT_PHOTO = 'img/perfil-padrao.webp'

username_validator = RegexValidator(
    r'^[a-z0-9_]{3,30}$',
    'Use de 3 a 30 caracteres: letras minúsculas sem acento, números e “_”.',
)


def normalize_email(email):
    """E-mail inteiro em minúsculas: Fulano@Exemplo.com e fulano@exemplo.com são a mesma conta."""
    return (email or '').strip().lower()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def generate_username(self):
        """Username público provisório (ex.: cinefilo_4821), editável depois em Configurações."""
        for digitos in (4, 4, 4, 5, 6, 8):
            candidato = f'{USERNAME_PREFIX}_{secrets.randbelow(9 * 10 ** (digitos - 1)) + 10 ** (digitos - 1)}'
            if not self.filter(username=candidato).exists():
                return candidato
        return f'{USERNAME_PREFIX}_{secrets.token_hex(6)}'

    def get_by_natural_key(self, email):
        return self.get(email=normalize_email(email))

    def _create_user(self, email, password, **extra):
        email = normalize_email(email)
        if not email:
            raise ValueError('O e-mail é obrigatório.')
        extra.setdefault('username', self.generate_username())
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        if not extra['is_staff'] or not extra['is_superuser']:
            raise ValueError('Um superusuário precisa de is_staff e is_superuser.')
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Conta do Ângulo: entra pelo e-mail; o username é o nome público (fase social)."""

    email = models.EmailField('e-mail', unique=True)
    username = models.CharField(
        'username', max_length=30, unique=True, validators=[username_validator],
        help_text='Nome público. Letras minúsculas sem acento, números e “_”.',
    )
    is_active = models.BooleanField('ativo', default=True)
    is_staff = models.BooleanField('acesso ao admin', default=False)
    date_joined = models.DateTimeField('criado em', default=timezone.now)
    # Versão da foto de perfil (0 = foto padrão). Fica no usuário para o cabeçalho montar a URL
    # sem consultar a tabela das fotos, que guarda os bytes.
    # db_default: o código anterior (sem este campo) continua criando contas enquanto o deploy troca.
    photo_version = models.PositiveIntegerField('versão da foto', default=0, db_default=0, editable=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'usuário'
        ordering = ['-date_joined']

    def __str__(self):
        return self.username

    def clean(self):
        super().clean()
        self.email = normalize_email(self.email)

    @property
    def photo_url(self):
        """Foto escolhida (URL versionada, para o cache) ou a foto padrão do Ângulo."""
        if self.photo_version:
            return f"{reverse('accounts:photo')}?v={self.photo_version}"
        return static(DEFAULT_PHOTO)

    @property
    def owner(self):
        """Dono do histórico de gosto (ver recommender.models.owner_key)."""
        return f'u:{self.pk}'


class ProfilePhoto(models.Model):
    """Foto de perfil enviada pelo usuário, já recortada e reprocessada (ver accounts/photos.py).

    Os bytes ficam no banco: no Vercel não há disco persistente, e a imagem final é pequena
    (WebP 384 × 384, dezenas de KB).
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name='photo')
    image = models.BinaryField('imagem (WebP)')
    updated_at = models.DateTimeField('atualizada em', auto_now=True)

    class Meta:
        verbose_name = 'foto de perfil'
        verbose_name_plural = 'fotos de perfil'

    def __str__(self):
        return f'Foto de {self.user}'
