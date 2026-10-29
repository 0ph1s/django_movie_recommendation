# catalog/posters.py
"""
Busca das capas (pôsteres) em APIs públicas, usada por `manage.py fetch_posters`.

  Filmes e séries  API do TMDB. O `external_id` dos títulos do TMDB já é o ID da API.
                   Exige chave gratuita (settings.TMDB_API_KEY): a chave v3 ou o token v4.
  Animes           API GraphQL da AniList, que aceita o ID do MyAnimeList (`idMal`) e
                   devolve até 50 títulos por requisição. Não exige chave.

Só usa a biblioteca padrão (urllib), para não acrescentar dependências.
"""
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TMDB_API = 'https://api.themoviedb.org/3'
TMDB_IMAGES = 'https://image.tmdb.org/t/p/w500'
ANILIST_API = 'https://graphql.anilist.co'
ANILIST_BATCH = 50
USER_AGENT = 'Angulo/1.0 (recomendador Django)'
TIMEOUT = 20
RETRIES = 4

_ANILIST_QUERY = """
query ($ids: [Int], $perPage: Int) {
  Page(perPage: $perPage) {
    media(idMal_in: $ids, type: ANIME) {
      idMal
      coverImage { extraLarge large }
    }
  }
}
"""


class PosterSourceError(Exception):
    """Falha que não adianta repetir (ex.: chave recusada): interrompe a busca."""


class RateLimiter:
    """Garante um intervalo mínimo entre requisições, mesmo com várias threads."""

    def __init__(self, por_segundo):
        self.intervalo = 1 / por_segundo
        self.proxima = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            agora = time.monotonic()
            espera = self.proxima - agora
            self.proxima = max(agora, self.proxima) + self.intervalo
        if espera > 0:
            time.sleep(espera)


def request_json(url, *, headers=None, body=None, limiter=None, origem='API'):
    """GET (ou POST, com `body`) que devolve o JSON da resposta, ou None em 404.

    Repete com espera crescente em 429, erros 5xx e falhas de rede; respeita Retry-After.
    """
    cabecalhos = {'Accept': 'application/json', 'User-Agent': USER_AGENT, **(headers or {})}
    dados = None
    if body is not None:
        dados = json.dumps(body).encode()
        cabecalhos['Content-Type'] = 'application/json'

    for tentativa in range(RETRIES):
        if limiter:
            limiter.wait()
        try:
            with urlopen(Request(url, data=dados, headers=cabecalhos), timeout=TIMEOUT) as resposta:
                return json.load(resposta)
        except HTTPError as erro:
            if erro.code == 404:
                return None
            if erro.code in (401, 403):
                raise PosterSourceError(f'{origem} recusou a autenticação (HTTP {erro.code}).') from erro
            if erro.code != 429 and erro.code < 500:
                raise
            espera = float(erro.headers.get('Retry-After') or 2 ** tentativa)
        except (URLError, TimeoutError):
            espera = 2 ** tentativa
        time.sleep(min(espera, 60))
    raise PosterSourceError(f'{origem} não respondeu depois de {RETRIES} tentativas.')


class TmdbClient:
    # O limite do TMDB fica em torno de 50 req/s; 30 deixa folga.
    def __init__(self, credencial, por_segundo=30):
        credencial = credencial.strip()
        # Tokens v4 ("API Read Access Token") são JWTs; chaves v3 são hexadecimais curtas.
        if credencial.startswith('eyJ'):
            self.headers, self.params = {'Authorization': f'Bearer {credencial}'}, {}
        else:
            self.headers, self.params = {}, {'api_key': credencial}
        self.limiter = RateLimiter(por_segundo)

    def poster_url(self, kind, external_id):
        recurso = 'movie' if kind == 'movie' else 'tv'
        url = f'{TMDB_API}/{recurso}/{external_id}'
        if self.params:
            url += f'?{urlencode(self.params)}'
        dados = request_json(url, headers=self.headers, limiter=self.limiter, origem='TMDB')
        caminho = (dados or {}).get('poster_path')
        return f'{TMDB_IMAGES}{caminho}' if caminho else ''


class AniListClient:
    # O limite publicado é de 90 req/min (às vezes reduzido para 30); 25/min é seguro.
    def __init__(self, por_minuto=25):
        self.limiter = RateLimiter(por_minuto / 60)

    def poster_urls(self, mal_ids):
        """{id do MAL: url da capa} para um lote de até 50 IDs."""
        ids = [int(i) for i in mal_ids]
        corpo = {'query': _ANILIST_QUERY, 'variables': {'ids': ids, 'perPage': len(ids)}}
        dados = request_json(ANILIST_API, body=corpo, limiter=self.limiter, origem='AniList')
        capas = {}
        for midia in (dados or {}).get('data', {}).get('Page', {}).get('media', []):
            imagem = midia.get('coverImage') or {}
            url = imagem.get('extraLarge') or imagem.get('large') or ''
            if midia.get('idMal') and url:
                capas[str(midia['idMal'])] = url
        return capas
