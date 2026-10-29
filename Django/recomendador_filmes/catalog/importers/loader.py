# catalog/importers/loader.py
"""Grava registros normalizados no banco com upsert em lote."""
from dataclasses import asdict

import pandas as pd
from django.db import transaction
from django.utils.text import slugify

from ..models import Genre, Title

BATCH_SIZE = 500
_UPSERT_FIELDS = [
    'title', 'original_title', 'overview', 'tagline', 'keywords', 'cast', 'director',
    'year', 'runtime', 'episodes', 'vote_average', 'vote_count', 'popularity', 'updated_at',
]


def select_records(registros, min_votes=0, limit=None):
    """Remove duplicados (fica o último), aplica o mínimo de votos e mantém os `limit` mais populares."""
    unicos = {}
    for registro in registros:
        if registro.vote_count >= min_votes:
            unicos[(registro.source, registro.kind, registro.external_id)] = registro
    selecionados = sorted(unicos.values(), key=lambda r: r.popularity, reverse=True)
    return selecionados[:limit] if limit else selecionados


@transaction.atomic
def save_records(registros):
    """Cria ou atualiza títulos e seus gêneros. Retorna a quantidade gravada."""
    if not registros:
        return 0

    generos = _ensure_genres({nome for r in registros for nome in r.genres})

    titulos = []
    for registro in registros:
        dados = asdict(registro)
        dados.pop('genres')
        titulos.append(Title(**dados))
    Title.objects.bulk_create(
        titulos,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=['source', 'kind', 'external_id'],
        update_fields=_UPSERT_FIELDS,
    )

    # O bulk_create com upsert não devolve as PKs em todos os bancos: busca-as de novo.
    chaves = {(r.source, r.kind, r.external_id) for r in registros}
    ids = {
        (source, kind, external_id): pk
        for pk, source, kind, external_id in Title.objects.filter(
            source__in={c[0] for c in chaves}, kind__in={c[1] for c in chaves},
        ).values_list('pk', 'source', 'kind', 'external_id')
        if (source, kind, external_id) in chaves
    }

    # A capa só é sobrescrita quando o CSV traz uma: assim, reimportar o TMDB 5000 (que não
    # tem capas) preserva as que `fetch_posters` buscou.
    com_capa = [r for r in registros if r.poster_url]
    Title.objects.bulk_update(
        [Title(pk=ids[(r.source, r.kind, r.external_id)], poster_url=r.poster_url) for r in com_capa],
        ['poster_url'],
        batch_size=BATCH_SIZE,
    )

    Ligacao = Title.genres.through
    Ligacao.objects.filter(title_id__in=ids.values()).delete()
    Ligacao.objects.bulk_create(
        [
            Ligacao(title_id=ids[(r.source, r.kind, r.external_id)], genre_id=generos[nome])
            for r in registros
            for nome in r.genres
        ],
        batch_size=BATCH_SIZE,
    )
    return len(registros)


def refresh_popularity_ranks():
    """Recalcula o percentil de popularidade de cada título dentro do seu tipo."""
    linhas = list(Title.objects.values_list('pk', 'kind', 'popularity'))
    if not linhas:
        return
    df = pd.DataFrame(linhas, columns=['pk', 'kind', 'popularity'])
    df['rank'] = df.groupby('kind')['popularity'].rank(pct=True)
    Title.objects.bulk_update(
        [Title(pk=pk, popularity_rank=rank) for pk, rank in zip(df['pk'], df['rank'])],
        ['popularity_rank'],
        batch_size=BATCH_SIZE,
    )


def _ensure_genres(nomes):
    existentes = dict(Genre.objects.values_list('name', 'pk'))
    novos = [Genre(name=nome, slug=slugify(nome)) for nome in sorted(nomes - existentes.keys())]
    Genre.objects.bulk_create(novos, ignore_conflicts=True)
    return dict(Genre.objects.values_list('name', 'pk'))
