# api/serializers.py
"""Conversão de modelos e resultados do motor para dicionários JSON."""

OVERVIEW_PREVIEW = 220


def title_card(titulo):
    """Versão compacta para listas (exige `prefetch_related('genres')`)."""
    sinopse = titulo.overview
    if len(sinopse) > OVERVIEW_PREVIEW:
        sinopse = sinopse[:OVERVIEW_PREVIEW].rsplit(' ', 1)[0] + '…'
    return {
        'id': titulo.pk,
        'title': titulo.title,
        'original_title': titulo.original_title,
        'kind': titulo.kind,
        'kind_label': titulo.get_kind_display(),
        'year': titulo.year,
        'genres': [g.name for g in titulo.genres.all()],
        'director': titulo.director,
        'vote_average': round(titulo.vote_average, 1),
        'vote_count': titulo.vote_count,
        'overview': sinopse,
        'poster_url': titulo.poster_url,
    }


def title_detail(titulo):
    return {
        **title_card(titulo),
        'overview': titulo.overview,
        'tagline': titulo.tagline,
        'cast': titulo.cast,
        'runtime': titulo.runtime,
        'episodes': titulo.episodes,
        'popularity': titulo.popularity,
    }


def recommendation(rec, titulo):
    return {
        **title_card(titulo),
        'score': round(rec.score, 4),
        'similarity': round(rec.similarity, 4),
        'relevance': round(rec.relevance, 4),
        'quality': round(rec.quality, 4),
        'contributions': {bloco: round(valor, 4) for bloco, valor in rec.contributions.items()},
        'reasons': rec.reasons,
    }


def interaction(item):
    return {
        'signal': item.signal,
        'updated_at': item.updated_at.isoformat(),
        'title': title_card(item.title),
    }
