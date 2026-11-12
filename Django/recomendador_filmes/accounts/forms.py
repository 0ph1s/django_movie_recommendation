from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import User, normalize_email


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
