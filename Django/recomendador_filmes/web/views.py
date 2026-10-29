# web/views.py
from itertools import chain, zip_longest

from django.db.models import Count
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from api.serializers import title_card
from catalog.models import Genre, Title
from recommender.config import get_config

FEATURED_PER_KIND = 4


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
    return render(request, 'web/playground.html', {
        'page': 'playground',
        'kinds': Title.Kind.choices,
        'total_titles': Title.objects.count(),
    })
