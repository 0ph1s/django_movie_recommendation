# recommender/index_store.py
"""
Índice pronto no Vercel Blob: publicado pela rotina diária e baixado pelas instâncias do Vercel.

Reconstruir o índice a partir do banco leva dezenas de segundos com o catálogo grande, tempo
demais para a primeira requisição de uma instância nova. A rotina diária (GitHub Actions)
constrói o índice uma vez e o publica com `manage.py publish_index`; o registro IndexSnapshot
diz qual arquivo vale para qual estado do catálogo.

  * Publicar  exige BLOB_READ_WRITE_TOKEN e o pacote `vercel-blob`, instalados só na rotina.
  * Baixar    é um GET na URL pública, com a biblioteca padrão: o Vercel não precisa de nada.

Cada publicação usa um caminho novo (derivado do fingerprint), então o cache da CDN nunca
entrega um arquivo antigo. As publicações mais velhas que as `KEEP` últimas são apagadas.
"""
import hashlib
import io
import logging
from urllib.request import Request, urlopen

import joblib

from .models import IndexSnapshot

logger = logging.getLogger(__name__)

KEEP = 2
DOWNLOAD_TIMEOUT = 30
PREFIX = 'indices'


def snapshot_for(fingerprint, feature_hash, formato):
    """O snapshot exato para este estado do catálogo; senão, o mais recente compatível."""
    compativeis = IndexSnapshot.objects.filter(feature_hash=feature_hash, format=formato)
    exato = compativeis.filter(total=fingerprint[0], last_update=fingerprint[1] or '').first()
    return exato or compativeis.first()


def download(snapshot):
    """Baixa e desserializa o índice. Devolve None em qualquer falha (quem chama reconstrói)."""
    try:
        with urlopen(Request(snapshot.url, headers={'User-Agent': 'Angulo/1.0'}), timeout=DOWNLOAD_TIMEOUT) as r:
            return joblib.load(io.BytesIO(r.read()))
    except Exception:  # rede, arquivo apagado ou de outra versão das bibliotecas
        logger.warning('Não foi possível baixar o índice publicado %s.', snapshot.url, exc_info=True)
        return None


def publish(indice, blob=None):
    """Envia o índice ao Blob, registra o snapshot e apaga os antigos. Devolve o snapshot."""
    if blob is None:
        try:
            from vercel.blob import sync as blob
        except ImportError as erro:
            raise RuntimeError('Publicar o índice exige o pacote vercel-blob (pip install vercel-blob).') from erro

    dados = io.BytesIO()
    joblib.dump(indice, dados, compress=3)
    corpo = dados.getvalue()
    total, ultimo = indice.fingerprint
    chave = hashlib.sha1(f'{total}|{ultimo}|{indice.feature_hash}'.encode()).hexdigest()[:16]
    pathname = f'{PREFIX}/recommender-v{indice.format}-{chave}.joblib'

    enviado = blob.put_blob(pathname, corpo, access='public', content_type='application/octet-stream',
                            allow_overwrite=True)
    snapshot = IndexSnapshot.objects.create(
        url=enviado.url, pathname=enviado.pathname, total=total, last_update=ultimo or '',
        feature_hash=indice.feature_hash, format=indice.format, size=len(corpo),
    )

    antigos = list(IndexSnapshot.objects.exclude(pk=snapshot.pk)[KEEP - 1:])
    # O mesmo caminho pode ter sido republicado (mesmo catálogo): não apaga o arquivo em uso.
    caminhos = sorted({s.pathname for s in antigos} - {snapshot.pathname})
    if caminhos:
        blob.delete_blob(caminhos)
    IndexSnapshot.objects.filter(pk__in=[s.pk for s in antigos]).delete()
    return snapshot
