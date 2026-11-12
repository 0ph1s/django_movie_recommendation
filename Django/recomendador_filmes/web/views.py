# web/views.py
import random
from collections import Counter
from itertools import chain, zip_longest

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from api.serializers import title_card
from api.views import insights_payload
from catalog.models import Genre, Title
from recommender import preferences
from recommender.config import get_config
from recommender.engine import EmptyCatalog

FEATURED_PER_KIND = 4

# Tela de primeira avaliação (/bem-vindo/): 24 títulos populares e variados.
WELCOME_TOTAL = 24
WELCOME_SHARE = {'movie': 12, 'series': 6, 'anime': 6}
WELCOME_POOL = 150           # entre os N mais populares de cada tipo
WELCOME_MAX_PER_GENRE = 3    # pelo gênero principal
WELCOME_MAX_PER_DECADE = 5
WELCOME_GOAL = 5


def _featured():
    """Os mais populares de cada tipo, intercalados (filme, série, anime, filme...)."""
    por_tipo = [
        list(Title.objects.for_listing().filter(kind=kind)[:FEATURED_PER_KIND])
        for kind in Title.Kind.values
    ]
    return [title_card(t) for t in chain.from_iterable(zip_longest(*por_tipo)) if t]


def home(request):
    contagem = dict(Title.objects.values_list('kind').annotate(n=Count('id')))
    return render(request, 'web/home.html', {
        'page': 'home',
        'counts': [
            {'kind': kind, 'label': label, 'total': contagem.get(kind, 0)}
            for kind, label in Title.Kind.choices
        ],
        'total_titles': sum(contagem.values()),
        'total_genres': Genre.objects.count(),
        'featured': _featured(),
        'weights': {bloco: round(peso * 100) for bloco, peso in get_config().block_weights.items()},
    })


@ensure_csrf_cookie
def playground(request):
    # Os controles já nascem com as preferências salvas (sem piscar nos valores padrão).
    prefs = preferences.payload(request)
    return render(request, 'web/playground.html', {
        'page': 'playground',
        'kinds': Title.Kind.choices,
        'total_titles': Title.objects.count(),
        'prefs': prefs['values'],
        'prefs_customized': prefs['customized'],
    })


@ensure_csrf_cookie
def profile(request):
    """Página de perfil: funciona para quem tem conta e para o perfil da sessão anônima."""
    try:
        dados = insights_payload(request)
    except EmptyCatalog:
        dados = None
    return render(request, 'web/perfil.html', {'page': 'profile', 'insights': dados})


def welcome_titles(rng=None):
    """Sorteio estratificado: proporção fixa por tipo, sem repetir demais gênero e década."""
    rng = rng or random.Random()
    escolhidos, generos, decadas = [], Counter(), Counter()
    por_tipo = {}
    for kind, quantos in WELCOME_SHARE.items():
        candidatos = list(Title.objects.for_listing().filter(kind=kind)[:WELCOME_POOL])
        rng.shuffle(candidatos)
        # Com capa primeiro: a tela é para reconhecer títulos de relance.
        candidatos.sort(key=lambda t: not t.poster_url)
        pegos = []
        for rodada in (True, False):  # 1ª passada respeita a variedade; a 2ª completa
            for titulo in candidatos:
                if len(pegos) >= quantos:
                    break
                if titulo in pegos:
                    continue
                genero = next(iter(titulo.genres.all()), None)
                decada = titulo.year // 10 if titulo.year else None
                if rodada and (generos[genero] >= WELCOME_MAX_PER_GENRE or decadas[decada] >= WELCOME_MAX_PER_DECADE):
                    continue
                pegos.append(titulo)
                generos[genero] += 1
                decadas[decada] += 1
        por_tipo[kind] = pegos
    # Intercala os tipos na proporção 2:1:1 (filme, filme, série, anime...).
    filmes, series, animes = (iter(por_tipo.get(k, [])) for k in ('movie', 'series', 'anime'))
    for grupo in zip_longest(filmes, filmes, series, animes):
        escolhidos.extend(t for t in grupo if t)
    return escolhidos[:WELCOME_TOTAL]


@login_required
@ensure_csrf_cookie
def welcome(request):
    """Primeira avaliação de quem criou a conta sem histórico na sessão."""
    return render(request, 'web/bem_vindo.html', {
        'page': 'welcome',
        'titles': [title_card(t) for t in welcome_titles()],
        'goal': WELCOME_GOAL,
    })


def page_not_found(request, exception):
    """404 do site (handler404). A API continua respondendo em JSON."""
    if request.path.startswith('/api/'):
        return JsonResponse({'error': 'Recurso não encontrado.'}, status=404)
    return render(request, '404.html', {'page': 'not-found'}, status=404)
