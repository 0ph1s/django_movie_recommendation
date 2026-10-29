# api/views.py
"""
API JSON do catálogo e do recomendador.

Views de função enxutas, sem DRF: são poucos endpoints, todos de leitura do índice em
memória ou escrita de uma única tabela (Interaction), e o formato de resposta é
controlado em api/serializers.py.
"""
import difflib
import json
import time
from functools import wraps

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from catalog.models import Genre, Title
from recommender.engine import (
    EmptyCatalog,
    HybridParams,
    describe_profile,
    get_index,
    recommend_for_profile,
    similar_to,
    similarity_matrix,
)
from recommender.models import Interaction, owner_key
from recommender.profile import Signal

from . import serializers

MAX_PAGE = 60
MAX_MATRIX = 24


def _erro(mensagem, status=400):
    return JsonResponse({'error': mensagem}, status=status)


def catalog_required(view):
    """Converte um catálogo vazio em 503 com a instrução de como popular o banco."""
    @wraps(view)
    def envolvida(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except EmptyCatalog as erro:
            return _erro(str(erro), status=503)
    return envolvida


def _float(request, nome):
    try:
        return float(request.GET[nome])
    except (KeyError, ValueError):
        return None


def _int(request, nome, padrao, minimo=0, maximo=None):
    try:
        valor = int(request.GET.get(nome, padrao))
    except ValueError:
        valor = padrao
    valor = max(valor, minimo)
    return min(valor, maximo) if maximo is not None else valor


def _kinds(request):
    return tuple(k for k in request.GET.get('kinds', '').split(',') if k)


def _hybrid_params(request):
    return HybridParams.from_config(
        k=_int(request, 'k', 12, minimo=1, maximo=50),
        alpha=_float(request, 'alpha'),
        rating_weight=_float(request, 'rating_weight'),
        obscurity=_float(request, 'obscurity'),
        diversity=_float(request, 'diversity'),
        kinds=_kinds(request),
    )


def _with_titles(recomendacoes):
    titulos = Title.objects.for_listing().in_bulk([r.title_id for r in recomendacoes])
    return [serializers.recommendation(r, titulos[r.title_id]) for r in recomendacoes if r.title_id in titulos]


def _params_payload(params):
    return {
        'k': params.k, 'alpha': params.alpha, 'rating_weight': params.rating_weight,
        'obscurity': params.obscurity, 'diversity': params.diversity, 'kinds': list(params.kinds),
    }


# ---------------------------------------------------------------- catálogo

@require_GET
def catalog(request):
    """Lista/busca títulos. Filtros: q, kinds=movie,anime, genre=<slug>, limit, offset."""
    limite = _int(request, 'limit', 24, minimo=1, maximo=MAX_PAGE)
    deslocamento = _int(request, 'offset', 0)
    termo = request.GET.get('q', '').strip()

    titulos = Title.objects.all()
    if _kinds(request):
        titulos = titulos.filter(kind__in=_kinds(request))
    if request.GET.get('genre'):
        titulos = titulos.filter(genres__slug=request.GET['genre'])

    encontrados = titulos.search(termo)
    aproximado = False
    if termo and len(termo) >= 3 and not encontrados.exists():
        # Tolerância a erros de digitação: compara com todos os títulos do filtro atual.
        nomes = {nome.lower(): pk for nome, pk in titulos.values_list('title', 'pk')}
        parecidos = difflib.get_close_matches(termo.lower(), nomes.keys(), n=limite, cutoff=0.55)
        encontrados = titulos.filter(pk__in=[nomes[n] for n in parecidos])
        aproximado = True

    total = encontrados.count()
    pagina = encontrados.for_listing()[deslocamento:deslocamento + limite]
    return JsonResponse({
        'count': total,
        'approximate': aproximado,
        'results': [serializers.title_card(t) for t in pagina],
    })


@require_GET
def genres(request):
    return JsonResponse({'results': list(Genre.objects.values('name', 'slug'))})


@require_GET
def title_detail(request, pk):
    titulo = get_object_or_404(Title.objects.for_listing(), pk=pk)
    return JsonResponse(serializers.title_detail(titulo))


@require_GET
@catalog_required
def similar(request, pk):
    titulo = get_object_or_404(Title.objects.for_listing(), pk=pk)
    params = _hybrid_params(request)
    inicio = time.perf_counter()
    resultados = similar_to(get_index(), titulo.pk, params)
    return JsonResponse({
        'source': serializers.title_card(titulo),
        'params': _params_payload(params),
        'elapsed_ms': round((time.perf_counter() - inicio) * 1000, 1),
        'results': _with_titles(resultados),
    })


@require_GET
@catalog_required
def matrix(request):
    """Bloco da matriz de similaridade do cosseno: ?ids=1,2,3 (até 24 títulos)."""
    try:
        ids = [int(i) for i in request.GET.get('ids', '').split(',') if i][:MAX_MATRIX]
    except ValueError:
        return _erro('Use ids=1,2,3 com números inteiros.')
    ordem, valores = similarity_matrix(get_index(), ids)
    titulos = Title.objects.in_bulk(ordem)
    return JsonResponse({
        'titles': [{'id': i, 'title': titulos[i].title, 'kind': titulos[i].kind} for i in ordem],
        'matrix': [[round(float(v), 4) for v in linha] for linha in valores],
    })


# ---------------------------------------------------------------- perfil

def _history(request):
    return list(
        Interaction.objects.filter(owner=owner_key(request))
        .select_related('title').prefetch_related('title__genres')
    )


def _profile_payload(request, historico=None):
    historico = _history(request) if historico is None else historico
    return {'history': [serializers.interaction(i) for i in historico]}


@require_http_methods(['GET', 'DELETE'])
def profile(request):
    if request.method == 'DELETE':
        Interaction.objects.filter(owner=owner_key(request)).delete()
    return JsonResponse(_profile_payload(request))


@require_http_methods(['POST'])
def add_interaction(request):
    """Corpo JSON: {"title_id": 123, "signal": 1 | -1}. Reavaliar move o título para o fim."""
    try:
        dados = json.loads(request.body or b'{}')
        title_id = int(dados['title_id'])
        sinal = int(dados.get('signal', Interaction.Signal.LIKE))
    except (ValueError, KeyError, TypeError):
        return _erro('Envie {"title_id": <id>, "signal": 1 ou -1}.')
    if sinal not in Interaction.Signal.values:
        return _erro('O sinal deve ser 1 (curti) ou -1 (não curti).')

    titulo = get_object_or_404(Title, pk=title_id)
    with transaction.atomic():
        Interaction.objects.update_or_create(
            owner=owner_key(request), title=titulo, defaults={'signal': sinal},
        )
    return JsonResponse(_profile_payload(request), status=201)


@require_http_methods(['DELETE'])
def remove_interaction(request, title_id):
    Interaction.objects.filter(owner=owner_key(request), title_id=title_id).delete()
    return JsonResponse(_profile_payload(request))


@require_GET
@catalog_required
def recommendations(request):
    """Recomendações para o histórico da sessão, com o resumo do perfil calculado."""
    params = _hybrid_params(request)
    historico = _history(request)
    sinais = [Signal(i.title_id, i.signal) for i in historico]

    inicio = time.perf_counter()
    indice = get_index()
    resultados, perfil = recommend_for_profile(indice, sinais, params)
    decorrido = (time.perf_counter() - inicio) * 1000

    return JsonResponse({
        'mode': 'profile' if perfil is not None else 'cold_start',
        'params': _params_payload(params),
        'elapsed_ms': round(decorrido, 1),
        'catalog_size': indice.size,
        'dimensions': indice.dimensions,
        'profile': describe_profile(indice, perfil) if perfil is not None else None,
        'results': _with_titles(resultados),
        **_profile_payload(request, historico),
    })
