import json

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from recommender import preferences
from recommender.models import merge_history

from .data import delete_user_data, export_user_data
from .forms import DeleteAccountForm, LoginForm, SettingsPasswordForm, SignupForm, UsernameForm

MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def _next_url(request):
    """Destino depois de entrar: o `next` pedido, se for deste site; senão o playground."""
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return destino
    return reverse('web:playground')


def _enter(request, user, conta_nova):
    """Autentica e traz o que a sessão anônima juntou: histórico e preferências.

    O login troca a chave da sessão (proteção contra fixação de sessão), então o dono
    anônimo `s:<chave>` precisa ser lido antes.
    """
    chave = request.session.session_key
    prefs_da_sessao = preferences.overrides(request)

    login(request, user, backend=getattr(user, 'backend', MODEL_BACKEND))

    somados = merge_history(f's:{chave}', user.owner) if chave else 0
    preferences.adopt(user, prefs_da_sessao, conta_nova=conta_nova)
    request.session.pop(preferences.SESSION_KEY, None)
    if somados:
        messages.success(
            request,
            f'{somados} títulos da sessão foram somados ao seu perfil.' if somados > 1
            else '1 título da sessão foi somado ao seu perfil.',
        )
    return somados


def _auth_page(request, template, form):
    return render(request, template, {'page': 'auth', 'form': form, 'next': _next_url(request)})


@sensitive_post_parameters('password')
@csrf_protect
@never_cache
def signup(request):
    if request.user.is_authenticated:
        return redirect(_next_url(request))
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        somados = _enter(request, user, conta_nova=True)
        messages.success(request, f'Conta criada. Seu nome público é {user.username}; dá para trocar depois.')
        # Quem chega sem histórico faz a primeira avaliação; quem trouxe a sessão já vê o perfil.
        return redirect('web:profile' if somados else 'web:welcome')
    return _auth_page(request, 'accounts/criar_conta.html', form)


@sensitive_post_parameters('password')
@csrf_protect
@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_next_url(request))
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        _enter(request, form.get_user(), conta_nova=False)
        return redirect(_next_url(request))
    return _auth_page(request, 'accounts/entrar.html', form)


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, 'Você saiu da conta. Este navegador começa um perfil novo.')
    return redirect('web:home')


# ---------------------------------------------------------------- configurações e LGPD

@login_required
@sensitive_post_parameters('old_password', 'new_password1', 'new_password2', 'password')
@csrf_protect
@never_cache
def settings_view(request):
    """Nome público, senha, exportação dos dados e exclusão da conta numa página só.

    Cada formulário envia um `action` próprio; só ele é validado, os outros voltam vazios.
    """
    acao = request.POST.get('action') if request.method == 'POST' else None
    dados = lambda nome: request.POST if acao == nome else None  # noqa: E731
    form_nome = UsernameForm(request.user, dados('username'), initial={'username': request.user.username})
    form_senha = SettingsPasswordForm(request.user, dados('password'))
    form_excluir = DeleteAccountForm(request.user, dados('delete'))

    if acao == 'username' and form_nome.is_valid():
        user = form_nome.save()
        messages.success(request, f'Pronto. Seu nome público agora é {user.username}.')
        return redirect('accounts:settings')
    if acao == 'password' and form_senha.is_valid():
        user = form_senha.save()
        update_session_auth_hash(request, user)  # continua logado nesta sessão
        messages.success(request, 'Senha trocada.')
        return redirect('accounts:settings')
    if acao == 'delete' and form_excluir.is_valid():
        delete_user_data(request.user)
        logout(request)
        messages.info(request, 'Conta excluída. Todo o seu histórico de gosto foi apagado.')
        return redirect('web:home')

    return render(request, 'accounts/configuracoes.html', {
        'page': 'settings',
        'form_username': form_nome,
        'form_password': form_senha,
        'form_delete': form_excluir,
        'open_section': acao,
    }, status=400 if acao else 200)


@login_required
@require_GET
@never_cache
def export_view(request):
    """Download em JSON com tudo o que o Ângulo guarda sobre a conta."""
    corpo = json.dumps(export_user_data(request.user), ensure_ascii=False, indent=2)
    resposta = HttpResponse(corpo, content_type='application/json; charset=utf-8')
    nome = f'angulo-{request.user.username}-{timezone.localdate():%Y-%m-%d}.json'
    resposta['Content-Disposition'] = f'attachment; filename="{nome}"'
    return resposta
