# catalog/importers/base.py
"""Tipos e funções de limpeza compartilhados pelos adaptadores de dataset."""
import ast
import json
import math
import re
from dataclasses import dataclass, field

import pandas as pd

# Vocabulário canônico de gêneros: o do TMDB para filmes, acrescido dos gêneros
# próprios de anime que não têm equivalente (Slice of Life, Mecha, Sports...).
# Cada entrada mapeia um rótulo de origem (em minúsculas) para um ou mais gêneros canônicos.
_GENRE_ALIASES = {
    'sci-fi': ['Science Fiction'],
    'science fiction': ['Science Fiction'],
    'sci-fi & fantasy': ['Science Fiction', 'Fantasy'],
    'action & adventure': ['Action', 'Adventure'],
    'war & politics': ['War'],
    'military': ['War'],
    'suspense': ['Thriller'],
    'historical': ['History'],
    'kids': ['Family'],
    'soap': ['Drama'],
    'martial arts': ['Action'],
    'super power': ['Action'],
    'space': ['Science Fiction'],
    'dementia': ['Psychological'],
}

# Rótulos descartados: metadados que não são gênero, ou ausência de valor.
_GENRES_IGNORED = {'', 'unknown', 'award winning', 'foreign'}

# Conteúdo adulto explícito fica fora do catálogo.
ADULT_GENRES = {'hentai', 'erotica'}

# No CSV pré-mesclado do TMDB 5000 os gêneros vêm separados por espaço
# ("Action Science Fiction"), então os nomes compostos precisam ser reconhecidos antes.
_MULTIWORD_GENRES = ['Science Fiction', 'TV Movie']

_UNICODE_ESCAPE = re.compile(r'\\u([0-9a-fA-F]{4})')
_YEAR = re.compile(r'(18|19|20)\d{2}')
_MISSING_MARKERS = {'', 'unknown', 'nan', 'none', 'null', 'n/a'}


@dataclass
class NormalizedTitle:
    """Registro já limpo, independente da fonte, pronto para virar um `Title`."""

    kind: str
    source: str
    external_id: str
    title: str
    original_title: str = ''
    overview: str = ''
    tagline: str = ''
    keywords: str = ''
    cast: str = ''
    director: str = ''
    genres: list[str] = field(default_factory=list)
    year: int | None = None
    runtime: int | None = None
    episodes: int | None = None
    vote_average: float = 0.0
    vote_count: int = 0
    popularity: float = 0.0
    poster_url: str = ''


def is_missing(valor):
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return str(valor).strip().lower() in _MISSING_MARKERS


def clean_text(valor, max_length=None):
    """Converte para str, decodifica escapes \\uXXXX literais e normaliza espaços."""
    if is_missing(valor):
        return ''
    texto = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), str(valor))
    texto = ' '.join(texto.split())
    if max_length and len(texto) > max_length:
        texto = texto[: max_length - 1].rstrip() + '…'
    return texto


def to_float(valor, default=0.0):
    if is_missing(valor):
        return default
    try:
        numero = float(str(valor).replace(',', ''))
    except ValueError:
        return default
    return default if math.isnan(numero) else numero


def to_int(valor, default=None):
    numero = to_float(valor, default=None)
    if numero is None:
        return default
    return int(numero)


def parse_year(valor):
    """Extrai o primeiro ano plausível de datas como '2009-12-10' ou 'Apr 3, 1998 to ...'."""
    if is_missing(valor):
        return None
    encontrado = _YEAR.search(str(valor))
    return int(encontrado.group(0)) if encontrado else None


def parse_names(valor, key='name'):
    """Lê listas de nomes em JSON (TMDB), em literal Python ou separadas por vírgula."""
    if is_missing(valor):
        return []
    texto = str(valor).strip()
    if texto.startswith('['):
        try:
            itens = json.loads(texto)
        except ValueError:
            try:
                itens = ast.literal_eval(texto)
            except (ValueError, SyntaxError):
                itens = []
        nomes = [item.get(key, '') if isinstance(item, dict) else item for item in itens]
        return [clean_text(n) for n in nomes if clean_text(n)]
    return [clean_text(parte) for parte in texto.split(',') if clean_text(parte)]


def split_space_separated_genres(valor):
    """'Action Science Fiction' -> ['Action', 'Science Fiction']."""
    texto = clean_text(valor)
    encontrados = []
    for composto in _MULTIWORD_GENRES:
        if composto in texto:
            encontrados.append(composto)
            texto = texto.replace(composto, ' ')
    return encontrados + texto.split()


def canonical_genres(rotulos):
    """Traduz rótulos de origem para o vocabulário canônico, sem repetições e na ordem."""
    canonicos = []
    for rotulo in rotulos:
        chave = clean_text(rotulo).lower()
        if chave in _GENRES_IGNORED:
            continue
        for nome in _GENRE_ALIASES.get(chave, [clean_text(rotulo)]):
            if nome not in canonicos:
                canonicos.append(nome)
    return canonicos


def read_csv(caminho):
    """Lê tudo como texto: a conversão de cada coluna é responsabilidade do adaptador."""
    return pd.read_csv(caminho, dtype=str, keep_default_na=False, encoding='utf-8')


def pick(linha, *colunas, default=''):
    """Primeiro valor presente entre colunas alternativas (os datasets mudam de versão)."""
    for coluna in colunas:
        if coluna in linha and not is_missing(linha[coluna]):
            return linha[coluna]
    return default
