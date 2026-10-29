import time

from django.core.management.base import BaseCommand, CommandError

from recommender.engine import EmptyCatalog, rebuild_index


class Command(BaseCommand):
    help = 'Recalcula a matriz de features do recomendador e salva o índice em disco.'

    def handle(self, *args, **options):
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
