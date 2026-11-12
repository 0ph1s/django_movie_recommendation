# recommender/profile.py
"""
Perfil dinâmico do usuário: um vetor no mesmo espaço dos títulos.

É uma variação do algoritmo de Rocchio, com decaimento por recência:

    perfil = média_ponderada(positivos) − γ · média_ponderada(negativos)
    peso da interação i = |valor_i| · 0,5 ^ (idade_i / meia_vida)

onde idade 0 é a interação mais recente e o valor vem do estado do título: favorito pesa
2 (`favorite_weight`), curti 1 e não curti −1. "Já vi" e "quero assistir" têm valor 0: não
entram no vetor nem na contagem de idade, só saem das recomendações. Como o perfil vive no espaço dos títulos, a
recomendação é só mais uma similaridade do cosseno: score = X · perfil / ‖perfil‖.
Cada nova interação muda o vetor na hora; não há treino.
"""
from dataclasses import dataclass

import numpy as np

LIKE = 1
DISLIKE = -1


@dataclass(frozen=True)
class Signal:
    title_id: int
    value: float  # > 0 aproxima (curti = 1, favorito = 2), < 0 afasta, 0 não entra no vetor


def recency_weights(n, half_life):
    """Pesos para n interações em ordem cronológica (a última é a mais recente)."""
    idades = np.arange(n - 1, -1, -1, dtype=np.float32)
    return np.power(np.float32(0.5), idades / np.float32(max(half_life, 1e-6)))


def build_profile(index, sinais, half_life, dislike_weight):
    """Devolve o vetor de perfil (1 x d, norma 1) ou None se não houver nenhum positivo no catálogo."""
    # Só os sinais com peso contam a idade: um "já vi" recente não envelhece os curtidos.
    validos = [s for s in sinais if s.title_id in index.row_of and s.value != 0]
    if not any(s.value > 0 for s in validos):
        return None

    linhas = np.array([index.row_of[s.title_id] for s in validos])
    valores = np.array([s.value for s in validos], dtype=np.float32)
    pesos = recency_weights(len(validos), half_life) * np.abs(valores)
    positivos, negativos = valores > 0, valores < 0

    perfil = _weighted_mean(index.matrix, linhas[positivos], pesos[positivos])
    if negativos.any():
        perfil = perfil - dislike_weight * _weighted_mean(
            index.matrix, linhas[negativos], pesos[negativos]
        )

    norma = np.linalg.norm(perfil)
    return (perfil / norma).astype(np.float32) if norma > 0 else None


def _weighted_mean(matriz, linhas, pesos):
    pesos = pesos / pesos.sum()
    return np.asarray(matriz[linhas].T @ pesos).ravel()
