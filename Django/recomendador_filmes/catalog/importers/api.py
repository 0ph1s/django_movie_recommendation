# catalog/importers/api.py
"""
Catálogo direto das APIs, em vez dos CSVs estáticos: usado por `manage.py sync_catalog`.

  Filmes e séries  API do TMDB. A "descoberta" lista os mais votados (os clássicos que as
                   pessoas procuram) e os lançamentos recentes mais populares; a página de
                   cada título traz sinopse, elenco, direção e palavras-chave, os mesmos
                   campos que os CSVs do TMDB davam.
  Animes           API GraphQL da AniList, 50 por requisição, ordenados por popularidade; só os
                   que já estrearam (em exibição ou encerrados), não os anunciados.
                   O título continua identificado pelo ID do MyAnimeList (`idMal`), o mesmo
                   dos CSVs: animes já avaliados pelos usuários são atualizados, não duplicados.

As listas da descoberta já trazem nota, votos e popularidade. Por isso só os títulos novos
pedem a página de detalhes; os que já estão no banco têm apenas esses números atualizados
(a menos que `full=True`).

Textos em inglês (en-US): o índice usa stop words do inglês e o resto do catálogo também está
em inglês. Conteúdo adulto fica de fora nas duas fontes.
"""
import re
from datetime import date, timedelta
from urllib.parse import urlencode

from ..posters import ANILIST_API, TMDB_API, RateLimiter, request_json
from .base import ADULT_GENRES, NormalizedTitle, canonical_genres, clean_text, parse_year
from .tmdb import MAX_CAST, POSTER_BASE_URL

LANGUAGE = 'en-US'
TMDB_PAGE_SIZE = 20
TMDB_MAX_PAGES = 500           # limite da API para a descoberta
ANILIST_PAGE_SIZE = 50
# Na AniList, formatos de "obra seriada". Filmes de anime já vêm pelo TMDB (como filmes).
ANIME_FORMATS = ['TV', 'TV_SHORT', 'ONA', 'OVA']
# Tags da AniList (temas: "Time Travel", "Isekai"...) com relevância mínima para virar palavra-chave.
ANIME_TAG_MIN_RANK = 60
ANIME_MAX_TAGS = 8
TMDB_ANIMATION = 16
_HTML = re.compile(r'<[^>]+>')
_SOURCE_NOTE = re.compile(r'\((?:Source|Fonte):[^)]*\)\s*$', re.IGNORECASE)


# ------------------------------------------------------------------ TMDB

class TmdbCatalog:
    """Descoberta e detalhes de filmes e séries no TMDB."""

    # O limite do TMDB fica em torno de 50 req/s; 30 deixa folga (mesmo valor das capas).
    def __init__(self, credencial, por_segundo=30):
        credencial = credencial.strip()
        if credencial.startswith('eyJ'):      # token v4 (JWT)
            self.headers, self.auth = {'Authorization': f'Bearer {credencial}'}, {}
        else:                                 # chave v3
            self.headers, self.auth = {}, {'api_key': credencial}
        self.limiter = RateLimiter(por_segundo)

    def _get(self, caminho, **params):
        consulta = urlencode({**self.auth, 'language': LANGUAGE, **params})
        return request_json(f'{TMDB_API}{caminho}?{consulta}', headers=self.headers,
                            limiter=self.limiter, origem='TMDB')

    def discover(self, kind, limite, *, desde=None, min_votes=0, sort='vote_count.desc'):
        """Até `limite` itens da descoberta (a linha resumida, já com nota e votos)."""
        recurso = 'movie' if kind == 'movie' else 'tv'
        campo = 'primary_release_date' if kind == 'movie' else 'first_air_date'
        # Só o que já estreou: anúncios e títulos ainda sem data não entram.
        params = {'sort_by': sort, 'include_adult': 'false', 'vote_count.gte': min_votes,
                  f'{campo}.lte': date.today().isoformat()}
        if desde:
            params[f'{campo}.gte'] = desde.isoformat()
        itens = []
        for pagina in range(1, TMDB_MAX_PAGES + 1):
            dados = self._get(f'/discover/{recurso}', page=pagina, **params) or {}
            resultados = dados.get('results') or []
            itens.extend(r for r in resultados if _keep_tmdb(kind, r))
            if len(itens) >= limite or pagina >= (dados.get('total_pages') or 0) or not resultados:
                break
        return itens[:limite]

    def details(self, kind, external_id):
        if kind == 'movie':
            return self._get(f'/movie/{external_id}', append_to_response='credits,keywords')
        return self._get(f'/tv/{external_id}', append_to_response='aggregate_credits,keywords')


def _keep_tmdb(kind, linha):
    if linha.get('adult'):
        return False
    # Animação japonesa em série é anime: vem da AniList, com os dados certos (estúdio, temas).
    if kind == 'series' and TMDB_ANIMATION in (linha.get('genre_ids') or []) and linha.get('original_language') == 'ja':
        return False
    return True


def tmdb_stats(kind, linha):
    """Números que mudam com o tempo, direto da linha da descoberta."""
    return {
        'vote_average': float(linha.get('vote_average') or 0),
        'vote_count': int(linha.get('vote_count') or 0),
        'popularity': float(linha.get('popularity') or 0),
        'poster_url': f'{POSTER_BASE_URL}{linha["poster_path"]}' if linha.get('poster_path') else '',
    }


def normalize_tmdb(kind, dados):
    """Página de detalhes do TMDB -> NormalizedTitle (ou None, se não servir)."""
    if not dados or dados.get('adult'):
        return None
    if kind == 'movie':
        titulo, original, lancamento = dados.get('title'), dados.get('original_title'), dados.get('release_date')
        creditos = dados.get('credits') or {}
        palavras = [k.get('name', '') for k in (dados.get('keywords') or {}).get('keywords', [])]
        elenco = [p.get('name', '') for p in (creditos.get('cast') or [])[:MAX_CAST]]
        autoria = [p.get('name', '') for p in creditos.get('crew') or [] if p.get('job') == 'Director'][:2]
        duracao, episodios = dados.get('runtime'), None
    else:
        titulo, original, lancamento = dados.get('name'), dados.get('original_name'), dados.get('first_air_date')
        creditos = dados.get('aggregate_credits') or {}
        palavras = [k.get('name', '') for k in (dados.get('keywords') or {}).get('results', [])]
        # A emissora ("HBO") funciona como palavra-chave; do formato, só "Miniseries" diz algo.
        palavras += [n.get('name', '') for n in dados.get('networks') or []]
        if (dados.get('type') or '').lower() == 'miniseries':
            palavras.append('Miniseries')
        elenco = [p.get('name', '') for p in (creditos.get('cast') or [])[:MAX_CAST]]
        autoria = [p.get('name', '') for p in dados.get('created_by') or []][:3]
        duracoes = dados.get('episode_run_time') or []
        duracao, episodios = (duracoes[0] if duracoes else None), dados.get('number_of_episodes')

    titulo = clean_text(titulo)
    if not titulo:
        return None
    return NormalizedTitle(
        kind=kind,
        source='tmdb',
        external_id=str(dados['id']),
        title=titulo,
        original_title=clean_text(original) if clean_text(original) != titulo else '',
        overview=clean_text(dados.get('overview')),
        tagline=clean_text(dados.get('tagline'), max_length=400),
        keywords=' '.join(clean_text(p) for p in palavras if clean_text(p)),
        cast=', '.join(clean_text(n) for n in elenco if clean_text(n)),
        director=clean_text(', '.join(autoria), max_length=255),
        genres=canonical_genres([g.get('name', '') for g in dados.get('genres') or []]),
        year=parse_year(lancamento),
        runtime=int(duracao) if duracao else None,
        episodes=int(episodios) if episodios else None,
        **tmdb_stats(kind, dados),
    )


# ------------------------------------------------------------------ AniList

_ANILIST_QUERY = """
query ($page: Int, $perPage: Int, $formats: [MediaFormat], $since: FuzzyDateInt) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    media(type: ANIME, isAdult: false, sort: POPULARITY_DESC, format_in: $formats,
          status_in: [RELEASING, FINISHED], startDate_greater: $since) {
      idMal
      title { english romaji }
      description(asHtml: false)
      format
      source
      genres
      tags { name rank isAdult isMediaSpoiler isGeneralSpoiler }
      studios(isMain: true) { nodes { name } }
      episodes
      duration
      averageScore
      meanScore
      popularity
      startDate { year }
      coverImage { extraLarge large }
      stats { scoreDistribution { amount } }
    }
  }
}
"""


class AniListCatalog:
    # O limite publicado é de 90 req/min (às vezes reduzido para 30); 25/min é seguro.
    def __init__(self, por_minuto=25):
        self.limiter = RateLimiter(por_minuto / 60)

    def popular(self, limite, *, desde=None):
        """Até `limite` animes, do mais popular ao menos, já normalizados."""
        registros, pagina = [], 1
        while len(registros) < limite:
            variaveis = {'page': pagina, 'perPage': ANILIST_PAGE_SIZE, 'formats': ANIME_FORMATS}
            if desde:
                variaveis['since'] = int(desde.strftime('%Y%m%d'))
            dados = request_json(ANILIST_API, body={'query': _ANILIST_QUERY, 'variables': variaveis},
                                 limiter=self.limiter, origem='AniList') or {}
            pagina_dados = (dados.get('data') or {}).get('Page') or {}
            for midia in pagina_dados.get('media') or []:
                registro = normalize_anilist(midia)
                if registro:
                    registros.append(registro)
            if not (pagina_dados.get('pageInfo') or {}).get('hasNextPage'):
                break
            pagina += 1
        return registros[:limite]


def _anilist_text(texto):
    texto = _HTML.sub(' ', texto or '')
    return clean_text(_SOURCE_NOTE.sub('', clean_text(texto)))


def normalize_anilist(midia):
    """Item da AniList -> NormalizedTitle. Sem ID do MyAnimeList, fica de fora (é a chave)."""
    if not midia or not midia.get('idMal'):
        return None
    generos = midia.get('genres') or []
    if ADULT_GENRES & {g.lower() for g in generos}:
        return None
    titulos = midia.get('title') or {}
    ingles, romaji = clean_text(titulos.get('english')), clean_text(titulos.get('romaji'))
    titulo = ingles or romaji
    if not titulo:
        return None

    # A obra de origem (mangá, light novel...) e os temas mais fortes viram palavras-chave.
    origem = (midia.get('source') or '').replace('_', ' ').title()
    origem = '' if origem.lower() in {'original', 'other'} else origem
    temas = [
        t['name'] for t in sorted(midia.get('tags') or [], key=lambda t: -(t.get('rank') or 0))
        if (t.get('rank') or 0) >= ANIME_TAG_MIN_RANK and not t.get('isAdult')
        and not t.get('isMediaSpoiler') and not t.get('isGeneralSpoiler')
    ][:ANIME_MAX_TAGS]
    estudios = [s.get('name', '') for s in ((midia.get('studios') or {}).get('nodes') or [])][:3]
    nota = midia.get('averageScore') or midia.get('meanScore') or 0
    votos = sum(d.get('amount') or 0 for d in ((midia.get('stats') or {}).get('scoreDistribution') or []))
    capa = midia.get('coverImage') or {}

    return NormalizedTitle(
        kind='anime',
        source='mal',
        external_id=str(midia['idMal']),
        title=titulo,
        original_title=romaji if ingles and romaji != ingles else '',
        overview=_anilist_text(midia.get('description')),
        keywords=' '.join(filter(None, [origem, *temas])),
        director=clean_text(', '.join(estudios), max_length=255),
        # A AniList não rotula "Animation"; aqui ele liga animes a filmes animados.
        genres=canonical_genres(['Animation', *generos]),
        year=(midia.get('startDate') or {}).get('year'),
        runtime=midia.get('duration') or None,
        episodes=midia.get('episodes') or None,
        vote_average=nota / 10,
        vote_count=votos,
        popularity=float(midia.get('popularity') or 0),
        poster_url=capa.get('extraLarge') or capa.get('large') or '',
    )


def recent_since(dias):
    return date.today() - timedelta(days=dias) if dias else None
