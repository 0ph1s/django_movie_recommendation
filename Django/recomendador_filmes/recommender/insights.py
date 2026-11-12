"""
Insights da página de perfil: estatísticas, DNA, radar de gêneros, títulos que te definem,
conforto × exploração e watchlist com % de match.

Tudo é calculado na hora a partir do histórico, no mesmo espaço vetorial das recomendações
(não há treino). `exclude` recalcula o perfil sem alguns títulos, sem gravar nada: é o modo
"e se" da página.

As funções devolvem IDs de títulos (`title_id`); quem chama troca pelos cartões serializados.
"""
import math
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from catalog.models import Title

from .avatar import avatar_grid
from .config import get_config
from .engine import describe_profile
from .features import KINDS
from .models import Interaction, state_weight
from .profile import Signal, build_profile, recency_weights

State = Interaction.State
POSITIVE = (State.FAVORITE, State.LIKE)
RATED = (State.FAVORITE, State.LIKE, State.DISLIKE, State.SEEN)  # tudo menos a watchlist

DNA_TOKENS = 24
RADAR_AXES = 8
RADAR_MIN_AXES = 5
DEFINING = 8
BLIND_SPOTS = 4
BLIND_PER_TYPE = 2
BLIND_MIN_GOOD = 5     # títulos bem avaliados para um grupo contar como ponto cego
GOOD_RATING = 0.75     # "bem avaliado": percentil da nota bayesiana no próprio tipo
GOOD_VOTES = 0.25      # ...e fora do quartil menos votado
KIND_PLURAL = {'movie': 'filmes', 'series': 'séries', 'anime': 'animes'}
MAP_CENTER_NEIGHBORS = 10   # o centro do perfil no mapa é a média destes títulos mais próximos
MAP_NEIGHBORS_SHOWN = 5     # vizinhos do centro listados abaixo do mapa (fora do histórico)


# ---------------------------------------------------------------- metadados do catálogo

@dataclass
class CatalogMeta:
    genres: list           # por linha do índice: gêneros do título
    years: np.ndarray      # por linha: ano (nan se desconhecido)
    coords: np.ndarray     # por linha: (x, y) no mapa do gosto (nan sem projeção)
    genre_share: dict      # gênero -> parcela no catálogo (cada título divide 1 entre os seus gêneros)
    groups: dict           # ('genre' | 'kind' | 'decade', valor) -> linhas do índice

    @property
    def has_map(self):
        return bool(np.isfinite(self.coords).all(axis=1).any())


_meta = {'key': None, 'value': None, 'map_version': 0}


def invalidate_catalog_meta():
    """Chamado por recommender.projection ao gravar coordenadas novas neste processo."""
    _meta['map_version'] += 1


def catalog_meta(indice):
    """Gêneros, anos, posições e grupos por linha do índice, calculados uma vez por índice.

    A chave usa o fingerprint do catálogo (e não `id(indice)`, que o Python pode reaproveitar
    para um índice novo) e a versão do mapa, que muda quando a projeção é regravada.
    """
    chave = (indice.fingerprint, indice.feature_hash, indice.size, _meta['map_version'])
    if _meta['key'] != chave:
        _meta['value'] = _build_meta(indice)
        _meta['key'] = chave
    return _meta['value']


def _build_meta(indice):
    linhas_db = {i: (ano, x, y) for i, ano, x, y in Title.objects.values_list('id', 'year', 'map_x', 'map_y')}
    anos = {i: v[0] for i, v in linhas_db.items()}
    generos = defaultdict(list)
    for title_id, nome in Title.genres.through.objects.values_list('title_id', 'genre__name'):
        generos[title_id].append(nome)

    por_linha = [sorted(generos.get(int(i), [])) for i in indice.ids]
    years = np.array([anos.get(int(i)) or np.nan for i in indice.ids], dtype=float)
    coords = np.array(
        [[np.nan if v is None else v for v in linhas_db.get(int(i), (None, None, None))[1:]] for i in indice.ids],
        dtype=float,
    ).reshape(-1, 2)
    parcela = Counter()
    grupos = defaultdict(list)
    for linha, nomes in enumerate(por_linha):
        for nome in nomes:
            parcela[nome] += 1 / len(nomes)
            grupos[('genre', nome)].append(linha)
        grupos[('kind', str(indice.kinds[linha]))].append(linha)
        if not np.isnan(years[linha]):
            grupos[('decade', int(years[linha]) // 10 * 10)].append(linha)
    total = sum(parcela.values()) or 1.0
    return CatalogMeta(
        genres=por_linha,
        years=years,
        coords=coords,
        genre_share={nome: valor / total for nome, valor in parcela.items()},
        groups={chave: np.array(linhas) for chave, linhas in grupos.items()},
    )


# ---------------------------------------------------------------- perfil

def _profile(indice, itens):
    config = get_config()
    sinais = [Signal(i.title_id, i.weight) for i in itens]
    return build_profile(indice, sinais, config.recency_half_life, config.dislike_weight)


def _vector_weights(indice, itens):
    """Peso de cada título no vetor (estado × recência), com sinal, como em build_profile."""
    validos = [i for i in itens if i.title_id in indice.row_of and i.weight != 0]
    recencia = recency_weights(len(validos), get_config().recency_half_life)
    return {i.title_id: float(r) * i.weight for i, r in zip(validos, recencia)}


def _genre_affinity(indice, meta, pesos):
    """Parcela de cada gênero no gosto: cada título positivo divide o seu peso entre os gêneros."""
    afinidade = Counter()
    for title_id, peso in pesos.items():
        if peso <= 0:
            continue
        nomes = meta.genres[indice.row_of[title_id]]
        for nome in nomes:
            afinidade[nome] += peso / len(nomes)
    total = sum(afinidade.values())
    return {nome: valor / total for nome, valor in afinidade.items()} if total else {}


def _lock(tem, precisa, unidade):
    return {'unlocked': tem >= precisa, 'have': tem, 'need': precisa, 'unit': unidade}


def build_insights(indice, historico, exclude=()):
    """Tudo o que a página de perfil mostra. `historico` vem em ordem cronológica."""
    config = get_config()
    meta = catalog_meta(indice)
    excluir = {int(i) for i in exclude}

    positivos = [i for i in historico if i.state in POSITIVE and i.title_id in indice.row_of]
    avaliados = [i for i in historico if i.state in RATED]
    ativos = [i for i in historico if i.title_id not in excluir]

    perfil_total = _profile(indice, historico)
    perfil = _profile(indice, ativos) if excluir else perfil_total
    pesos_total = _vector_weights(indice, historico)
    pesos = _vector_weights(indice, ativos) if excluir else pesos_total

    n_pos, n_aval = len(positivos), len(avaliados)
    locks = {
        'map': _lock(n_pos, config.unlock_map, 'positives'),
        'dna': _lock(n_pos, config.unlock_dna, 'positives'),
        'radar': _lock(n_pos, config.unlock_dna, 'positives'),
        'defining': _lock(n_pos, config.unlock_dna, 'positives'),
        'stats': _lock(n_aval, config.unlock_stats, 'rated'),
        'comfort': _lock(n_pos, config.unlock_comfort, 'positives'),
    }
    aberto = {nome: trava['unlocked'] for nome, trava in locks.items()}
    resumo_total = describe_profile(indice, perfil_total, limite=DNA_TOKENS) if perfil_total is not None else None

    return {
        'counts': {'positives': n_pos, 'rated': n_aval, 'total': len(historico)},
        'locks': locks,
        'map_available': meta.has_map,
        'map': _map(indice, meta, historico, perfil) if aberto['map'] and meta.has_map else None,
        'excluded': sorted(excluir),
        'avatar': avatar_grid(resumo_total),
        'stats': _stats(historico) if aberto['stats'] else None,
        'dna': (
            (describe_profile(indice, perfil, limite=DNA_TOKENS) if excluir else resumo_total)
            if aberto['dna'] and perfil is not None else None
        ),
        'radar': _radar(indice, meta, pesos_total, pesos) if aberto['radar'] else None,
        'defining': _defining(indice, historico, perfil_total, pesos_total, excluir) if aberto['defining'] else None,
        'comfort': _comfort(indice, meta, historico, ativos, perfil) if aberto['comfort'] else None,
        'watchlist': _watchlist(indice, historico, perfil),
        'whatif': _whatif(indice, meta, historico, pesos_total, pesos, excluir) if excluir else None,
    }


# ---------------------------------------------------------------- seções

def _minutes(titulo):
    """Duração total estimada: filme pelo runtime; série e anime por runtime × episódios."""
    if titulo.kind == Title.Kind.MOVIE:
        return titulo.runtime or None
    if titulo.runtime and titulo.episodes:
        return titulo.runtime * titulo.episodes
    return None


def _stats(historico):
    avaliados = [i for i in historico if i.state in RATED]
    por_tipo = Counter(i.title.kind for i in avaliados)
    decadas = Counter(
        i.title.year // 10 * 10 for i in historico if i.state in POSITIVE and i.title.year
    )
    minutos, sem_duracao = 0, 0
    for item in avaliados:
        duracao = _minutes(item.title)
        if duracao:
            minutos += duracao
        else:
            sem_duracao += 1
    return {
        'rated': len(avaliados),
        'by_kind': {kind: por_tipo.get(kind, 0) for kind in KINDS},
        'by_state': {estado: sum(1 for i in historico if i.state == estado) for estado in State.values},
        # Em empate, a década mais recente.
        'favorite_decade': max(decadas.items(), key=lambda kv: (kv[1], kv[0]))[0] if decadas else None,
        'hours': round(minutos / 60),
        'hours_missing': sem_duracao,
    }


def _radar(indice, meta, pesos_total, pesos):
    """Afinidade por gênero comparada com a parcela do gênero no catálogo.

    Os eixos vêm do perfil completo (os gêneros mais fortes, completados pelos mais comuns do
    catálogo), para que o modo "e se" mude os valores sem trocar os eixos de lugar.
    """
    completo = _genre_affinity(indice, meta, pesos_total)
    if not completo:
        return None
    atual = _genre_affinity(indice, meta, pesos)
    eixos = sorted(completo, key=lambda g: -completo[g])[:RADAR_AXES]
    for nome in sorted(meta.genre_share, key=lambda g: -meta.genre_share[g]):
        if len(eixos) >= RADAR_MIN_AXES:
            break
        if nome not in eixos:
            eixos.append(nome)
    return {
        'axes': [
            {'genre': g, 'user': round(atual.get(g, 0.0), 4), 'catalog': round(meta.genre_share.get(g, 0.0), 4)}
            for g in eixos
        ],
    }


def _defining(indice, historico, perfil_total, pesos_total, excluir):
    """Os positivos que mais puxam o vetor: peso (estado × recência) × cosseno com o perfil."""
    if perfil_total is None:
        return []
    itens = [i for i in historico if i.state in POSITIVE and i.title_id in indice.row_of]
    linhas = [indice.row_of[i.title_id] for i in itens]
    cossenos = np.asarray(indice.matrix[linhas] @ perfil_total).ravel()
    contribuicoes = np.array([pesos_total[i.title_id] for i in itens]) * np.clip(cossenos, 0, None)
    total = float(contribuicoes.sum()) or 1.0
    ordem = np.argsort(-contribuicoes, kind='stable')[:DEFINING]
    return [
        {
            'title_id': itens[k].title_id,
            'state': itens[k].state,
            'share': round(float(contribuicoes[k]) / total, 4),
            'excluded': itens[k].title_id in excluir,
        }
        for k in ordem
    ]


def _entropy(contagem, categorias):
    """Entropia normalizada (0 = tudo numa categoria, 1 = espalhado por todas)."""
    total = sum(contagem.values())
    if total <= 0 or categorias <= 1:
        return 0.0
    p = np.array([v / total for v in contagem.values() if v > 0])
    return float(-(p * np.log(p)).sum() / math.log(categorias))


def _comfort(indice, meta, historico, ativos, perfil):
    """Ecletismo (entropia de gêneros e tipos), dispersão no espaço e pontos cegos."""
    positivos = [i for i in ativos if i.state in POSITIVE and i.title_id in indice.row_of]
    generos, tipos = Counter(), Counter()
    for item in positivos:
        peso = state_weight(item.state)
        linha = indice.row_of[item.title_id]
        nomes = meta.genres[linha]
        for nome in nomes:
            generos[nome] += peso / len(nomes)
        tipos[str(indice.kinds[linha])] += peso

    n_tipos = len(set(indice.kinds.tolist()))
    ecletismo = 0.7 * _entropy(generos, len(meta.genre_share)) + 0.3 * _entropy(tipos, n_tipos)

    dispersao = None
    if perfil is not None and positivos:
        linhas = [indice.row_of[i.title_id] for i in positivos]
        dispersao = 1.0 - float(np.asarray(indice.matrix[linhas] @ perfil).ravel().mean())

    return {
        'eclecticism': round(ecletismo, 4),
        'dispersion': round(dispersao, 4) if dispersao is not None else None,
        'blind_spots': _blind_spots(indice, meta, historico, perfil),
    }


def _blind_spots(indice, meta, historico, perfil):
    """Gêneros, tipos e décadas com muitos títulos bem avaliados e nenhuma interação sua."""
    vistos = np.zeros(indice.size, dtype=bool)
    for item in historico:
        if item.title_id in indice.row_of:
            vistos[indice.row_of[item.title_id]] = True
    bons = (indice.q_rating >= GOOD_RATING) & (indice.q_votes >= GOOD_VOTES)

    candidatos = []
    for (tipo, valor), linhas in meta.groups.items():
        if vistos[linhas].any():
            continue
        boas = linhas[bons[linhas]]
        if len(boas) >= BLIND_MIN_GOOD:
            candidatos.append((len(boas), tipo, valor, boas))

    similaridades = np.asarray(indice.matrix @ perfil).ravel() if perfil is not None else None
    escolhidos, por_tipo = [], Counter()
    for quantidade, tipo, valor, boas in sorted(candidatos, key=lambda c: (-c[0], c[1], str(c[2]))):
        if por_tipo[tipo] >= BLIND_PER_TYPE:
            continue
        por_tipo[tipo] += 1
        escolhidos.append({
            'type': tipo,
            'value': valor,
            'label': _group_label(tipo, valor),
            'count': quantidade,
            'suggestion_id': _entry_title(indice, boas, similaridades),
        })
        if len(escolhidos) >= BLIND_SPOTS:
            break
    return escolhidos


def _group_label(tipo, valor):
    if tipo == 'kind':
        return KIND_PLURAL.get(valor, valor)
    if tipo == 'decade':
        return f'anos {valor}'
    return valor


def _entry_title(indice, linhas, similaridades):
    """Porta de entrada para um ponto cego: bem avaliado e, se houver perfil, perto dele."""
    qualidade = indice.q_rating[linhas]
    if similaridades is None:
        score = qualidade
    else:
        sim = np.clip(similaridades[linhas], 0, None)
        score = 0.5 * (sim / max(float(sim.max()), 1e-9)) + 0.5 * qualidade
    return int(indice.ids[linhas[int(np.argmax(score))]])


def _map(indice, meta, historico, perfil):
    """Seus títulos no mapa, o centro do perfil e os vizinhos mais próximos dele.

    O t-SNE não projeta pontos novos, então o centro é a média das coordenadas dos títulos
    mais próximos do vetor de perfil (no cosseno). No modo "e se", ele se move junto.
    """
    com_posicao = np.isfinite(meta.coords).all(axis=1)
    pontos = []
    for item in historico:
        linha = indice.row_of.get(item.title_id)
        if linha is None or not com_posicao[linha]:
            continue
        pontos.append({
            'title_id': item.title_id,
            'state': item.state,
            'x': round(float(meta.coords[linha, 0]), 4),
            'y': round(float(meta.coords[linha, 1]), 4),
        })
    if perfil is None:
        return {'points': pontos, 'center': None, 'neighbor_ids': []}

    similaridades = np.asarray(indice.matrix @ perfil).ravel()
    similaridades[~com_posicao] = -np.inf
    ordem = np.argsort(-similaridades, kind='stable')
    centro = meta.coords[ordem[:MAP_CENTER_NEIGHBORS]].mean(axis=0)

    vistos = {indice.row_of[i.title_id] for i in historico if i.title_id in indice.row_of}
    vizinhos = [int(indice.ids[r]) for r in ordem[: MAP_NEIGHBORS_SHOWN + len(vistos)] if r not in vistos]
    return {
        'points': pontos,
        'center': {'x': round(float(centro[0]), 4), 'y': round(float(centro[1]), 4)},
        'neighbor_ids': vizinhos[:MAP_NEIGHBORS_SHOWN],
    }


def _watchlist(indice, historico, perfil):
    """Títulos marcados como "quero assistir", com o % de match (cosseno relativo ao melhor)."""
    itens = [i for i in historico if i.state == State.WATCHLIST]
    if not itens:
        return []
    match = {}
    if perfil is not None:
        similaridades = np.asarray(indice.matrix @ perfil).ravel()
        fora = np.ones(indice.size, dtype=bool)
        for item in historico:
            if item.title_id in indice.row_of:
                fora[indice.row_of[item.title_id]] = False
        topo = float(similaridades[fora].max()) if fora.any() else 0.0
        for item in itens:
            if item.title_id in indice.row_of and topo > 0:
                valor = similaridades[indice.row_of[item.title_id]] / topo
                match[item.title_id] = round(float(min(max(valor, 0.0), 1.0)), 4)
    linhas = [{'title_id': i.title_id, 'match': match.get(i.title_id)} for i in reversed(itens)]
    return sorted(linhas, key=lambda w: -(w['match'] or 0))


def _whatif(indice, meta, historico, pesos_total, pesos, excluir):
    """O gênero que mais perde espaço no gosto sem os títulos excluídos.

    Escolhe pela perda absoluta (pontos de parcela), para que um gênero pequeno que some por
    inteiro não roube a frase de um gênero central que encolhe; informa a perda relativa.
    """
    antes = _genre_affinity(indice, meta, pesos_total)
    depois = _genre_affinity(indice, meta, pesos)
    titulos = [i.title_id for i in historico if i.title_id in excluir]
    quedas = {g: v - depois.get(g, 0.0) for g, v in antes.items()}
    genero = max(quedas, key=quedas.get) if quedas else None
    if genero is None or quedas[genero] < 0.01:
        return {'title_ids': titulos, 'genre': None, 'loss': 0.0, 'empty': not depois}
    return {
        'title_ids': titulos,
        'genre': genero,
        'loss': round(quedas[genero] / antes[genero], 4),
        'empty': not depois,
    }


def profile_summary(indice, historico):
    """Resumo do perfil completo (DNA, tipos, época) ou None, sem nenhum positivo."""
    perfil = _profile(indice, historico)
    return describe_profile(indice, perfil, limite=DNA_TOKENS) if perfil is not None else None
