# recommender/management/commands/publish_index.py
"""
Publica o índice de recomendação no Vercel Blob para as instâncias do Vercel baixarem pronto.

Roda na rotina diária (.github/workflows/sync-catalog.yml), depois de `sync_catalog` e
`build_index`. Usa o índice atual do catálogo (constrói se preciso), envia o arquivo, registra
o IndexSnapshot e apaga as publicações antigas.

Exige BLOB_READ_WRITE_TOKEN (o token do store "angulo-indice") e o pacote vercel-blob.
"""
import os
import time

from django.core.management.base import BaseCommand, CommandError

from recommender.engine import EmptyCatalog, get_index
from recommender.index_store import publish


class Command(BaseCommand):
    help = 'Publica o índice de recomendação no Vercel Blob (rotina diária).'

    def handle(self, *args, **options):
        if not os.environ.get('BLOB_READ_WRITE_TOKEN'):
            raise CommandError('Defina BLOB_READ_WRITE_TOKEN (token do Vercel Blob) para publicar o índice.')
        try:
            indice = get_index()
        except EmptyCatalog as erro:
            raise CommandError(str(erro)) from erro
        inicio = time.perf_counter()
        try:
            snapshot = publish(indice)
        except RuntimeError as erro:
            raise CommandError(str(erro)) from erro
        self.stdout.write(self.style.SUCCESS(
            f'Índice publicado: {snapshot.total} títulos, {snapshot.size / 1e6:.1f} MB, '
            f'em {time.perf_counter() - inicio:.1f}s -> {snapshot.url}'
        ))
