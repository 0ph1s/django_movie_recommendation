# recommender/config.py
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True)
class RecommenderConfig:
    """Parâmetros do recomendador. Sobrescreva qualquer um em settings.RECOMMENDER."""

    # Peso de cada bloco de features na similaridade do cosseno. São normalizados para
    # somar 1, e então cos(a, b) = Σ peso_bloco · cos_bloco(a, b).
    weight_synopsis: float = 0.35     # TF-IDF da sinopse + tagline
    weight_tags: float = 0.45         # gêneros, palavras-chave, elenco e direção/estúdio
    weight_attributes: float = 0.20   # época, faixa de nota e tipo (filme/série/anime)

    # Quantas vezes cada gênero se repete no bloco de tags (reforça o gênero frente às palavras-chave).
    genre_boost: int = 3
    max_synopsis_features: int = 20_000

    # Rating bayesiano: m = este quantil da contagem de votos dentro de cada tipo.
    vote_quantile: float = 0.70

    # Padrões do filtro híbrido (todos ajustáveis por requisição).
    alpha: float = 0.75          # 1 = só similaridade; 0 = só qualidade
    rating_weight: float = 0.65  # dentro da qualidade: nota bayesiana vs. popularidade
    obscurity: float = 0.25      # oculta títulos abaixo deste percentil de votos no seu tipo
    diversity: float = 0.15      # peso do MMR (0 = sem diversificação)
    candidate_pool: int = 250    # candidatos por similaridade antes do re-ranqueamento

    # Perfil dinâmico do usuário (Rocchio com decaimento por recência).
    dislike_weight: float = 0.5  # o quanto os "não curti" afastam o perfil
    recency_half_life: float = 6  # a cada N interações mais antigas, o peso cai pela metade

    index_path: Path = Path('var/recommender_index.joblib')
    # Segundos em que o índice em memória é usado sem conferir no banco se o catálogo mudou.
    # 0 confere a cada consulta (desenvolvimento e testes).
    fingerprint_ttl: float = 0

    @property
    def block_weights(self):
        pesos = {
            'synopsis': self.weight_synopsis,
            'tags': self.weight_tags,
            'attributes': self.weight_attributes,
        }
        total = sum(pesos.values())
        return {bloco: peso / total for bloco, peso in pesos.items()}

    @property
    def feature_hash(self):
        """Muda quando um parâmetro que afeta a matriz de features muda (invalida o índice salvo)."""
        relevantes = {
            chave: valor for chave, valor in asdict(self).items()
            if chave.startswith('weight_') or chave in {'genre_boost', 'max_synopsis_features', 'vote_quantile'}
        }
        return sha1(repr(sorted(relevantes.items())).encode()).hexdigest()[:12]


@lru_cache(maxsize=1)
def get_config():
    nomes = {f.name for f in fields(RecommenderConfig)}
    sobrescritas = {
        chave.lower(): valor
        for chave, valor in getattr(settings, 'RECOMMENDER', {}).items()
        if chave.lower() in nomes
    }
    if 'index_path' in sobrescritas:
        sobrescritas['index_path'] = Path(sobrescritas['index_path'])
    return RecommenderConfig(**sobrescritas)
