"""Índice publicado no Vercel Blob: publicação, limpeza e uso no lugar de reconstruir."""
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import joblib
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from catalog.importers.loader import refresh_popularity_ranks, save_records
from catalog.models import Title
from catalog.tests.factories import sample_catalog
from recommender import engine, index_store
from recommender.config import get_config
from recommender.models import IndexSnapshot


class BlobFalso:
    """Imita vercel.blob.sync: guarda os arquivos em memória."""

    def __init__(self):
        self.arquivos, self.apagados = {}, []

    def put_blob(self, pathname, corpo, **opcoes):
        self.arquivos[pathname] = corpo
        return SimpleNamespace(url=f'https://loja.public.blob.vercel-storage.com/{pathname}', pathname=pathname)

    def delete_blob(self, caminhos):
        self.apagados += caminhos
        for c in caminhos:
            self.arquivos.pop(c, None)


class IndiceTestCase(TestCase):
    usar_snapshots = False

    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.caminho = Path(pasta.name) / 'indice.joblib'
        configuracao = override_settings(RECOMMENDER={'INDEX_PATH': self.caminho, 'USE_SNAPSHOTS': self.usar_snapshots})
        configuracao.enable()
        self.addCleanup(configuracao.disable)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)
        self.limpar_memoria()
        self.addCleanup(self.limpar_memoria)
        save_records(sample_catalog())
        refresh_popularity_ranks()
        self.blob = BlobFalso()

    def limpar_memoria(self):
        engine._cached, engine._checked_at, engine._snapshot_pk = None, 0.0, None

    def baixar_do_blob(self, snapshot):
        return joblib.load(io.BytesIO(self.blob.arquivos[snapshot.pathname]))


class PublicacaoTests(IndiceTestCase):
    def test_publica_e_guarda_so_as_duas_ultimas(self):
        indice = engine.get_index()
        primeiro = index_store.publish(indice, blob=self.blob)
        self.assertEqual((primeiro.total, primeiro.feature_hash), (indice.fingerprint[0], indice.feature_hash))
        self.assertEqual(self.baixar_do_blob(primeiro).size, indice.size)

        caminhos = [primeiro.pathname]
        for titulo in ('Nova A', 'Nova B'):
            save_records([sample_catalog()[0].__class__(kind='movie', source='tmdb', external_id=titulo,
                                                        title=titulo, overview='space')])
            snapshot = index_store.publish(engine.get_index(), blob=self.blob)
            caminhos.append(snapshot.pathname)

        self.assertEqual(IndexSnapshot.objects.count(), 2)
        self.assertEqual(self.blob.apagados, [caminhos[0]])
        self.assertEqual(set(self.blob.arquivos), set(caminhos[1:]))

    def test_republicar_o_mesmo_catalogo_nao_apaga_o_arquivo_em_uso(self):
        indice = engine.get_index()
        a = index_store.publish(indice, blob=self.blob)
        b = index_store.publish(indice, blob=self.blob)
        index_store.publish(indice, blob=self.blob)
        self.assertEqual(a.pathname, b.pathname)
        self.assertIn(a.pathname, self.blob.arquivos)

    def test_comando_exige_o_token(self):
        with mock.patch.dict('os.environ', {'BLOB_READ_WRITE_TOKEN': ''}):
            with self.assertRaises(CommandError):
                call_command('publish_index')


class UsoNoVercelTests(IndiceTestCase):
    usar_snapshots = True

    def publicar(self):
        indice = engine.rebuild_index()
        snapshot = index_store.publish(indice, blob=self.blob)
        self.caminho.unlink()          # instância nova: sem nada no disco nem em memória
        self.limpar_memoria()
        return snapshot

    def test_baixa_o_publicado_em_vez_de_construir(self):
        self.publicar()
        with mock.patch.object(index_store, 'download', side_effect=self.baixar_do_blob) as baixar, \
             mock.patch.object(engine, '_build_and_save') as construir:
            indice = engine.get_index()
        baixar.assert_called_once()
        construir.assert_not_called()
        self.assertEqual(indice.size, Title.objects.count())

    def test_catalogo_mudou_usa_o_publicado_ate_sair_um_novo(self):
        snapshot = self.publicar()
        Title.objects.filter(pk=Title.objects.first().pk).update(title='Mudou')
        Title.objects.first().save()   # novo updated_at: o fingerprint muda
        with mock.patch.object(index_store, 'download', side_effect=self.baixar_do_blob) as baixar, \
             mock.patch.object(engine, '_build_and_save') as construir:
            antigo = engine.get_index()
            engine.get_index()         # de novo: não baixa outra vez o mesmo arquivo
        construir.assert_not_called()
        self.assertEqual(baixar.call_count, 1)
        self.assertEqual(antigo.fingerprint, snapshot.fingerprint)

    def test_sem_publicado_ou_falha_no_download_constroi(self):
        with mock.patch.object(engine, '_build_and_save', wraps=engine._build_and_save) as construir:
            engine.get_index()
        construir.assert_called_once()

        self.publicar()
        with mock.patch.object(index_store, 'download', return_value=None), \
             mock.patch.object(engine, '_build_and_save', wraps=engine._build_and_save) as construir:
            engine.get_index()
        construir.assert_called_once()

    def test_fora_do_vercel_ignora_os_publicados(self):
        self.publicar()
        with override_settings(RECOMMENDER={'INDEX_PATH': self.caminho, 'USE_SNAPSHOTS': False}):
            get_config.cache_clear()
            with mock.patch.object(index_store, 'download') as baixar:
                engine.get_index()
        baixar.assert_not_called()


class SincronizacaoAtualizaFingerprintTests(IndiceTestCase):
    @override_settings(TMDB_API_KEY='chave')
    def test_so_numeros_novos_mudam_o_fingerprint(self):
        from catalog.importers.api import AniListCatalog, TmdbCatalog
        antes = engine._fingerprint()
        linha = {'id': 1, 'vote_average': 9.9, 'vote_count': 1, 'popularity': 1}
        with mock.patch.object(TmdbCatalog, 'discover', side_effect=lambda k, n, **kw: [] if k == 'series' or kw.get('desde') else [linha]), \
             mock.patch.object(AniListCatalog, 'popular', return_value=[]):
            call_command('sync_catalog', no_index=True, stdout=io.StringIO())
        self.assertNotEqual(engine._fingerprint(), antes)
