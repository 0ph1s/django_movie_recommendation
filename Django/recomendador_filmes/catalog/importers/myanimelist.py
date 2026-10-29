# catalog/importers/myanimelist.py
"""Adaptador para datasets do MyAnimeList.

Formato principal: "Anime Dataset 2023" (anime-dataset-2023.csv). Também aceita as
colunas do dataset de 2020 (anime.csv / anime_with_synopsis.csv, incluindo o
nome de coluna `sypnopsis`, grafado assim no original).

Mapeamento para o modelo comum:
  * nota          <- Score (0–10, mesma escala do TMDB)
  * votos         <- Scored By
  * popularidade  <- Members (no MAL, "Popularity" é uma posição no ranking, não um volume)
  * "direção"     <- Studios (a assinatura autoral mais estável em anime)
"""
from .base import (
    ADULT_GENRES,
    NormalizedTitle,
    canonical_genres,
    clean_text,
    parse_names,
    parse_year,
    pick,
    read_csv,
    to_float,
    to_int,
)

# Formatos que não são obras narrativas (videoclipes) ficam de fora.
_IGNORED_TYPES = {'music'}
_ADULT_RATING_PREFIX = 'rx'


def _source(linha):
    # "Original" (roteiro próprio) é o caso comum e não aproxima obras entre si.
    origem = clean_text(pick(linha, 'Source', 'source'))
    return '' if origem.lower() in {'original', 'other'} else origem


def read_anime(caminho):
    for linha in read_csv(caminho).to_dict('records'):
        nome = clean_text(pick(linha, 'Name', 'name'))
        nome_ingles = clean_text(pick(linha, 'English name', 'english_name'))
        identificador = clean_text(pick(linha, 'anime_id', 'MAL_ID', 'mal_id'))
        if not (nome or nome_ingles) or not identificador:
            continue

        rotulos = parse_names(pick(linha, 'Genres', 'genres', 'genre'))
        classificacao = clean_text(pick(linha, 'Rating', 'rating')).lower()
        if ADULT_GENRES & {r.lower() for r in rotulos} or classificacao.startswith(_ADULT_RATING_PREFIX):
            continue
        formato = clean_text(pick(linha, 'Type', 'type'))
        if formato.lower() in _IGNORED_TYPES:
            continue

        # Título em inglês quando existe: é o nome pelo qual a maioria do público procura.
        yield NormalizedTitle(
            kind='anime',
            source='mal',
            external_id=identificador,
            title=nome_ingles or nome,
            original_title=nome if nome_ingles and nome != nome_ingles else '',
            overview=clean_text(pick(linha, 'Synopsis', 'synopsis', 'sypnopsis')),
            # A obra de origem (mangá, light novel...) e os temas viram palavras-chave.
            keywords=' '.join(filter(None, [_source(linha), clean_text(pick(linha, 'Themes', 'themes'))])),
            cast=', '.join(parse_names(pick(linha, 'cast', 'Voice Actors'))[:8]),
            director=clean_text(', '.join(parse_names(pick(linha, 'Studios', 'studios'))[:3]), max_length=255),
            # O MAL não rotula "Animation" (seria redundante lá); aqui ele liga animes a filmes animados.
            genres=canonical_genres(['Animation', *rotulos]),
            year=parse_year(pick(linha, 'Aired', 'aired', 'Premiered', 'premiered')),
            episodes=to_int(pick(linha, 'Episodes', 'episodes')),
            vote_average=to_float(pick(linha, 'Score', 'score')),
            vote_count=to_int(pick(linha, 'Scored By', 'scored_by'), default=0),
            popularity=to_float(pick(linha, 'Members', 'members')),
            poster_url=clean_text(pick(linha, 'Image URL', 'image_url')),
        )
