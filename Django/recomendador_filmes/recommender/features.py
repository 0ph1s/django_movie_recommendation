# recommender/features.py
"""
Construção da matriz de features em que a similaridade do cosseno é calculada.

Cada título vira um vetor esparso formado por três blocos:

  synopsis    TF-IDF (uni e bigramas) da sinopse + tagline.
  tags        TF-IDF de tokens categóricos: gêneros (com reforço), palavras-chave,
              elenco e direção/estúdio, cada pessoa colapsada em um único token.
  attributes  Atributos numéricos/categóricos codificados para que o cosseno faça
              sentido: tipo em one-hot; ano e nota em "one-hot suave" (funções de base
              radial), de modo que 1994 fique próximo de 1999 e longe de 1950.

Cada bloco é normalizado (L2) e multiplicado por √peso. Como os pesos somam 1, a linha
final tem norma 1 e o produto escalar de duas linhas é exatamente
    cos(a, b) = Σ_bloco peso · cos_bloco(a, b),
ou seja, a similaridade total se decompõe por bloco, o que alimenta as explicações.
Linhas com algum bloco vazio (ex.: sem sinopse) são renormalizadas ao final.
"""
import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

KINDS = ['movie', 'series', 'anime']
YEAR_CENTERS = np.arange(1910, 2031, 10, dtype=np.float32)
YEAR_SIGMA = 7.0
RATING_CENTERS = np.arange(1, 11, dtype=np.float32)
RATING_SIGMA = 0.75
# Peso de cada grupo dentro do bloco de atributos.
ATTRIBUTE_WEIGHTS = {'kind': 0.30, 'year': 0.40, 'rating': 0.30}

# Prefixos dos tokens do bloco de tags (também usados para exibir as explicações).
TAG_PREFIXES = {'g': 'gênero', 'd': 'direção', 'c': 'elenco', 'k': 'tema'}

_NON_ALNUM = re.compile(r'[^a-z0-9]+')


@dataclass
class FeatureMatrix:
    matrix: sparse.csr_matrix
    blocks: dict             # nome do bloco -> (coluna inicial, coluna final)
    tag_tokens: np.ndarray   # nome de cada coluna do bloco de tags
    tag_labels: dict         # token -> rótulo legível ("d:james_cameron" -> "James Cameron")


def slug_token(texto):
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower()
    return _NON_ALNUM.sub('_', texto).strip('_')


def build_features(df, config):
    """Recebe um DataFrame do catálogo (ver engine._load_catalog) e devolve a FeatureMatrix."""
    pesos = config.block_weights
    labels = {}

    sinopse = _synopsis_block(df, config)
    tags, tag_tokens = _tags_block(df, config, labels)
    atributos = _attributes_block(df)

    partes, blocos, inicio = [], {}, 0
    for nome, bloco in [('synopsis', sinopse), ('tags', tags), ('attributes', atributos)]:
        bloco = normalize(bloco.astype(np.float32), norm='l2', axis=1) * np.float32(np.sqrt(pesos[nome]))
        partes.append(bloco)
        blocos[nome] = (inicio, inicio + bloco.shape[1])
        inicio += bloco.shape[1]

    matriz = normalize(sparse.hstack(partes, format='csr'), norm='l2', axis=1).astype(np.float32)
    return FeatureMatrix(matriz, blocos, tag_tokens, labels)


def _min_df(n):
    # Em catálogos pequenos (testes, amostras) um termo presente em um só título ainda conta.
    return 2 if n >= 200 else 1


def _synopsis_block(df, config):
    textos = (df['overview'].fillna('') + ' ' + df['tagline'].fillna('')).str.strip()
    vetorizador = TfidfVectorizer(
        stop_words='english',
        strip_accents='unicode',
        sublinear_tf=True,
        ngram_range=(1, 2),
        min_df=_min_df(len(df)),
        max_df=0.5,
        max_features=config.max_synopsis_features,
        dtype=np.float32,
    )
    try:
        return vetorizador.fit_transform(textos)
    except ValueError:  # vocabulário vazio: nenhuma sinopse utilizável
        return sparse.csr_matrix((len(df), 1), dtype=np.float32)


def split_run_on_names(texto):
    """'Sam Worthington Zoe Saldana Samuel L. Jackson' -> ['Sam Worthington', 'Zoe Saldana', 'Samuel L. Jackson'].

    O elenco do CSV pré-mesclado do TMDB vem sem separador. A heurística agrupa as palavras
    duas a duas, estendendo o nome quando a palavra seguinte é uma inicial ("L."), uma
    partícula ("de", "van") ou um sufixo ("Jr."). Erra com nomes de uma palavra só, que são raros.
    """
    palavras = texto.split()
    nomes, i = [], 0
    while i < len(palavras):
        nome = palavras[i:i + 2]
        i += 2
        while i < len(palavras) and (
            _is_name_glue(nome[-1]) or palavras[i].rstrip('.,').lower() in _NAME_SUFFIXES
        ):
            nome.append(palavras[i])
            i += 1
        nomes.append(' '.join(nome))
    return nomes


_NAME_PARTICLES = {'de', 'da', 'do', 'dos', 'del', 'della', 'di', 'du', 'la', 'le', 'van', 'von', 'der', 'den', 'bin', 'st.'}
_NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv'}


def _is_name_glue(palavra):
    """Inicial ("L.") ou partícula ("van"): o nome continua na próxima palavra."""
    return (len(palavra) <= 2 and palavra.endswith('.')) or palavra.lower() in _NAME_PARTICLES


def _people_tokens(texto, prefixo, labels):
    """'Hayao Miyazaki, Isao Takahata' -> ['d:hayao_miyazaki', 'd:isao_takahata']."""
    if not texto:
        return []
    if ',' in texto or prefixo == 'd':
        nomes = [n.strip() for n in texto.split(',') if n.strip()]
    else:
        nomes = split_run_on_names(texto)
    tokens = []
    for nome in nomes:
        token = f'{prefixo}:{slug_token(nome)}'
        labels.setdefault(token, nome)
        tokens.append(token)
    return tokens


def _tags_block(df, config, labels):
    documentos = []
    for linha in df.itertuples(index=False):
        tokens = []
        for genero in linha.genres:
            token = f'g:{slug_token(genero)}'
            labels.setdefault(token, genero)
            tokens.extend([token] * config.genre_boost)
        for palavra in slug_token(linha.keywords or '').split('_'):
            if len(palavra) > 2:
                token = f'k:{palavra}'
                labels.setdefault(token, palavra)
                tokens.append(token)
        tokens += _people_tokens(linha.director, 'd', labels)
        tokens += _people_tokens(linha.cast, 'c', labels)
        documentos.append(tokens)

    vetorizador = TfidfVectorizer(
        analyzer=_identity,
        sublinear_tf=True,
        min_df=_min_df(len(df)),
        dtype=np.float32,
    )
    try:
        matriz = vetorizador.fit_transform(documentos)
    except ValueError:
        return sparse.csr_matrix((len(df), 1), dtype=np.float32), np.array(['_'])
    return matriz, vetorizador.get_feature_names_out()


def _identity(tokens):
    return tokens


def _rbf(valores, centros, sigma):
    """'One-hot suave': cada valor ativa os centros vizinhos com peso gaussiano. NaN -> zeros."""
    valores = np.asarray(valores, dtype=np.float32)[:, None]
    ativacao = np.exp(-((valores - centros[None, :]) ** 2) / (2 * sigma ** 2))
    return np.nan_to_num(ativacao, nan=0.0)


def _attributes_block(df):
    tipo = np.stack([(df['kind'] == k).to_numpy(np.float32) for k in KINDS], axis=1)
    ano = _rbf(df['year'].astype('float32'), YEAR_CENTERS, YEAR_SIGMA)
    # Sem votos, a nota não significa nada: fica fora (zeros).
    nota = pd.Series(df['vote_average'], dtype='float32').where(df['vote_count'] > 0)
    nota = _rbf(nota, RATING_CENTERS, RATING_SIGMA)

    grupos = []
    for nome, grupo in [('kind', tipo), ('year', ano), ('rating', nota)]:
        grupos.append(normalize(grupo, norm='l2', axis=1) * np.sqrt(ATTRIBUTE_WEIGHTS[nome]))
    return sparse.csr_matrix(np.hstack(grupos).astype(np.float32))
