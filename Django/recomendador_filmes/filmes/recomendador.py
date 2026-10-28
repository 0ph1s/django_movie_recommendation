# filmes/recomendador.py
import difflib
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

CAMINHO_DATASET = Path(__file__).resolve().parent / 'movies.csv'
RECURSOS_SELECIONADOS = ['genres', 'keywords', 'tagline', 'cast', 'director']


@lru_cache(maxsize=1)
def carregar_dados():
    """Carrega o dataset e calcula os vetores TF-IDF uma única vez por processo."""
    df = pd.read_csv(CAMINHO_DATASET)
    df[RECURSOS_SELECIONADOS] = df[RECURSOS_SELECIONADOS].fillna('')
    df['release_date'] = df['release_date'].fillna('')
    recursos_combinados = df[RECURSOS_SELECIONADOS].agg(' '.join, axis=1)

    # O TfidfVectorizer já normaliza os vetores (norma L2), então o produto
    # escalar (linear_kernel) é igual à similaridade de cosseno.
    vetores = TfidfVectorizer().fit_transform(recursos_combinados)
    titulos_minusculos = df['title'].str.lower()
    return df, vetores, titulos_minusculos


def encontrar_filme(filme_requerido):
    """Retorna o índice do filme com título mais próximo, ou None se não houver."""
    df, _, titulos_minusculos = carregar_dados()
    encontrados = difflib.get_close_matches(
        filme_requerido.strip().lower(), titulos_minusculos.unique(), n=1
    )
    if not encontrados:
        return None

    # Títulos repetidos (ex.: "Batman" de 1966 e de 1989): usa o mais popular.
    candidatos = df[titulos_minusculos == encontrados[0]]
    return candidatos['popularity'].idxmax()


def recomendar(filme_requerido, quantidade):
    """Retorna (filme_encontrado, recomendacoes), ou (None, []) se o filme não existir."""
    df, vetores, _ = carregar_dados()
    indice_do_filme = encontrar_filme(filme_requerido)
    if indice_do_filme is None:
        return None, []

    pontuacao_similaridade = linear_kernel(vetores[indice_do_filme], vetores).ravel()
    titulo_do_filme = df.loc[indice_do_filme, 'title']

    recomendacoes = []
    for indice in pontuacao_similaridade.argsort()[::-1]:
        if len(recomendacoes) == quantidade:
            break
        if indice == indice_do_filme or df.loc[indice, 'title'] == titulo_do_filme:
            continue
        recomendacoes.append(_descrever(df, indice))

    return _descrever(df, indice_do_filme), recomendacoes


def _descrever(df, indice):
    return {
        'titulo': df.loc[indice, 'title'],
        'ano': df.loc[indice, 'release_date'][:4],
    }
