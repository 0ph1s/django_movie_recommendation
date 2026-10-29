# recommender/engine.py
"""
Motor de recomendação: índice de features, filtro híbrido e perfil dinâmico.

Fluxo de uma recomendação
  1. Vetor de consulta: a linha de um título (modo "parecidos com") ou o perfil do usuário.
  2. Similaridade do cosseno contra o catálogo inteiro: um produto matriz-vetor esparso,
     já que todas as linhas têm norma 1 (X · q = cos).
  3. Filtros: tipo, itens já vistos e corte de obscuridade (percentil de votos no tipo).
  4. Os `candidate_pool` mais similares são re-ranqueados pelo score híbrido
         score = α · sim_relativa + (1 − α) · qualidade
         qualidade = w · percentil(nota bayesiana) + (1 − w) · percentil(popularidade)
     O pool vem antes da mistura para que um título ótimo mas sem relação nenhuma
     com a consulta nunca entre só pela nota.
  5. MMR opcional para diversificar o resultado.

A matriz N x N completa nunca é materializada (com 5 mil títulos seriam 100 MB em
float32): cada consulta calcula só a linha de que precisa, em poucos milissegundos.
`similarity_matrix(ids)` gera o bloco N x N para um subconjunto, quando necessário.
"""
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace

import joblib
import numpy as np
import pandas as pd
from django.db.models import Count, Max

from catalog.models import Title

from .config import get_config
from .features import KINDS, RATING_CENTERS, TAG_PREFIXES, YEAR_CENTERS, build_features, slug_token
from .profile import build_profile
from .quality import quality_signals

logger = logging.getLogger(__name__)
INDEX_FORMAT = 2


class EmptyCatalog(Exception):
    """Não há títulos no banco: é preciso rodar `manage.py import_dataset`."""


@dataclass
class RecommenderIndex:
    ids: np.ndarray
    kinds: np.ndarray
    work_keys: np.ndarray      # título normalizado + ano: identifica a mesma obra em fontes diferentes
    matrix: object             # scipy.sparse.csr_matrix (N x d), linhas com norma 1
    blocks: dict
    tag_tokens: np.ndarray
    tag_labels: dict
    q_rating: np.ndarray
    q_popularity: np.ndarray
    q_votes: np.ndarray
    fingerprint: tuple
    feature_hash: str
    format: int = INDEX_FORMAT
    row_of: dict = field(init=False, repr=False)

    def __post_init__(self):
        self.row_of = {int(i): linha for linha, i in enumerate(self.ids)}

    def __setstate__(self, estado):
        self.__dict__.update(estado)
        self.row_of = {int(i): linha for linha, i in enumerate(self.ids)}

    def __getstate__(self):
        estado = self.__dict__.copy()
        estado.pop('row_of', None)
        return estado

    @property
    def size(self):
        return self.matrix.shape[0]

    @property
    def dimensions(self):
        return self.matrix.shape[1]

    def vector(self, title_id):
        return self.matrix[self.row_of[title_id]].toarray().ravel()


@dataclass(frozen=True)
class HybridParams:
    """Parâmetros de uma consulta. Valores fora da faixa são ajustados em `clamped()`."""

    k: int = 12
    alpha: float = 0.75
    rating_weight: float = 0.65
    obscurity: float = 0.25
    diversity: float = 0.15
    kinds: tuple = ()  # vazio = todos os tipos

    @classmethod
    def from_config(cls, **sobrescritas):
        config = get_config()
        base = cls(
            alpha=config.alpha,
            rating_weight=config.rating_weight,
            obscurity=config.obscurity,
            diversity=config.diversity,
        )
        return replace(base, **{k: v for k, v in sobrescritas.items() if v is not None}).clamped()

    def clamped(self):
        def faixa(valor):
            return float(min(max(valor, 0.0), 1.0))

        return replace(
            self,
            k=int(min(max(self.k, 1), 50)),
            alpha=faixa(self.alpha),
            rating_weight=faixa(self.rating_weight),
            # Acima de 0,95 quase nada sobra; o limite evita um resultado sempre vazio.
            obscurity=min(faixa(self.obscurity), 0.95),
            diversity=min(faixa(self.diversity), 0.9),
            kinds=tuple(k for k in self.kinds if k in KINDS),
        )


@dataclass
class Recommendation:
    title_id: int
    score: float
    similarity: float     # cosseno bruto com a consulta
    relevance: float      # cosseno / maior cosseno do pool: o termo que entra na mistura
    quality: float        # 0–1, mistura de nota bayesiana e popularidade
    contributions: dict   # bloco -> parcela do cosseno (somam `similarity`)
    reasons: list         # tokens em comum com mais peso, já legíveis


# ---------------------------------------------------------------- índice e cache

_lock = threading.Lock()
_cached = None
_checked_at = 0.0  # time.monotonic() da última vez que o fingerprint confirmou _cached


def _fingerprint():
    agregado = Title.objects.aggregate(total=Count('id'), ultimo=Max('updated_at'))
    ultimo = agregado['ultimo'].isoformat() if agregado['ultimo'] else None
    return (agregado['total'], ultimo)


def _is_current(indice, fingerprint, config):
    return (
        indice is not None
        and indice.format == INDEX_FORMAT
        and indice.fingerprint == fingerprint
        and indice.feature_hash == config.feature_hash
    )


def get_index():
    """Índice atual, do cache em memória, do disco ou reconstruído, nessa ordem."""
    global _cached, _checked_at
    config = get_config()
    # Dentro do intervalo, nem consulta o banco: o catálogo muda raramente (só por comando).
    if _cached is not None and time.monotonic() - _checked_at < config.fingerprint_ttl:
        return _cached

    fingerprint = _fingerprint()
    if _is_current(_cached, fingerprint, config):
        _checked_at = time.monotonic()
        return _cached

    with _lock:
        if not _is_current(_cached, fingerprint, config):
            indice = _load_from_disk(config)
            if not _is_current(indice, fingerprint, config):
                indice = _build_and_save(config, fingerprint)
            _cached = indice
        _checked_at = time.monotonic()
        return _cached


def rebuild_index():
    global _cached, _checked_at
    with _lock:
        _cached = _build_and_save(get_config(), _fingerprint())
        _checked_at = time.monotonic()
        return _cached


def _load_from_disk(config):
    if not config.index_path.is_file():
        return None
    try:
        return joblib.load(config.index_path)
    except Exception:  # arquivo corrompido ou de outra versão: reconstrói
        logger.warning('Índice em %s ilegível; será reconstruído.', config.index_path, exc_info=True)
        return None


def _build_and_save(config, fingerprint):
    indice = build_index(_load_catalog(), config, fingerprint)
    config.index_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(indice, config.index_path, compress=3)
    return indice


def _load_catalog():
    campos = ['id', 'kind', 'title', 'overview', 'tagline', 'keywords', 'cast', 'director',
              'year', 'vote_average', 'vote_count', 'popularity']
    df = pd.DataFrame.from_records(
        list(Title.objects.order_by('id').values_list(*campos)), columns=campos
    )
    generos = defaultdict(list)
    for title_id, nome in Title.genres.through.objects.values_list('title_id', 'genre__name'):
        generos[title_id].append(nome)
    df['genres'] = df['id'].map(lambda i: generos.get(i, []))
    df['year'] = pd.to_numeric(df['year'], errors='coerce')
    return df


def build_index(df, config, fingerprint=None):
    if df.empty:
        raise EmptyCatalog('O catálogo está vazio. Rode `python manage.py import_dataset`.')
    df = df.reset_index(drop=True)
    features = build_features(df, config)
    rating, popularity, votes = quality_signals(df, config.vote_quantile)
    return RecommenderIndex(
        ids=df['id'].to_numpy(np.int64),
        kinds=df['kind'].to_numpy(str),
        work_keys=_work_keys(df),
        matrix=features.matrix,
        blocks=features.blocks,
        tag_tokens=features.tag_tokens,
        tag_labels=features.tag_labels,
        q_rating=rating,
        q_popularity=popularity,
        q_votes=votes,
        fingerprint=fingerprint,
        feature_hash=config.feature_hash,
    )


def _work_keys(df):
    # "Spirited Away" (2001) existe no TMDB como filme e no MyAnimeList como anime.
    anos = df['year'].fillna(0).astype(int).astype(str)
    return (df['title'].map(slug_token) + '|' + anos).to_numpy(str)


# ---------------------------------------------------------------- consultas

def similar_to(indice, title_id, params):
    """Títulos parecidos com `title_id` (filtro híbrido aplicado)."""
    if title_id not in indice.row_of:
        return []
    return _rank(indice, indice.vector(title_id), params, excluir=_same_works(indice, [indice.row_of[title_id]]))


def recommend_for_profile(indice, sinais, params):
    """Recomendações para um histórico de sinais (curti / não curti).

    Devolve (recomendações, vetor de perfil). Sem nenhum "curti" o perfil é None e o
    resultado cai no ranking de qualidade (partida a frio).
    """
    config = get_config()
    perfil = build_profile(indice, sinais, config.recency_half_life, config.dislike_weight)
    vistos = _same_works(indice, [indice.row_of[s.title_id] for s in sinais if s.title_id in indice.row_of])
    if perfil is None:
        return _rank_by_quality(indice, params, vistos), None
    return _rank(indice, perfil, params, excluir=vistos), perfil


def similarity_matrix(indice, ids):
    """Bloco da matriz de similaridade do cosseno entre os títulos informados (len(ids)²)."""
    linhas = [indice.row_of[i] for i in ids if i in indice.row_of]
    sub = indice.matrix[linhas]
    return [int(indice.ids[l]) for l in linhas], (sub @ sub.T).toarray()


def _same_works(indice, linhas):
    """As linhas informadas mais as de outras fontes que representam a mesma obra."""
    if not linhas:
        return set()
    return set(np.flatnonzero(np.isin(indice.work_keys, indice.work_keys[linhas])).tolist())


def _eligible(indice, params, excluir):
    mascara = indice.q_votes >= params.obscurity
    if params.kinds:
        mascara &= np.isin(indice.kinds, params.kinds)
    if excluir:
        mascara[list(excluir)] = False
    return mascara


def _quality(indice, linhas, params):
    w = params.rating_weight
    return w * indice.q_rating[linhas] + (1 - w) * indice.q_popularity[linhas]


def _rank(indice, consulta, params, excluir):
    config = get_config()
    similaridades = indice.matrix @ consulta
    candidatos = np.flatnonzero(_eligible(indice, params, excluir) & (similaridades > 0))
    if candidatos.size == 0:
        return []

    ordem = np.argsort(-similaridades[candidatos], kind='stable')[: config.candidate_pool]
    pool = candidatos[ordem]
    sim = similaridades[pool]
    qualidade = _quality(indice, pool, params)
    relevancia = sim / sim.max()
    score = params.alpha * relevancia + (1 - params.alpha) * qualidade

    escolhidos = mmr(indice.matrix[pool], score, params.k, params.diversity)
    return [
        Recommendation(
            title_id=int(indice.ids[pool[i]]),
            score=float(score[i]),
            similarity=float(sim[i]),
            relevance=float(relevancia[i]),
            quality=float(qualidade[i]),
            contributions=_contributions(indice, pool[i], consulta),
            reasons=_reasons(indice, pool[i], consulta),
        )
        for i in escolhidos
    ]


def _rank_by_quality(indice, params, excluir):
    linhas = np.flatnonzero(_eligible(indice, params, excluir))
    qualidade = _quality(indice, linhas, params)
    melhores = np.argsort(-qualidade, kind='stable')[: params.k]
    return [
        Recommendation(
            title_id=int(indice.ids[linhas[i]]),
            score=float(qualidade[i]),
            similarity=0.0,
            relevance=0.0,
            quality=float(qualidade[i]),
            contributions={},
            reasons=[],
        )
        for i in melhores
    ]


def mmr(vetores, scores, k, diversidade):
    """Maximal Marginal Relevance: troca um pouco de score por menos redundância.

        escolhe argmax  (1 − λ) · score_i − λ · max_{j escolhido} cos(i, j)
    """
    k = min(k, len(scores))
    if diversidade <= 0 or k <= 1:
        return list(np.argsort(-scores, kind='stable')[:k])

    similaridade = (vetores @ vetores.T).toarray()
    maior_sim = np.zeros(len(scores), dtype=np.float32)
    escolhidos = []
    for _ in range(k):
        valor = (1 - diversidade) * scores - diversidade * maior_sim
        valor[escolhidos] = -np.inf
        i = int(np.argmax(valor))
        escolhidos.append(i)
        maior_sim = np.maximum(maior_sim, similaridade[i])
    return escolhidos


# ---------------------------------------------------------------- explicações

def _contributions(indice, linha, consulta):
    vetor = indice.matrix[linha]
    partes = {}
    for bloco, (inicio, fim) in indice.blocks.items():
        fatia = vetor[:, inicio:fim]
        partes[bloco] = float(fatia.data @ consulta[inicio:fim][fatia.indices]) if fatia.nnz else 0.0
    return partes


def _reasons(indice, linha, consulta, limite=4):
    """Tokens do bloco de tags que mais contribuíram para a similaridade."""
    inicio, fim = indice.blocks['tags']
    fatia = indice.matrix[linha][:, inicio:fim]
    if not fatia.nnz:
        return []
    produto = fatia.data * consulta[inicio:fim][fatia.indices]
    melhores = np.argsort(-produto)[:limite]
    return [_label(indice, fatia.indices[i]) for i in melhores if produto[i] > 0]


def _label(indice, coluna):
    token = str(indice.tag_tokens[coluna])
    prefixo = token.split(':', 1)[0]
    return {
        'token': token,
        'label': indice.tag_labels.get(token, token.split(':', 1)[-1]),
        'group': TAG_PREFIXES.get(prefixo, ''),
    }


def describe_profile(indice, perfil, limite=10):
    """Resumo legível do perfil ("DNA"): tokens dominantes, peso de cada bloco, tipos e época."""
    inicio, fim = indice.blocks['tags']
    tags = perfil[inicio:fim]
    positivos = np.flatnonzero(tags > 0)
    melhores = positivos[np.argsort(-tags[positivos])[:limite]]
    topo = float(tags[melhores[0]]) if melhores.size else 1.0
    dna = [{**_label(indice, c), 'weight': float(tags[c] / topo)} for c in melhores]

    energia = {b: float(np.sum(perfil[i:f] ** 2)) for b, (i, f) in indice.blocks.items()}
    total = sum(energia.values()) or 1.0

    # Layout do bloco de atributos: [tipos (3) | ano (RBF) | nota (RBF)].
    a0, _ = indice.blocks['attributes']
    n_tipo, n_ano = len(KINDS), len(YEAR_CENTERS)
    tipos = np.clip(perfil[a0:a0 + n_tipo], 0, None)
    anos = np.clip(perfil[a0 + n_tipo:a0 + n_tipo + n_ano], 0, None)
    notas = np.clip(perfil[a0 + n_tipo + n_ano:a0 + n_tipo + n_ano + len(RATING_CENTERS)], 0, None)

    return {
        'dna': dna,
        'blocks': {b: e / total for b, e in energia.items()},
        'kinds': {k: float(v) for k, v in zip(KINDS, tipos / tipos.sum())} if tipos.sum() else {},
        'year': float(anos @ YEAR_CENTERS / anos.sum()) if anos.sum() else None,
        'rating': float(notas @ RATING_CENTERS / notas.sum()) if notas.sum() else None,
    }
