"""Contrato do BufferManager (+ FileManager por trás). Silberschatz 13.5."""
import pytest

from src.common.config import load_config
from src.common.erros import BufferFullError
from src.common.tipos import CHAVES_STATS
from tests.conftest import bm_fake, bm_real
from tests.contratos import construir

DADOS = 3  # área 'dados' pequena para forçar substituição


@pytest.fixture
def cfg_peq():
    return load_config(overrides={"buffer.areas.dados": DADOS, "buffer.total_pages": 8 + 64 + DADOS + 64})


@pytest.fixture(params=["fake", "real"])
def buf(request, cfg_peq, tmp_path, _buffers_sem_pins):
    b = construir(request.param, lambda: bm_real(cfg_peq, tmp_path), lambda: bm_fake(cfg_peq))
    _buffers_sem_pins.append(b)
    return b


def _arquivo_com(buf, n):
    """Cria arquivo com n blocos (conteúdo = nº do bloco), grava e esvazia o buffer."""
    fid = buf.create("t", "heap")
    bnos = []
    for i in range(n):
        with buf.fresh_page(fid) as fr:
            fr.data[0:4] = (fr.bno).to_bytes(4, "little")
            bnos.append(fr.bno)
    buf.drop_all()
    buf.reset_stats()
    return fid, bnos


def _acessar(buf, fid, seq):
    for b in seq:
        with buf.page(fid, b):
            pass


def test_grava_e_le_apos_cold_start(buf):
    fid, bnos = _arquivo_com(buf, 5)
    for b in bnos:
        with buf.page(fid, b) as fr:
            assert int.from_bytes(fr.data[0:4], "little") == b
            assert len(fr.data) == buf.block_size
    assert buf.num_blocks(fid) == 5


def test_stats_chaves_e_invariante(buf):
    fid, bnos = _arquivo_com(buf, 2)
    _acessar(buf, fid, [bnos[0], bnos[0], bnos[1]])
    st = buf.stats()
    assert set(CHAVES_STATS) <= set(st) and "por_area" in st
    assert st["requests"] == 3 and st["hits"] == 1 and st["misses"] == 2
    assert st["hits"] + st["misses"] == st["requests"]
    assert st["por_area"]["dados"]["requests"] == 3
    assert st["reads"] == 2 and st["transferencias"] == st["reads"] + st["writes"]
    assert st["seeks"] == st["rand_reads"] + st["rand_writes"]
    buf.reset_stats()
    assert buf.stats()["requests"] == 0 and buf.stats()["reads"] == 0


def test_new_page_nao_conta_request(buf):
    fid = buf.create("t", "heap")
    buf.reset_stats()
    with buf.fresh_page(fid):
        pass
    st = buf.stats()
    assert st["requests"] == 0 and st["reads"] == 0


@pytest.mark.parametrize("politica,misses,hits", [
    # área de 3 páginas, referências 1,2,3,1,4,2:
    # LRU: 1m 2m 3m 1h | 4m expulsa 2 (menos recente) | 2m expulsa 3  -> 5 faltas, 1 acerto
    ("LRU", 5, 1),
    # MRU: 1m 2m 3m 1h | 4m expulsa 1 (mais recente)  | 2h            -> 4 faltas, 2 acertos
    ("MRU", 4, 2),
])
def test_sequencia_classica(buf, politica, misses, hits):
    fid, b = _arquivo_com(buf, 4)
    buf.set_policy("dados", politica)
    _acessar(buf, fid, [b[0], b[1], b[2], b[0], b[3], b[1]])
    st = buf.stats()
    assert (st["misses"], st["hits"]) == (misses, hits)


def test_expulsao_dirty_grava_e_limpa_nao(buf):
    fid, b = _arquivo_com(buf, 5)
    with buf.page(fid, b[0], dirty=True) as fr:
        fr.data[10] = 7
    _acessar(buf, fid, [b[1], b[2], b[3]])        # LRU expulsa b0 (dirty) -> 1 escrita
    st = buf.stats()
    assert st["writes"] == 1 and st["dirty_evictions"] == 1
    _acessar(buf, fid, [b[4]])                    # expulsa b1 (limpa) -> nenhuma escrita
    assert buf.stats()["writes"] == 1
    with buf.page(fid, b[0]) as fr:               # alteração persistiu
        assert fr.data[10] == 7


def test_mark_dirty_tambem_grava(buf):
    fid, b = _arquivo_com(buf, 1)
    with buf.page(fid, b[0]) as fr:
        fr.data[5] = 9
        fr.mark_dirty()
    buf.drop_all()
    with buf.page(fid, b[0]) as fr:
        assert fr.data[5] == 9


def test_pinada_nao_e_expulsa(buf):
    fid, b = _arquivo_com(buf, 4)
    frames = [buf.pin(fid, x) for x in b[:DADOS]]
    with pytest.raises(BufferFullError):
        buf.pin(fid, b[3])
    for fr in frames:
        buf.unpin(fr)
    with buf.page(fid, b[3]):
        pass


def test_toss_immediate_vira_proxima_vitima(buf):
    fid, b = _arquivo_com(buf, 4)
    _acessar(buf, fid, [b[0], b[1]])
    with buf.page(fid, b[2], toss=True):
        pass
    _acessar(buf, fid, [b[3]])        # LRU expulsaria b0; com toss expulsa b2
    buf.reset_stats()
    _acessar(buf, fid, [b[0], b[1]])
    assert buf.stats()["hits"] == 2
    _acessar(buf, fid, [b[2]])
    assert buf.stats()["misses"] == 1


def test_assert_no_pins(buf):
    fid, b = _arquivo_com(buf, 1)
    fr = buf.pin(fid, b[0])
    with pytest.raises(AssertionError):
        buf.assert_no_pins()
    buf.unpin(fr)
    buf.assert_no_pins()


def test_context_manager_solta_com_excecao(buf):
    fid, b = _arquivo_com(buf, 1)
    with pytest.raises(RuntimeError):
        with buf.page(fid, b[0]):
            raise RuntimeError("x")
    buf.assert_no_pins()


def test_leitura_sequencial_vs_aleatoria(buf):
    fid, b = _arquivo_com(buf, 3)
    _acessar(buf, fid, b)
    st = buf.stats()
    assert st["reads"] == 3
    assert st["seq_reads"] >= 2 and st["rand_reads"] <= 1


def test_flush_conta_forced_write(buf):
    fid, b = _arquivo_com(buf, 1)
    with buf.page(fid, b[0], dirty=True):
        pass
    buf.flush(fid, b[0])
    st = buf.stats()
    assert st["forced_writes"] == 1 and st["writes"] == 1
    buf.flush(fid, b[0])                          # já limpa: nada a gravar
    assert buf.stats()["writes"] == 1


def test_free_page_e_delete(buf):
    fid, b = _arquivo_com(buf, 3)
    buf.free_page(fid, b[1])
    assert buf.num_blocks(fid) == 2
    with buf.fresh_page(fid) as fr:               # reusa o bloco liberado
        assert fr.bno == b[1]
    buf.delete("t")
    assert not buf.exists("t")


def test_cabecalho_meta(buf):
    fid = buf.create("t", "heap", {"x": 1})
    buf.set_header(fid, raiz=5)
    h = buf.header(fid)
    assert h["tipo_org"] == "heap" and h["meta"]["x"] == 1 and h["meta"]["raiz"] == 5


def test_area_capacity(buf, cfg_peq):
    assert buf.area_capacity("dados") == DADOS
    assert buf.area_capacity("trabalho") == cfg_peq.M
