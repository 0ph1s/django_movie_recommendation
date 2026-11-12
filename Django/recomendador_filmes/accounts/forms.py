from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError

from .models import User, normalize_email, username_validator


class SignupForm(forms.Form):
    """Cadastro em dois campos. O username é gerado e pode ser trocado depois."""

    email = forms.EmailField(
        label='E-mail', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True, 'class': 'field-input'}),
    )
    password = forms.CharField(
        label='Senha', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'class': 'field-input'}),
        help_text='Pelo menos 8 caracteres, sem ser só números nem uma senha comum.',
    )

    def clean_email(self):
        email = normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email=email).exists():
            raise ValidationError('Já existe uma conta com este e-mail. Entre com ela.')
        return email

    def clean(self):
        dados = super().clean()
        senha = dados.get('password')
        if senha:
            try:
                password_validation.validate_password(senha, User(email=dados.get('email', '')))
            except ValidationError as erro:
                self.add_error('password', erro)
        return dados

    def save(self):
        return User.objects.create_user(self.cleaned_data['email'], self.cleaned_data['password'])


class LoginForm(AuthenticationForm):
    """Login por e-mail. O campo continua se chamando `username` (padrão do Django e do axes)."""

    username = forms.EmailField(
        label='E-mail', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True, 'class': 'field-input'}),
    )
    password = forms.CharField(
        label='Senha', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'class': 'field-input'}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'E-mail ou senha incorretos.',
        'inactive': 'Esta conta está desativada.',
    }

    def clean_username(self):
        return normalize_email(self.cleaned_data['username'])


# Nomes que viram rotas ou confundem na futura página pública (/u/<username>/).
RESERVED_USERNAMES = {
    'admin', 'api', 'angulo', 'perfil', 'configuracoes', 'playground', 'entrar', 'sair',
    'criar_conta', 'bem_vindo', 'root', 'suporte', 'staff', 'sistema',
}


class UsernameForm(forms.Form):
    """Troca do nome público. Aceita maiúsculas e as converte."""

    username = forms.CharField(
        label='Nome público', max_length=30,
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'class': 'field-input', 'spellcheck': 'false'}),
        help_text='De 3 a 30 caracteres: letras sem acento, números e “_”.',
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_username(self):
        nome = self.cleaned_data['username'].strip().lower()
        username_validator(nome)
        if nome in RESERVED_USERNAMES:
            raise ValidationError('Este nome é reservado. Escolha outro.')
        if User.objects.exclude(pk=self.user.pk).filter(username=nome).exists():
            raise ValidationError('Este nome já está em uso.')
        return nome

    def save(self):
        self.user.username = self.cleaned_data['username']
        self.user.save(update_fields=['username'])
        return self.user


class SettingsPasswordForm(PasswordChangeForm):
    """Troca de senha com a senha atual, nos campos do site."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rotulos = {'old_password': 'Senha atual', 'new_password1': 'Nova senha', 'new_password2': 'Repita a nova senha'}
        for nome, campo in self.fields.items():
            campo.label = rotulos[nome]
            campo.widget.attrs['class'] = 'field-input'
            campo.widget.attrs.pop('autofocus', None)
        self.fields['new_password1'].help_text = 'Pelo menos 8 caracteres, sem ser só números nem uma senha comum.'


class DeleteAccountForm(forms.Form):
    """Excluir a conta pede a senha: é irreversível."""

    password = forms.CharField(
        label='Sua senha', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'class': 'field-input'}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        senha = self.cleaned_data['password']
        if not self.user.check_password(senha):
            raise ValidationError('Senha incorreta.')
        return senha
