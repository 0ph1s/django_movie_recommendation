# catalog/management/commands/import_dataset.py
"""
Importa filmes, séries e animes de arquivos CSV e reconstrói o índice de recomendação.

Exemplos:
    python manage.py import_dataset                       # arquivos padrão de data/
    python manage.py import_dataset --movies tmdb_5000_movies.csv --credits tmdb_5000_credits.csv
    python manage.py import_dataset --anime anime-dataset-2023.csv --min-votes 5000 --limit 3000
    python manage.py import_dataset --series TMDB_tv_dataset_v3.csv --min-votes 200 --truncate
"""
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.importers import read_anime, read_movies, read_series
from catalog.importers.loader import refresh_popularity_ranks, save_records, select_records
from catalog.models import Title

# Arquivos usados quando o comando roda sem nenhum caminho.
DEFAULT_FILES = {
    'movies': 'tmdb_5000_movies.csv',
    'series': 'samples/tmdb_tv_sample.csv',
    'anime': 'samples/myanimelist_anime_sample.csv',
}


class Command(BaseCommand):
    help = 'Importa CSVs do TMDB (filmes/séries) e do MyAnimeList (animes) e reconstrói o índice.'

    def add_arguments(self, parser):
        parser.add_argument('--movies', type=Path, help='CSV de filmes do TMDB 5000 (original ou pré-mesclado).')
        parser.add_argument('--credits', type=Path, help='tmdb_5000_credits.csv, se os filmes vierem no formato original.')
        parser.add_argument('--series', type=Path, help='CSV de séries do TMDB (TMDB_tv_dataset_v3.csv).')
        parser.add_argument('--anime', type=Path, help='CSV de animes do MyAnimeList (anime-dataset-2023.csv).')
        parser.add_argument('--min-votes', type=int, default=0,
                            help='Descarta títulos com menos votos que isto (útil em datasets enormes).')
        parser.add_argument('--limit', type=int, help='Importa no máximo N títulos por arquivo, os mais populares primeiro.')
        parser.add_argument('--truncate', action='store_true', help='Apaga o catálogo inteiro antes de importar.')
        parser.add_argument('--no-index', action='store_true', help='Não reconstrói o índice de recomendação ao final.')

    def handle(self, *args, **options):
        fontes = self._resolve_sources(options)

        if options['truncate']:
            apagados, _ = Title.objects.all().delete()
            self.stdout.write(f'Catálogo apagado ({apagados} registros).')

        for rotulo, leitor, caminho in fontes:
            inicio = time.perf_counter()
            registros = select_records(leitor(caminho), options['min_votes'], options['limit'])
            gravados = save_records(registros)
            self.stdout.write(self.style.SUCCESS(
                f'{rotulo}: {gravados} títulos de {caminho.name} em {time.perf_counter() - inicio:.1f}s'
            ))
        # Percentis dependem do catálogo inteiro: calculados uma vez, depois de todos os arquivos.
        refresh_popularity_ranks()

        if not options['no_index']:
            # Import tardio: o app recommender depende do catálogo, não o contrário.
            from recommender.engine import rebuild_index

            inicio = time.perf_counter()
            indice = rebuild_index()
            self.stdout.write(self.style.SUCCESS(
                f'Índice: {indice.size} títulos x {indice.dimensions} dimensões em {time.perf_counter() - inicio:.1f}s'
            ))

    def _resolve_sources(self, options):
        explicitos = any(options[k] for k in DEFAULT_FILES)
        pasta = Path(settings.DATASET_DIR)

        def caminho(chave):
            if options[chave]:
                return options[chave]
            return None if explicitos else pasta / DEFAULT_FILES[chave]

        credits = options['credits']
        candidatos = [
            ('Filmes', lambda c: read_movies(c, credits_path=credits), caminho('movies')),
            ('Séries', read_series, caminho('series')),
            ('Animes', read_anime, caminho('anime')),
        ]
        fontes = [(rotulo, leitor, c) for rotulo, leitor, c in candidatos if c is not None]
        for _, _, c in fontes:
            if not c.is_file():
                raise CommandError(f'Arquivo não encontrado: {c}')
        if credits and not credits.is_file():
            raise CommandError(f'Arquivo não encontrado: {credits}')
        return fontes
