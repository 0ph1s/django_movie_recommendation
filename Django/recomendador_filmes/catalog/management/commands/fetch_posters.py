# catalog/management/commands/fetch_posters.py
"""
Preenche `Title.poster_url` com as capas originais.

Exemplos:
    python manage.py fetch_posters                    # tudo o que ainda não tem capa
    python manage.py fetch_posters --kinds anime      # só animes (não precisa de chave)
    python manage.py fetch_posters --limit 500        # os 500 mais populares sem capa
    python manage.py fetch_posters --refresh          # busca de novo inclusive os que já têm

Filmes e séries exigem a variável de ambiente TMDB_API_KEY (chave v3 ou token v4).
Pode ser interrompido a qualquer momento: o que já foi encontrado é gravado em lotes.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.models import Title
from catalog.posters import ANILIST_BATCH, AniListClient, PosterSourceError, TmdbClient

SAVE_EVERY = 100


class Command(BaseCommand):
    help = 'Busca as capas dos títulos no TMDB (filmes e séries) e na AniList (animes).'

    def add_arguments(self, parser):
        parser.add_argument('--kinds', default='movie,series,anime',
                            help='Tipos separados por vírgula (padrão: movie,series,anime).')
        parser.add_argument('--limit', type=int, help='No máximo N títulos, os mais populares primeiro.')
        parser.add_argument('--refresh', action='store_true', help='Busca também os que já têm capa.')
        parser.add_argument('--workers', type=int, default=8, help='Requisições simultâneas ao TMDB.')

    def handle(self, *args, **options):
        tipos = [k.strip() for k in options['kinds'].split(',') if k.strip()]
        invalidos = set(tipos) - set(Title.Kind.values)
        if invalidos:
            raise CommandError(f'Tipo desconhecido: {", ".join(sorted(invalidos))}.')

        titulos = Title.objects.filter(kind__in=tipos).order_by('-popularity_rank', 'id')
        if not options['refresh']:
            titulos = titulos.filter(poster_url='')
        if options['limit']:
            titulos = titulos[:options['limit']]
        titulos = list(titulos.only('id', 'kind', 'source', 'external_id', 'poster_url'))

        do_tmdb = [t for t in titulos if t.source == Title.Source.TMDB]
        do_mal = [t for t in titulos if t.source == Title.Source.MYANIMELIST]
        self.encontrados = self.sem_capa = 0

        try:
            if do_tmdb:
                self._tmdb(do_tmdb, options['workers'])
            if do_mal:
                self._anilist(do_mal)
        except PosterSourceError as erro:
            raise CommandError(f'{erro} O que já tinha sido encontrado foi gravado.') from erro

        self.stdout.write(self.style.SUCCESS(
            f'Capas encontradas: {self.encontrados}. Sem capa na fonte: {self.sem_capa}.'
        ))

    # ------------------------------------------------------------------ TMDB

    def _tmdb(self, titulos, workers):
        chave = getattr(settings, 'TMDB_API_KEY', '')
        if not chave:
            self.stderr.write(self.style.WARNING(
                f'TMDB_API_KEY não definida: {len(titulos)} filmes/séries ignorados. '
                'Crie uma chave gratuita em themoviedb.org (Configurações > API) e defina a variável.'
            ))
            return

        cliente = TmdbClient(chave)
        inicio = time.perf_counter()
        pendentes = []
        self.stdout.write(f'TMDB: {len(titulos)} títulos...')
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futuros = {executor.submit(cliente.poster_url, t.kind, t.external_id): t for t in titulos}
            try:
                for n, futuro in enumerate(as_completed(futuros), start=1):
                    titulo = futuros[futuro]
                    self._registrar(titulo, futuro.result(), pendentes)
                    if n % SAVE_EVERY == 0:
                        self._gravar(pendentes)
                        self.stdout.write(f'  {n}/{len(titulos)} ({time.perf_counter() - inicio:.0f}s)')
            except BaseException:
                # Chave recusada ou Ctrl+C: cancela o que falta, mas guarda o que já veio.
                for f in futuros:
                    f.cancel()
                raise
            finally:
                self._gravar(pendentes)

    # ------------------------------------------------------------------ AniList

    def _anilist(self, titulos):
        cliente = AniListClient()
        self.stdout.write(f'AniList: {len(titulos)} animes em lotes de {ANILIST_BATCH}...')
        pendentes = []
        try:
            for inicio in range(0, len(titulos), ANILIST_BATCH):
                lote = titulos[inicio:inicio + ANILIST_BATCH]
                capas = cliente.poster_urls([t.external_id for t in lote])
                for titulo in lote:
                    self._registrar(titulo, capas.get(titulo.external_id, ''), pendentes)
                self._gravar(pendentes)
                self.stdout.write(f'  {min(inicio + ANILIST_BATCH, len(titulos))}/{len(titulos)}')
        finally:
            self._gravar(pendentes)

    # ------------------------------------------------------------------ gravação

    def _registrar(self, titulo, url, pendentes):
        if url:
            titulo.poster_url = url
            pendentes.append(titulo)
            self.encontrados += 1
        else:
            self.sem_capa += 1

    @staticmethod
    def _gravar(pendentes):
        # bulk_update não mexe em updated_at: a capa não afeta o índice de recomendação.
        if pendentes:
            Title.objects.bulk_update(pendentes, ['poster_url'], batch_size=500)
            pendentes.clear()
