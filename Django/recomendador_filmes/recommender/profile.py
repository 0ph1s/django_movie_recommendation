# recommender/profile.py
"""
Perfil dinâmico do usuário: um vetor no mesmo espaço dos títulos.

É uma variação do algoritmo de Rocchio, com decaimento por recência:

    perfil = média_ponderada(curtidos) − γ · média_ponderada(não curtidos)
    peso da interação i = 0,5 ^ (idade_i / meia_vida)

onde idade 0 é a interação mais recente. Como o perfil vive no espaço dos títulos, a
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
    value: int  # LIKE ou DISLIKE


def recency_weights(n, half_life):
    """Pesos para n interações em ordem cronológica (a última é a mais recente)."""
    idades = np.arange(n - 1, -1, -1, dtype=np.float32)
    return np.power(np.float32(0.5), idades / np.float32(max(half_life, 1e-6)))


def build_profile(index, sinais, half_life, dislike_weight):
    """Devolve o vetor de perfil (1 x d, norma 1) ou None se não houver nenhum "curti" no catálogo."""
    validos = [s for s in sinais if s.title_id in index.row_of]
    if not any(s.value == LIKE for s in validos):
        return None

    pesos = recency_weights(len(validos), half_life)
    linhas = np.array([index.row_of[s.title_id] for s in validos])
    valores = np.array([s.value for s in validos])

    perfil = _weighted_mean(index.matrix, linhas[valores == LIKE], pesos[valores == LIKE])
    if (valores == DISLIKE).any():
        perfil = perfil - dislike_weight * _weighted_mean(
            index.matrix, linhas[valores == DISLIKE], pesos[valores == DISLIKE]
        )

    norma = np.linalg.norm(perfil)
    return (perfil / norma).astype(np.float32) if norma > 0 else None


def _weighted_mean(matriz, linhas, pesos):
    pesos = pesos / pesos.sum()
    return np.asarray(matriz[linhas].T @ pesos).ravel()
