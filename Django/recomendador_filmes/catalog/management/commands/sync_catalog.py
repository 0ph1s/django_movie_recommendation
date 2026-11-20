# catalog/management/commands/sync_catalog.py
"""
Amplia e atualiza o catálogo direto das APIs do TMDB (filmes e séries) e da AniList (animes).

Exemplos:
    python manage.py sync_catalog                         # padrão: 8000 filmes, 3000 séries, 3000 animes
    python manage.py sync_catalog --movies 500 --series 0 --anime 0 --no-map
    python manage.py sync_catalog --kinds anime           # só animes (não precisa de chave)
    python manage.py sync_catalog --full                  # rebaixa os detalhes de todos, não só dos novos

O que entra:
  * os mais votados de cada tipo (os clássicos que as pessoas procuram);
  * os lançamentos dos últimos `--recent-days` dias, pelos mais populares, desde que tenham
    um mínimo de votos (`--recent-min-votes`), para não trazer título sem avaliação nenhuma.

Títulos que já estão no banco (inclusive os dos CSVs antigos) são reconhecidos pelo ID na
fonte: ganham nota, votos, popularidade e capa novos, e o histórico dos usuários continua
apontando para eles. Nada é apagado. Pode ser interrompido: o que já veio é gravado em lotes.

Filmes e séries exigem TMDB_API_KEY (chave v3 ou token v4). A AniList não pede chave.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.api import AniListCatalog, TmdbCatalog, normalize_tmdb, recent_since, tmdb_stats
from catalog.importers.loader import BATCH_SIZE, refresh_popularity_ranks, save_records
from catalog.models import Title
from catalog.posters import PosterSourceError

SAVE_EVERY = 200
# updated_at entra junto: é ele que muda o fingerprint do catálogo, e o índice (que usa nota e
# votos) precisa ser refeito quando esses números mudam.
STATS_FIELDS = ['vote_average', 'vote_count', 'popularity', 'updated_at']


class Command(BaseCommand):
    help = 'Amplia e atualiza o catálogo pelas APIs do TMDB (filmes e séries) e da AniList (animes).'

    def add_arguments(self, parser):
        parser.add_argument('--kinds', default='movie,series,anime',
                            help='Tipos separados por vírgula (padrão: movie,series,anime).')
        parser.add_argument('--movies', type=int, default=8000, help='Filmes mais votados (padrão: 8000).')
        parser.add_argument('--series', type=int, default=3000, help='Séries mais votadas (padrão: 3000).')
        parser.add_argument('--anime', type=int, default=3000, help='Animes mais populares (padrão: 3000).')
        parser.add_argument('--recent-days', type=int, default=365,
                            help='Janela de lançamentos, em dias (padrão: 365; 0 desliga).')
        parser.add_argument('--recent', type=int, default=1000,
                            help='Lançamentos por tipo, os mais populares (padrão: 1000).')
        parser.add_argument('--recent-min-votes', type=int, default=20,
                            help='Votos mínimos de um lançamento do TMDB (padrão: 20).')
        parser.add_argument('--full', action='store_true',
                            help='Busca os detalhes de todos, inclusive dos que já estão no banco.')
        parser.add_argument('--workers', type=int, default=8, help='Requisições simultâneas ao TMDB.')
        parser.add_argument('--no-index', action='store_true', help='Não reconstrói o índice de recomendação.')
        parser.add_argument('--no-map', action='store_true', help='Reconstrói o índice, mas não projeta o mapa.')

    def handle(self, *args, **opcoes):
        tipos = [k.strip() for k in opcoes['kinds'].split(',') if k.strip()]
        invalidos = set(tipos) - set(Title.Kind.values)
        if invalidos:
            raise CommandError(f'Tipo desconhecido: {", ".join(sorted(invalidos))}.')
        tmdb_tipos = [k for k in tipos if k in ('movie', 'series')]
        if tmdb_tipos and not settings.TMDB_API_KEY:
            raise CommandError('Filmes e séries precisam de TMDB_API_KEY. Para só animes: --kinds anime.')

        self.opcoes = opcoes
        self.desde = recent_since(opcoes['recent_days'])
        antes = Title.objects.count()
        inicio = time.perf_counter()
        try:
            for kind in tmdb_tipos:
                self._tmdb(kind)
            if 'anime' in tipos:
                self._anime()
        except PosterSourceError as erro:
            raise CommandError(f'{erro} O que já tinha vindo foi gravado.') from erro
        finally:
            refresh_popularity_ranks()

        depois = Title.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'Catálogo: {antes} → {depois} títulos (+{depois - antes}) em {time.perf_counter() - inicio:.0f}s'
        ))
        if not opcoes['no_index']:
            self._index()

    # -------------------------------------------------------------- TMDB

    def _tmdb(self, kind):
        quantos = self.opcoes['movies' if kind == 'movie' else 'series']
        rotulo = 'Filmes' if kind == 'movie' else 'Séries'
        cliente = TmdbCatalog(settings.TMDB_API_KEY)

        linhas = {}
        if quantos:
            for linha in cliente.discover(kind, quantos):
                linhas[str(linha['id'])] = linha
        if self.desde and self.opcoes['recent']:
            for linha in cliente.discover(kind, self.opcoes['recent'], desde=self.desde,
                                          min_votes=self.opcoes['recent_min_votes'], sort='popularity.desc'):
                linhas.setdefault(str(linha['id']), linha)
        if not linhas:
            return

        no_banco = dict(Title.objects.filter(source='tmdb', kind=kind, external_id__in=linhas)
                        .values_list('external_id', 'pk'))
        novos = list(linhas) if self.opcoes['full'] else [i for i in linhas if i not in no_banco]
        atualizados = self._update_stats(kind, linhas, no_banco, ignorar=set(novos))
        self.stdout.write(f'{rotulo}: {len(linhas)} na descoberta, {len(novos)} para detalhar, '
                          f'{atualizados} só com números novos.')

        gravados, lote = 0, []
        with ThreadPoolExecutor(max_workers=self.opcoes['workers']) as fila:
            futuros = [fila.submit(cliente.details, kind, i) for i in novos]
            for feito, futuro in enumerate(as_completed(futuros), 1):
                registro = normalize_tmdb(kind, futuro.result())
                if registro:
                    lote.append(registro)
                if len(lote) >= SAVE_EVERY:
                    gravados += save_records(lote)
                    lote = []
                    self.stdout.write(f'  {feito}/{len(novos)}')
        gravados += save_records(lote)
        self.stdout.write(self.style.SUCCESS(f'{rotulo}: {gravados} gravados com detalhes.'))

    def _update_stats(self, kind, linhas, no_banco, ignorar):
        """Nota, votos, popularidade e capa dos que já existem, direto da descoberta."""
        titulos, agora = [], timezone.now()
        for external_id, pk in no_banco.items():
            if external_id in ignorar:
                continue
            numeros = {**tmdb_stats(kind, linhas[external_id]), 'updated_at': agora}
            titulo = Title(pk=pk, **{c: numeros[c] for c in STATS_FIELDS})
            titulo.poster_url = numeros['poster_url']
            titulos.append(titulo)
        com_capa = [t for t in titulos if t.poster_url]
        Title.objects.bulk_update(titulos, STATS_FIELDS, batch_size=BATCH_SIZE)
        Title.objects.bulk_update(com_capa, ['poster_url'], batch_size=BATCH_SIZE)
        return len(titulos)

    # -------------------------------------------------------------- AniList

    def _anime(self):
        cliente = AniListCatalog()
        registros = {}
        if self.opcoes['anime']:
            for r in cliente.popular(self.opcoes['anime']):
                registros[r.external_id] = r
        if self.desde and self.opcoes['recent']:
            for r in cliente.popular(self.opcoes['recent'], desde=self.desde):
                registros.setdefault(r.external_id, r)
        # A AniList já entrega tudo numa listagem: grava completo, novos e existentes.
        lista = list(registros.values())
        gravados = sum(save_records(lista[i:i + SAVE_EVERY]) for i in range(0, len(lista), SAVE_EVERY))
        self.stdout.write(self.style.SUCCESS(f'Animes: {gravados} gravados.'))

    # -------------------------------------------------------------- índice

    def _index(self):
        # Import tardio: o app recommender depende do catálogo, não o contrário.
        from recommender.engine import rebuild_index
        from recommender.management.commands.build_index import run_map

        inicio = time.perf_counter()
        indice = rebuild_index()
        self.stdout.write(self.style.SUCCESS(
            f'Índice: {indice.size} títulos x {indice.dimensions} dimensões em {time.perf_counter() - inicio:.1f}s'
        ))
        if not self.opcoes['no_map']:
            run_map(self, indice)
