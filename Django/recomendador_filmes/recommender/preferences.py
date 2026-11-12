"""
Preferências do filtro híbrido (α, nota × popularidade, corte de obscuridade, diversidade e
tipos recomendados).

Só o que a pessoa altera é guardado: na sessão, para o anônimo, ou em `UserPreferences`,
para quem tem conta. O valor efetivo é sempre `padrões de config.py + alterações`.
"""
from catalog.models import Title

from .config import get_config
from .models import UserPreferences

SESSION_KEY = 'preferences'
KINDS = tuple(Title.Kind.values)

# Faixas dos controles do playground (as mesmas dos <input type="range">).
RANGES = {
    'alpha': (0.0, 1.0),
    'rating_weight': (0.0, 1.0),
    'obscurity': (0.0, 0.9),
    'diversity': (0.0, 0.8),
}


def defaults():
    config = get_config()
    return {
        'alpha': config.alpha,
        'rating_weight': config.rating_weight,
        'obscurity': config.obscurity,
        'diversity': config.diversity,
        'kinds': [],  # vazio = todos os tipos
    }


def clean(dados):
    """Valida um dicionário parcial vindo do cliente. Chaves desconhecidas são ignoradas.

    Levanta ValueError com uma mensagem legível se algum valor for inválido.
    """
    if not isinstance(dados, dict):
        raise ValueError('Envie um objeto JSON com as preferências.')
    limpos = {}
    for nome, (minimo, maximo) in RANGES.items():
        if nome not in dados:
            continue
        try:
            valor = float(dados[nome])
        except (TypeError, ValueError):
            raise ValueError(f'“{nome}” precisa ser um número.') from None
        limpos[nome] = round(min(max(valor, minimo), maximo), 4)
    if 'kinds' in dados:
        tipos = dados['kinds']
        if isinstance(tipos, str):
            tipos = [t for t in tipos.split(',') if t]
        if not isinstance(tipos, list):
            raise ValueError('“kinds” precisa ser uma lista de tipos.')
        tipos = [t for t in KINDS if t in tipos]
        # Todos marcados (ou nenhum) é o mesmo que o padrão.
        limpos['kinds'] = [] if len(tipos) in (0, len(KINDS)) else tipos
    return limpos


def _diff(valores):
    """Só o que difere do padrão."""
    padrao = defaults()
    return {k: v for k, v in valores.items() if k in padrao and v != padrao[k]}


def overrides(request):
    """O que a pessoa alterou (dicionário parcial)."""
    if request.user.is_authenticated:
        valores = UserPreferences.objects.filter(user=request.user).values_list('values', flat=True).first()
        return dict(valores or {})
    return dict(request.session.get(SESSION_KEY, {}))


def effective(request):
    """Valores efetivos, já com os padrões."""
    return {**defaults(), **overrides(request)}


def payload(request):
    alteradas = overrides(request)
    return {'values': {**defaults(), **alteradas}, 'defaults': defaults(), 'customized': bool(alteradas)}


def save(request, dados):
    """Mescla `dados` (já limpos) às alterações atuais e grava."""
    alteradas = _diff({**overrides(request), **dados})
    _store(request, alteradas)


def reset(request):
    _store(request, {})


def _store(request, alteradas):
    if request.user.is_authenticated:
        UserPreferences.objects.update_or_create(user=request.user, defaults={'values': alteradas})
    elif alteradas:
        request.session[SESSION_KEY] = alteradas
    else:
        request.session.pop(SESSION_KEY, None)


def adopt(user, da_sessao, conta_nova):
    """Ao entrar: decide entre as preferências da sessão anônima e as da conta.

    Conta nova herda as da sessão. Conta existente mantém as suas, salvas de propósito; só
    herda as da sessão se nunca tiver alterado nada.
    """
    if not da_sessao:
        return
    registro, _ = UserPreferences.objects.get_or_create(user=user)
    if conta_nova or not registro.values:
        registro.values = _diff(da_sessao)
        registro.save(update_fields=['values', 'updated_at'])
