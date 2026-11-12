# api/views.py
"""
API JSON do catálogo e do recomendador.

Views de função enxutas, sem DRF: são poucos endpoints, todos de leitura do índice em
memória ou escrita de uma única tabela (Interaction), e o formato de resposta é
controlado em api/serializers.py.
"""
import difflib
import hashlib
import hmac
import json
import time
from functools import wraps

from django.conf import settings
from django.http import HttpResponse, JsonResponse
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
from recommender import preferences
from recommender.avatar import avatar_etag, avatar_grid, avatar_svg
from recommender.insights import build_insights, profile_summary
from recommender.maintenance import purge_anonymous
from recommender.models import STATE_OF_LEGACY_SIGNAL, Interaction, clear_states, owner_key, set_state
from recommender.profile import Signal

from . import serializers

MAX_PAGE = 60
MAX_MATRIX = 24
MAX_EXCLUDE = 50

# Cartão "Guardar meu perfil" no playground: aparece com 5 títulos marcados e, se dispensado
# antes de 15, volta uma única vez ao chegar a 15.
OFFER_FIRST = 5
OFFER_AGAIN = 15
OFFER_SESSION_KEY = 'account_offer_dismissed_at'


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
    dono = owner_key(request)
    if dono is None:
        return []
    return list(
        Interaction.objects.filter(owner=dono)
        .select_related('title').prefetch_related('title__genres')
    )


def _account_offer(request, total):
    """Se o playground deve oferecer a criação de conta a este anônimo."""
    if request.user.is_authenticated or total < OFFER_FIRST:
        return False
    dispensado_em = request.session.get(OFFER_SESSION_KEY)
    return dispensado_em is None or (dispensado_em < OFFER_AGAIN <= total)


def _profile_payload(request, historico=None):
    historico = _history(request) if historico is None else historico
    return {
        'history': [serializers.interaction(i) for i in historico],
        'account_offer': _account_offer(request, len(historico)),
    }


@require_http_methods(['GET', 'DELETE'])
def profile(request):
    if request.method == 'DELETE' and owner_key(request):
        clear_states(owner_key(request))
    return JsonResponse(_profile_payload(request))


ESTADOS = ', '.join(Interaction.State.values)


def _state_from(dados):
    """Estado pedido: {"state": "..."} ou, no formato antigo, {"signal": 1 | -1}. Padrão: curti."""
    if 'state' in dados:
        if dados['state'] not in Interaction.State.values:
            raise ValueError(f'O estado deve ser um destes: {ESTADOS}.')
        return dados['state']
    if 'signal' in dados:
        try:
            return STATE_OF_LEGACY_SIGNAL[int(dados['signal'])]
        except (KeyError, TypeError, ValueError):
            raise ValueError('O sinal deve ser 1 (curti) ou -1 (não curti).') from None
    return Interaction.State.LIKE


@require_http_methods(['POST'])
def add_interaction(request):
    """Corpo JSON: {"title_id": 123, "state": "favorite" | "like" | "dislike" | "seen" | "watchlist"}.

    O formato antigo {"title_id": 123, "signal": 1 | -1} continua aceito. Reavaliar move o
    título para o fim (mais recente) e só gera evento se o estado mudar.
    """
    try:
        dados = json.loads(request.body or b'{}')
        title_id = int(dados['title_id'])
    except (KeyError, TypeError, ValueError):  # ValueError cobre o JSON inválido
        return _erro(f'Envie {{"title_id": <id>, "state": um destes: {ESTADOS}}}.')
    try:
        estado = _state_from(dados)
    except ValueError as erro:
        return _erro(str(erro))

    titulo = get_object_or_404(Title, pk=title_id)
    set_state(owner_key(request, create=True), titulo, estado)
    return JsonResponse(_profile_payload(request), status=201)


@require_http_methods(['DELETE'])
def remove_interaction(request, title_id):
    if owner_key(request):
        clear_states(owner_key(request), [title_id])
    return JsonResponse(_profile_payload(request))


@require_http_methods(['POST'])
def dismiss_account_offer(request):
    """“Agora não” no cartão de oferta de conta: guarda quantos títulos havia ao dispensar."""
    request.session[OFFER_SESSION_KEY] = len(_history(request))
    return JsonResponse({'account_offer': False})


# ---------------------------------------------------------------- página de perfil

def insights_payload(request, exclude=()):
    """Insights do perfil com os títulos já serializados (usado pela API e pela página /perfil/)."""
    historico = _history(request)
    dados = build_insights(get_index(), historico, exclude)

    titulos = {i.title_id: i.title for i in historico}
    pontos_cegos = (dados['comfort'] or {}).get('blind_spots', [])
    vizinhos = (dados['map'] or {}).get('neighbor_ids', [])
    faltam = ({b['suggestion_id'] for b in pontos_cegos} | set(vizinhos)) - set(titulos)
    titulos.update(Title.objects.for_listing().in_bulk(faltam))
    if dados['map']:
        dados['map']['neighbors'] = [serializers.title_card(titulos[t]) for t in vizinhos]

    for item in [*(dados['defining'] or []), *dados['watchlist']]:
        item['title'] = serializers.title_card(titulos[item['title_id']])
    for ponto in pontos_cegos:
        ponto['suggestion'] = serializers.title_card(titulos[ponto['suggestion_id']])
    if dados['whatif']:
        dados['whatif']['titles'] = [titulos[t].title for t in dados['whatif']['title_ids']]
    return dados


@require_GET
@catalog_required
def profile_insights(request):
    """Tudo o que a página de perfil mostra. ?exclude=1,2 recalcula sem esses títulos (modo "e se")."""
    try:
        excluir = [int(i) for i in request.GET.get('exclude', '').split(',') if i][:MAX_EXCLUDE]
    except ValueError:
        return _erro('Use exclude=1,2,3 com números inteiros.')
    return JsonResponse(insights_payload(request, excluir))


@require_GET
def map_points(request):
    """Todos os títulos com posição no mapa do gosto, em colunas compactas e iguais para todos.

    x e y vêm multiplicados por 1000 (inteiros de -1000 a 1000); `kinds` é uma letra por
    título (m = filme, s = série, a = anime). O título e a capa vêm sob demanda (/api/titles/<id>/).
    """
    linhas = Title.objects.filter(map_x__isnull=False, map_y__isnull=False).order_by('id').values_list(
        'id', 'map_x', 'map_y', 'kind',
    )
    letra = {'movie': 'm', 'series': 's', 'anime': 'a'}
    colunas = {'ids': [], 'x': [], 'y': [], 'kinds': []}
    for pk, x, y, kind in linhas:
        colunas['ids'].append(pk)
        colunas['x'].append(round(x * 1000))
        colunas['y'].append(round(y * 1000))
        colunas['kinds'].append(letra[kind])
    colunas['kinds'] = ''.join(colunas['kinds'])
    corpo = json.dumps(colunas, separators=(',', ':')).encode()
    etag = f'"{hashlib.sha1(corpo).hexdigest()[:16]}"'
    if request.headers.get('If-None-Match') == etag:
        resposta = HttpResponse(status=304)
    else:
        resposta = HttpResponse(corpo, content_type='application/json')
    resposta['ETag'] = etag
    resposta['Cache-Control'] = 'public, max-age=3600'
    return resposta


@require_GET
def profile_avatar(request):
    """Avatar ASCII em SVG, gerado do DNA do perfil. Com ETag: muda quando o gosto muda."""
    historico = _history(request)
    resumo = None
    if any(i.weight > 0 for i in historico):
        try:
            resumo = profile_summary(get_index(), historico)
        except EmptyCatalog:
            resumo = None
    grade = avatar_grid(resumo)
    etag = f'"{avatar_etag(grade)}"'
    if request.headers.get('If-None-Match') == etag:
        resposta = HttpResponse(status=304)
    else:
        resposta = HttpResponse(avatar_svg(grade), content_type='image/svg+xml; charset=utf-8')
    resposta['ETag'] = etag
    resposta['Cache-Control'] = 'private, no-cache'
    return resposta


# ---------------------------------------------------------------- preferências

@require_http_methods(['GET', 'PUT', 'DELETE'])
def user_preferences(request):
    """Ajustes do filtro híbrido. PUT com um objeto parcial; DELETE restaura os padrões."""
    if request.method == 'PUT':
        try:
            preferences.save(request, preferences.clean(json.loads(request.body or b'{}')))
        except json.JSONDecodeError:
            return _erro('Envie um objeto JSON com as preferências.')
        except ValueError as erro:
            return _erro(str(erro))
    elif request.method == 'DELETE':
        preferences.reset(request)
    return JsonResponse(preferences.payload(request))


# ---------------------------------------------------------------- recomendações

@require_GET
@catalog_required
def recommendations(request):
    """Recomendações para o histórico da sessão, com o resumo do perfil calculado."""
    params = _hybrid_params(request)
    historico = _history(request)
    sinais = [Signal(i.title_id, i.weight) for i in historico]

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


# ---------------------------------------------------------------- manutenção (Vercel Cron)

@require_GET
def cron_purge_anonymous(request):
    """Limpeza diária dos dados anônimos, chamada pelo Vercel Cron (ver vercel.json).

    O Vercel manda `Authorization: Bearer $CRON_SECRET`. Sem o segredo configurado no
    servidor, a rota recusa qualquer chamada.
    """
    segredo = settings.CRON_SECRET
    enviado = request.headers.get('Authorization', '')
    if not segredo or not hmac.compare_digest(enviado.encode(), f'Bearer {segredo}'.encode()):
        return _erro('Não autorizado.', status=401)
    return JsonResponse(purge_anonymous())
