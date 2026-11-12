import time

from django.core.management.base import BaseCommand, CommandError

from recommender.engine import EmptyCatalog, rebuild_index
from recommender.projection import build_map


class Command(BaseCommand):
    help = 'Recalcula a matriz de features do recomendador, salva o índice em disco e projeta o mapa do gosto.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-map', action='store_true',
            help='Não recalcula o mapa do gosto (SVD + t-SNE, dezenas de segundos em catálogos grandes).',
        )

    def handle(self, *args, no_map, **options):
        inicio = time.perf_counter()
        try:
            indice = rebuild_index()
        except EmptyCatalog as erro:
            raise CommandError(str(erro)) from erro
        blocos = ', '.join(f'{nome}: {fim - ini}' for nome, (ini, fim) in indice.blocks.items())
        self.stdout.write(self.style.SUCCESS(
            f'{indice.size} títulos x {indice.dimensions} dimensões ({blocos}) '
            f'em {time.perf_counter() - inicio:.1f}s'
        ))
        if not no_map:
            run_map(self, indice)


def run_map(comando, indice):
    """Projeta o mapa e informa o tempo (compartilhado com `import_dataset`)."""
    inicio = time.perf_counter()
    comando.stdout.write('Projetando o mapa do gosto (SVD + t-SNE)...')
    total = build_map(indice)
    comando.stdout.write(comando.style.SUCCESS(
        f'Mapa: {total} títulos posicionados em {time.perf_counter() - inicio:.1f}s'
    ))
