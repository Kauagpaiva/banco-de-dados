"""Contrato de TempFile e StorageContext (área 'trabalho', Silberschatz 15.4/15.5)."""
import pytest

from src.access.esquemas import INSCRICAO
from src.common.erros import BufferFullError
from tests.contratos import construir
from tests.fakes import FakeStorageContext, FakeTempFile, registros_fake

N = 700


@pytest.fixture(params=["fake", "real"])
def contexto(request, cfg, bm, tmp_path, page_impl, codec, _buffers_sem_pins):
    def real():
        from src.access.context import criar_contexto
        return criar_contexto(cfg, tmp_path / "ctx")
    c = construir(request.param, real,
                  lambda: FakeStorageContext(cfg, bm, page_impl=page_impl, codec_factory=codec))
    _buffers_sem_pins.append(c.bm)
    yield c
    c.close()


def test_append_scan(contexto):
    t = contexto.temp_file(INSCRICAO)
    recs = list(registros_fake(INSCRICAO, N, seed=5))
    for r in recs:
        t.append(r)
    t.close()
    assert t.num_registros() == N
    assert list(t.scan()) == recs                         # ordem de escrita preservada
    blocos = list(t.blocks())
    assert len(blocos) == t.num_blocks() > 1
    assert [r for b in blocos for r in t.records_in_block(b)] == recs
    assert [r for bl in t.scan_blocos() for r in bl] == recs
    t.delete()
    assert not contexto.bm.exists(t.nome)


def test_temp_nomes_unicos_e_area_trabalho(contexto):
    a, b = contexto.temp_file(INSCRICAO), contexto.temp_file(INSCRICAO)
    assert a.nome != b.nome
    contexto.reset_stats()
    for r in registros_fake(INSCRICAO, 50):
        a.append(r)
    st = contexto.buffer_stats()["por_area"]
    assert st["dados"]["requests"] == 0


def test_paginas_de_trabalho_limitadas_a_M(contexto):
    M = contexto.work_capacity()
    assert M == contexto.cfg.M
    frames = [contexto.pin_work_page() for _ in range(M)]
    with pytest.raises(BufferFullError):
        contexto.pin_work_page()
    for f in frames:
        contexto.unpin_work_page(f)
    contexto.bm.assert_no_pins()


def test_fake_temp_direto(bm):
    t = FakeTempFile(bm, "tmp_x", INSCRICAO)
    t.append(next(registros_fake(INSCRICAO, 1)))
    assert t.num_registros() == 1
    t.delete()
