"""
Mapa do gosto: o catálogo projetado em 2D.

O espaço de features tem dezenas de milhares de dimensões (esparso). A projeção tem duas
etapas: TruncatedSVD para ~50 dimensões densas (o "LSA" do TF-IDF) e t-SNE para 2. O t-SNE
preserva vizinhanças: títulos próximos no cosseno ficam próximos no mapa.

É cara (dezenas de segundos para 5 mil títulos), então roda só nos comandos locais
(`build_index`, `import_dataset`) e as coordenadas vão para o banco (`Title.map_x/map_y`).
O t-SNE não projeta pontos novos: o "centro" de um perfil é a média dos títulos mais
próximos dele (ver recommender.insights).
"""
import numpy as np

from catalog.models import Title

SVD_COMPONENTS = 50
PERPLEXITY = 30
SEED = 42


def compute_projection(indice, seed=SEED):
    """Coordenadas (N × 2) alinhadas com `indice.ids`, centradas e escaladas para [-1, 1]."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.manifold import TSNE

    n = indice.size
    if n < 3:
        return np.zeros((n, 2), dtype=np.float32)
    componentes = max(2, min(SVD_COMPONENTS, indice.dimensions - 1, n - 1))
    with np.errstate(invalid='ignore', divide='ignore'):
        denso = TruncatedSVD(n_components=componentes, random_state=seed).fit_transform(indice.matrix)
    denso = np.nan_to_num(denso)
    # Catálogo degenerado (títulos praticamente iguais): sem variância, o t-SNE não tem o que
    # separar e a árvore de Barnes-Hut estoura a pilha. Todos ficam no centro.
    if float(denso.std(axis=0).max()) < 1e-9:
        return np.zeros((n, 2), dtype=np.float32)
    # A perplexidade precisa ser menor que o número de pontos (catálogos pequenos, testes);
    # abaixo de algumas centenas, o método exato é rápido e mais estável que o Barnes-Hut.
    perplexidade = min(PERPLEXITY, max(1.0, (n - 1) / 3))
    coords = TSNE(
        n_components=2,
        perplexity=perplexidade,
        init='pca',
        learning_rate='auto',
        metric='cosine',
        method='exact' if n < 300 else 'barnes_hut',
        random_state=seed,
    ).fit_transform(denso)
    coords -= coords.mean(axis=0)
    coords /= np.abs(coords).max() or 1.0
    return coords.astype(np.float32)


def save_projection(indice, coords):
    """Grava as coordenadas. `bulk_update` não toca `updated_at`, então o índice não é invalidado."""
    posicoes = {int(i): (float(x), float(y)) for i, (x, y) in zip(indice.ids, coords)}
    titulos = list(Title.objects.filter(pk__in=posicoes).only('id'))
    for titulo in titulos:
        titulo.map_x, titulo.map_y = (round(v, 5) for v in posicoes[titulo.pk])
    Title.objects.bulk_update(titulos, ['map_x', 'map_y'], batch_size=500)
    from .insights import invalidate_catalog_meta

    invalidate_catalog_meta()
    return len(titulos)


def build_map(indice):
    """Calcula e grava. Devolve quantos títulos ganharam coordenadas."""
    return save_projection(indice, compute_projection(indice))
