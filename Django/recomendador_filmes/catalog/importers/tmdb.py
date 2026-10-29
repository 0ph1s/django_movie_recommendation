# catalog/importers/tmdb.py
"""Adaptadores para os datasets do TMDB (filmes e séries).

Filmes — aceita os dois formatos do "TMDB 5000 Movie Dataset":
  * o par original do Kaggle (tmdb_5000_movies.csv + tmdb_5000_credits.csv), com
    gêneros, palavras-chave, elenco e equipe em JSON;
  * a versão pré-mesclada (como data/tmdb_5000_movies.csv), em que gêneros,
    palavras-chave e elenco já vêm como texto e há uma coluna `director`.

Séries — formato do "Full TMDB TV Shows Dataset" (TMDB_tv_dataset_v3.csv), com
gêneros e criadores separados por vírgula. Uma coluna `cast` opcional é aproveitada.
"""
from .base import (
    NormalizedTitle,
    canonical_genres,
    clean_text,
    is_missing,
    parse_names,
    parse_year,
    pick,
    read_csv,
    split_space_separated_genres,
    to_float,
    to_int,
)

POSTER_BASE_URL = 'https://image.tmdb.org/t/p/w500'
MAX_CAST = 8


def _is_json_list(valor):
    return not is_missing(valor) and str(valor).lstrip().startswith('[')


def _genres(valor):
    rotulos = parse_names(valor) if _is_json_list(valor) else split_space_separated_genres(valor)
    return canonical_genres(rotulos)


def _keywords(valor):
    return ' '.join(parse_names(valor)) if _is_json_list(valor) else clean_text(valor)


def _cast(valor):
    if _is_json_list(valor):
        return ', '.join(parse_names(valor)[:MAX_CAST])
    return clean_text(valor)


def _director(linha):
    if not is_missing(linha.get('director')):
        return clean_text(linha['director'])
    equipe = linha.get('crew')
    if not _is_json_list(equipe):
        return ''
    diretores = [
        nome for nome, cargo in zip(parse_names(equipe), parse_names(equipe, key='job'))
        if cargo == 'Director'
    ]
    return ', '.join(diretores[:2])


def _poster(caminho):
    caminho = clean_text(caminho)
    if not caminho:
        return ''
    return caminho if caminho.startswith('http') else f'{POSTER_BASE_URL}{caminho}'


def read_movies(caminho, credits_path=None):
    df = read_csv(caminho)
    if credits_path:
        creditos = read_csv(credits_path).rename(columns={'movie_id': 'id'})
        df = df.merge(creditos[['id', 'cast', 'crew']], on='id', how='left', suffixes=('_old', ''))

    for linha in df.to_dict('records'):
        titulo = clean_text(linha.get('title'))
        if not titulo or is_missing(linha.get('id')):
            continue
        yield NormalizedTitle(
            kind='movie',
            source='tmdb',
            external_id=clean_text(linha['id']),
            title=titulo,
            original_title=clean_text(linha.get('original_title')),
            overview=clean_text(linha.get('overview')),
            tagline=clean_text(linha.get('tagline'), max_length=400),
            keywords=_keywords(linha.get('keywords')),
            cast=_cast(linha.get('cast')),
            director=clean_text(_director(linha), max_length=255),
            genres=_genres(linha.get('genres')),
            year=parse_year(linha.get('release_date')),
            runtime=to_int(linha.get('runtime')) or None,
            vote_average=to_float(linha.get('vote_average')),
            vote_count=to_int(linha.get('vote_count'), default=0),
            popularity=to_float(linha.get('popularity')),
            poster_url=_poster(linha.get('poster_path')),
        )


def read_series(caminho):
    for linha in read_csv(caminho).to_dict('records'):
        titulo = clean_text(pick(linha, 'name', 'title'))
        if not titulo or is_missing(linha.get('id')):
            continue
        if clean_text(linha.get('adult')).lower() == 'true':
            continue
        # A emissora ("HBO") funciona como palavra-chave; do formato, só "Miniseries"
        # diz algo (quase todas as séries são "Scripted").
        redes = parse_names(linha.get('networks'))
        formato = clean_text(linha.get('type'))
        formato = formato if formato.lower() == 'miniseries' else ''
        duracoes = parse_names(linha.get('episode_run_time'))
        yield NormalizedTitle(
            kind='series',
            source='tmdb',
            external_id=clean_text(linha['id']),
            title=titulo,
            original_title=clean_text(pick(linha, 'original_name', 'original_title')),
            overview=clean_text(linha.get('overview')),
            tagline=clean_text(linha.get('tagline'), max_length=400),
            keywords=' '.join([clean_text(linha.get('keywords')), *redes, formato]).strip(),
            cast=', '.join(parse_names(linha.get('cast'))[:MAX_CAST]),
            director=clean_text(', '.join(parse_names(linha.get('created_by'))[:3]), max_length=255),
            genres=canonical_genres(parse_names(linha.get('genres'))),
            year=parse_year(pick(linha, 'first_air_date', 'release_date')),
            runtime=to_int(duracoes[0]) if duracoes else None,
            episodes=to_int(linha.get('number_of_episodes')),
            vote_average=to_float(linha.get('vote_average')),
            vote_count=to_int(linha.get('vote_count'), default=0),
            popularity=to_float(linha.get('popularity')),
            poster_url=_poster(linha.get('poster_path')),
        )
