"""E02 — Gerente de Buffer Pool real sobre o FileManager real (Silberschatz 13.5, 19.5)."""
import pytest

from src.common.config import load_config
from src.common.erros import BufferFullError, StorageError
from src.storage.buffer_manager import BufferManager
from src.storage.file_manager import FileManager

DADOS = 3


@pytest.fixture
def cfg():
    return load_config(overrides={"buffer.areas.dados": DADOS,
                                  "buffer.total_pages": 8 + 64 + DADOS + 64})


@pytest.fixture
def novo_bm(tmp_path, _buffers_sem_pins):
    criados = []

    def fabrica(c):
        b = BufferManager(c, FileManager(c, tmp_path / f"bm{len(criados)}"))
        criados.append(b)
        _buffers_sem_pins.append(b)
        return b
    yield fabrica
    for b in criados:
        b.fm.close_all()


@pytest.fixture
def bm(cfg, novo_bm):
    return novo_bm(cfg)


def _arquivo(bm, n, nome="t"):
    fid = bm.create(nome, "heap")
    bnos = []
    for _ in range(n):
        with bm.fresh_page(fid) as fr:
            fr.data[0:4] = fr.bno.to_bytes(4, "little")
            bnos.append(fr.bno)
    bm.drop_all()
    bm.reset_stats()
    return fid, bnos


def _acessar(bm, fid, seq, area="dados"):
    for b in seq:
        with bm.page(fid, b, area):
            pass


def _faltas(bm, fid, seq):
    bm.reset_stats()
    _acessar(bm, fid, seq)
    return bm.stats()["misses"]


# ------------------------------------------------------------ políticas no buffer real
@pytest.mark.parametrize("politica,faltas", [
    # área de 3 páginas, referências a,b,c,a,d,b,e,a (8 refs):
    # LRU : a b c m | a h | d m(-b) | b m(-c) | e m(-a) | a m(-d)        -> 7
    # MRU : a b c m | a h | d m(-a) | b h     | e m(-b) | a m(-e)        -> 6
    # FIFO: a b c m | a h | d m(-a) | b h     | e m(-b) | a m(-c)        -> 6
    # CLOCK: anel [a,b,c] bits 1; a h; d: zera a,b,c, expulsa a -> [d,b,c] mão=1;
    #        b h (bit 1); e: zera b, expulsa c -> [d,b,e] mão=0; a: expulsa d? d tem bit 1
    #        -> zera d, b tem bit 0 -> expulsa b -> [d,a,e]                -> 6
    ("LRU", 7), ("MRU", 6), ("FIFO", 6), ("CLOCK", 6),
])
def test_politicas_no_buffer(bm, politica, faltas):
    fid, b = _arquivo(bm, 5)
    bm.set_policy("dados", politica)
    a, b_, c, d, e = b
    assert _faltas(bm, fid, [a, b_, c, a, d, b_, e, a]) == faltas


def test_policy_inicial_vem_do_cfg(novo_bm):
    c = load_config(overrides={"buffer.policies": {"dados": "MRU"}})
    b = novo_bm(c)
    assert b.policy("dados") == "MRU" and b.policy("indice") == "LRU"


def test_set_policy_invalida(bm):
    with pytest.raises(StorageError):
        bm.set_policy("dados", "OPT")
    with pytest.raises(StorageError):
        bm.set_policy("xpto", "LRU")


def test_set_policy_com_paginas_residentes(bm):
    fid, b = _arquivo(bm, 4)
    _acessar(bm, fid, b[:3])
    bm.set_policy("dados", "FIFO")      # residentes entram na ordem de carga: b0 é a vítima
    _acessar(bm, fid, [b[3]])
    assert _faltas(bm, fid, [b[1], b[2], b[3]]) == 0


# ------------------------------------------------------------ dirty / escrita
def test_expulsao_dirty_grava_e_limpa_nao(bm):
    fid, b = _arquivo(bm, 5)
    with bm.page(fid, b[0], dirty=True) as fr:
        fr.data[100] = 42
    _acessar(bm, fid, b[1:4])           # expulsa b0 (dirty)
    st = bm.stats()
    assert st["writes"] == 1 and st["dirty_evictions"] == 1
    _acessar(bm, fid, [b[4]])           # expulsa b1 (limpa)
    assert bm.stats()["writes"] == 1
    with bm.page(fid, b[0]) as fr:
        assert fr.data[100] == 42


def test_dados_persistem_apos_close_e_open(bm):
    fid, b = _arquivo(bm, 2)
    with bm.page(fid, b[1], dirty=True) as fr:
        fr.data[7] = 77
    bm.close(fid)
    fid2 = bm.open("t")
    with bm.page(fid2, b[1]) as fr:
        assert fr.data[7] == 77


def test_flush_all_grava_em_ordem_sequencial(bm):
    fid = bm.create("t", "heap")
    for _ in range(DADOS):
        with bm.fresh_page(fid):
            pass
    bm.reset_stats()
    bm.flush_all()
    st = bm.stats()
    # 3 blocos + cabeçalho (alterado pelos allocate_block); blocos 1..3 em ordem
    assert st["writes"] == DADOS + 1
    assert st["seq_writes"] >= DADOS - 1
    bm.flush_all()                       # nada mais dirty
    assert bm.stats()["writes"] == DADOS + 1


def test_flush_forced_output(bm):
    fid, b = _arquivo(bm, 1)
    with bm.page(fid, b[0]) as fr:
        fr.mark_dirty()
    bm.flush(fid, b[0])
    st = bm.stats()
    assert st["forced_writes"] == 1 and st["writes"] == 1
    assert st["por_area"]["dados"]["forced_writes"] == 1
    bm.flush(fid, b[0])
    bm.flush(fid, 999)                   # não residente: nada a fazer
    assert bm.stats()["writes"] == 1


# ------------------------------------------------------------ pin
def test_pin_impede_expulsao_e_buffer_cheio(bm):
    fid, b = _arquivo(bm, 4)
    frs = [bm.pin(fid, x) for x in b[:DADOS]]
    with pytest.raises(BufferFullError):
        bm.pin(fid, b[3])
    with pytest.raises(BufferFullError):
        bm.new_page(fid)
    assert bm.num_blocks(fid) == 4       # new_page falho não deixa bloco órfão
    bm.unpin(frs[1])
    with bm.page(fid, b[3]):             # só b1 podia sair
        pass
    for f in (frs[0], frs[2]):
        bm.unpin(f)
    assert _faltas(bm, fid, [b[0], b[2], b[3]]) == 0


def test_pin_duplo_precisa_de_dois_unpins(bm):
    fid, b = _arquivo(bm, 1)
    f1 = bm.pin(fid, b[0])
    f2 = bm.pin(fid, b[0])
    assert f1 is f2 and f1.pin_count == 2
    bm.unpin(f1)
    with pytest.raises(AssertionError):
        bm.assert_no_pins()
    bm.unpin(f2)
    bm.assert_no_pins()
    with pytest.raises(StorageError):
        bm.unpin(f1)                     # unpin sem pin


def test_drop_all_e_close_com_pin_falham(bm):
    fid, b = _arquivo(bm, 1)
    fr = bm.pin(fid, b[0])
    with pytest.raises(StorageError):
        bm.drop_all()
    with pytest.raises(StorageError):
        bm.close(fid)
    with pytest.raises(StorageError):
        bm.free_page(fid, b[0])
    bm.unpin(fr)


def test_bloco_invalido_nao_expulsa_ninguem(bm):
    fid, b = _arquivo(bm, 3)
    _acessar(bm, fid, b)
    with pytest.raises(StorageError):
        bm.pin(fid, 999)
    assert _faltas(bm, fid, b) == 0


# ------------------------------------------------------------ toss-immediate
def test_toss_immediate(bm):
    fid, b = _arquivo(bm, 4)
    _acessar(bm, fid, [b[0], b[1]])
    with bm.page(fid, b[2], toss=True):
        pass
    _acessar(bm, fid, [b[3]])            # expulsa b2 (tossed), não b0 (LRU)
    assert _faltas(bm, fid, [b[0], b[1], b[3]]) == 0


def test_toss_immediate_por_cfg(novo_bm):
    c = load_config(overrides={"buffer.areas.dados": DADOS, "buffer.total_pages": 8 + 64 + DADOS + 64,
                               "buffer.toss_immediate": True})
    bm = novo_bm(c)
    fid, b = _arquivo(bm, 4)
    _acessar(bm, fid, b)                 # cada página é tossed: b3 substitui a última (b2)
    assert _faltas(bm, fid, [b[0], b[1]]) == 0


# ------------------------------------------------------------ áreas
def test_areas_independentes(bm):
    fid, b = _arquivo(bm, 6)
    _acessar(bm, fid, b[:3], area="indice")
    _acessar(bm, fid, b[3:6], area="dados")
    assert _faltas(bm, fid, b) == 0      # 'dados' cheia não expulsou páginas de 'indice'
    st = bm.stats()["por_area"]                     # hit conta na área de residência
    assert st["dados"]["hits"] == 3 and st["indice"]["hits"] == 3


def test_hit_conta_na_area_de_residencia(bm):
    fid, b = _arquivo(bm, 1)
    _acessar(bm, fid, [b[0]], area="indice")
    bm.reset_stats()
    _acessar(bm, fid, [b[0]], area="dados")
    st = bm.stats()["por_area"]
    assert st["indice"]["hits"] == 1 and st["dados"]["requests"] == 0


def test_area_inexistente(bm):
    fid, b = _arquivo(bm, 1)
    with pytest.raises(StorageError):
        bm.pin(fid, b[0], area="xpto")
    with pytest.raises(StorageError):
        bm.area_capacity("xpto")


def test_area_capacity(bm, cfg):
    for a, n in cfg.buffer_areas.items():
        assert bm.area_capacity(a) == n


# ------------------------------------------------------------ estatísticas
def test_estatisticas(bm):
    fid, b = _arquivo(bm, 3)
    _acessar(bm, fid, [b[0], b[1], b[0], b[2], b[0]])
    st = bm.stats()
    assert st["requests"] == 5 and st["hits"] == 2 and st["misses"] == 3
    assert st["hits"] + st["misses"] == st["requests"]
    assert st["hit_rate"] == pytest.approx(2 / 5)
    assert st["por_area"]["dados"]["hit_rate"] == pytest.approx(2 / 5)
    assert st["por_area"]["indice"]["hit_rate"] == 0.0
    assert st["transferencias"] == st["reads"] + st["writes"] == 3
    assert st["seeks"] == st["rand_reads"] + st["rand_writes"]
    bm.reset_stats()
    assert all(bm.stats()[k] == 0 for k in ("requests", "reads", "writes", "dirty_evictions"))


def test_new_page_nao_conta_request_nem_leitura(bm):
    fid = bm.create("t", "heap")
    bm.reset_stats()
    with bm.fresh_page(fid) as fr:
        assert fr.dirty and fr.bno == 1 and len(fr.data) == bm.block_size
    st = bm.stats()
    assert st["requests"] == 0 and st["reads"] == 0


# ------------------------------------------------------------ free/delete
def test_free_page_descarta_sem_gravar_e_reusa(bm):
    fid, b = _arquivo(bm, 3)
    with bm.page(fid, b[1], dirty=True):
        pass
    bm.reset_stats()
    bm.free_page(fid, b[1])
    assert bm.stats()["writes"] == 1     # só a marca de bloco livre do FileManager
    assert bm.num_blocks(fid) == 2
    with pytest.raises(StorageError):
        bm.pin(fid, b[1])                # bloco livre
    with bm.fresh_page(fid) as fr:
        assert fr.bno == b[1]


def test_delete_descarta_paginas(bm):
    fid, b = _arquivo(bm, 2)
    with bm.page(fid, b[0], dirty=True):
        pass
    bm.delete("t")
    assert not bm.exists("t")
    bm.drop_all()                        # nada do arquivo apagado ficou no pool
    fid2 = bm.create("t", "heap")
    assert bm.num_blocks(fid2) == 0


# ------------------------------------------------------------ prefetch
def test_prefetch(novo_bm):
    c = load_config(overrides={"buffer.prefetch": 2})
    bm = novo_bm(c)
    fid, b = _arquivo(bm, 5)
    _acessar(bm, fid, b)
    st = bm.stats()
    # b0 miss (+ lê b1,b2) ; b1,b2 hit ; b3 miss (+ lê b4) ; b4 hit
    assert (st["requests"], st["misses"], st["hits"]) == (5, 2, 3)
    assert st["reads"] == 5 and st["hits"] + st["misses"] == st["requests"]
