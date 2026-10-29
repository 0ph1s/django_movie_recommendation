# recommender/quality.py
"""
Sinais de qualidade usados pelo filtro híbrido para não recomendar títulos obscuros
ou mal avaliados só porque são parecidos.

Tudo é calculado dentro de cada tipo (filme, série, anime): as fontes têm escalas de
votos muito diferentes (milhares no TMDB, centenas de milhares no MyAnimeList), então
comparar percentis dentro do tipo é o que torna os números comparáveis entre si.
"""
import numpy as np
import pandas as pd


def bayesian_rating(nota, votos, m, c):
    """Média ponderada do IMDb: puxa notas com poucos votos para a média global c.

        WR = v/(v+m) · R + m/(v+m) · C
    """
    nota = np.asarray(nota, dtype=np.float64)
    votos = np.asarray(votos, dtype=np.float64)
    if m <= 0:
        return nota
    return (votos / (votos + m)) * nota + (m / (votos + m)) * c


def quality_signals(df, vote_quantile):
    """Devolve três arrays em [0, 1], alinhados com as linhas de df:

    rating      percentil da nota bayesiana no tipo
    popularity  percentil da popularidade no tipo
    votes       percentil da contagem de votos no tipo (usado como corte de obscuridade)
    """
    rating = np.zeros(len(df), dtype=np.float32)
    popularity = np.zeros(len(df), dtype=np.float32)
    votes = np.zeros(len(df), dtype=np.float32)

    for _, grupo in df.groupby('kind', sort=False):
        posicoes = df.index.get_indexer(grupo.index)
        avaliados = grupo['vote_count'] > 0
        c = grupo.loc[avaliados, 'vote_average'].mean() if avaliados.any() else 0.0
        m = grupo['vote_count'].quantile(vote_quantile)
        wr = pd.Series(bayesian_rating(grupo['vote_average'], grupo['vote_count'], m, c), index=grupo.index)
        # Título sem nenhum voto não tem nota: vai para o fim do ranking.
        wr[~avaliados] = -1

        rating[posicoes] = _percentile(wr)
        popularity[posicoes] = _percentile(grupo['popularity'])
        votes[posicoes] = _percentile(grupo['vote_count'])
    return rating, popularity, votes


def _percentile(serie):
    """Posição relativa em [0, 1]; empates recebem a média das posições."""
    if len(serie) == 1:
        return np.ones(1, dtype=np.float32)
    return ((serie.rank(method='average') - 1) / (len(serie) - 1)).to_numpy(np.float32)
