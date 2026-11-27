"""Testes do índice hash secundário UNIQUE (M4/E07) — Silberschatz 14.5."""
import datetime as dt

import pytest

from src.access.contracts import Campo
from src.access.hash_index import CodecEntrada, HashIndex
from src.common.config import load_config
from src.common.erros import ChaveDuplicadaError, OperacaoNaoSuportada, RecordError
from src.common.tipos import RID
from tests.conftest import bm_fake, bm_real, real_ou_fake

CPF = Campo("CPF", "char(11)")


def _k(i):
    return f"{i:011d}"


@pytest.fixture
def novo_bm(tmp_path, so_fakes, _buffers_sem_pins):
    def fabrica(**overrides):
        cfg = load_config("teste", overrides=overrides or None)
        b = real_ou_fake(lambda: bm_real(cfg, tmp_path / "bmx"), lambda: bm_fake(cfg), so_fakes)
        _buffers_sem_pins.append(b)
        return b
    return fabrica


@pytest.mark.parametrize("campo,valor", [
    (Campo("a", "int"), -123456789012), (Campo("a", "float"), 7.25),
    (Campo("a", "date"), dt.date(2001, 2, 3)), (Campo("a", "char(11)"), "12345678901"),
    (Campo("a", "varchar(40)"), "José da Silva"), (Campo("a", "int", nulo=True), None),
])
def test_codec_entrada_roundtrip(campo, valor):
    c = CodecEntrada(campo)
    e = {"chave": valor, "bloco": 70000, "slot": 65535}
    dado = c.encode(e)
    assert len(dado) <= c.max_size
    assert c.decode(dado) == e


def test_codec_entrada_valida_limites():
    c = CodecEntrada(CPF)
    with pytest.raises(RecordError):
        c.encode({"chave": "1" * 12, "bloco": 1, "slot": 0})      # chave maior que char(11)
    with pytest.raises(RecordError):
        c.encode({"chave": None, "bloco": 1, "slot": 0})          # NOT NULL
    with pytest.raises(RecordError):
        c.encode({"chave": _k(1), "bloco": 1, "slot": 1 << 16})   # slot fora do limite
    with pytest.raises(RecordError):
        c.decode(b"\x01\x00")                                      # truncada
    with pytest.raises(RecordError):
        CodecEntrada(Campo("a", "int")).decode(b"\x01" + bytes(6) + b"\x00\x01")
    with pytest.raises(ValueError):
        CodecEntrada(Campo("l", "list[varchar(5)]"))


def test_insere_busca_remove_e_area_indice(bm, page_impl):
    idx = HashIndex(bm, "idx_cpf", CPF, nr_estimado=1000, page_impl=page_impl)
    idx.open()
    for i in range(1000):
        idx.insert(_k(i), RID(i // 10 + 1, i % 10))
    bm.reset_stats()
    for i in range(0, 1000, 31):
        assert list(idx.search_eq(_k(i))) == [RID(i // 10 + 1, i % 10)]
    st = bm.stats()["por_area"]
    assert st["indice"]["requests"] > 0 and st["dados"]["requests"] == 0
    assert list(idx.search_eq(_k(5000))) == []
    with pytest.raises(ChaveDuplicadaError):
        idx.insert(_k(3), RID(9, 9))
    with pytest.raises(KeyError):
        idx.delete(_k(3), RID(9, 9))                 # chave existe, ref diferente
    idx.delete(_k(3), RID(1, 3))
    assert list(idx.search_eq(_k(3))) == []
    idx.insert(_k(3), RID(9, 9))                     # chave livre de novo
    assert list(idx.search_eq(_k(3))) == [RID(9, 9)]
    assert idx.altura() == 1 and idx.num_blocks() == idx.arquivo.ocupacao()["total"]
    with pytest.raises(OperacaoNaoSuportada):
        idx.search_range(_k(1), _k(9))
    with pytest.raises(TypeError):
        idx.insert(_k(10_000), 42)
    idx.close()


def test_cadeia_longa_funcao_degenerada(novo_bm, page_impl):
    bm = novo_bm(**{"hash.funcao": "degenerada"})
    idx = HashIndex(bm, "idx_deg", CPF, n_buckets=4, page_impl=page_impl)
    idx.open()
    n = 1500
    for i in range(n):
        idx.insert(_k(i), RID(i + 1, 0))
    est = idx.estatisticas()
    assert est["cadeia_max"] == est["overflow"] >= 3
    assert list(idx.search_eq(_k(n - 1))) == [RID(n, 0)]           # fim da cadeia
    for i in range(n):
        idx.delete(_k(i), RID(i + 1, 0))
    assert idx.estatisticas()["overflow"] == 0 and idx.num_blocks() == 4
    with pytest.raises(KeyError):
        idx.delete(_k(0), RID(1, 0))
    idx.close()


def test_reabrir(bm, page_impl):
    idx = HashIndex(bm, "idx_r", CPF, nr_estimado=200, page_impl=page_impl)
    idx.open()
    for i in range(200):
        idx.insert(_k(i), RID(1, i))
    idx.close()
    idx2 = HashIndex(bm, "idx_r", CPF, nr_estimado=200, page_impl=page_impl)
    idx2.open()
    assert all(list(idx2.search_eq(_k(i))) == [RID(1, i)] for i in range(200))
    idx2.close()


def test_exige_dimensionamento_e_campo(bm):
    with pytest.raises(ValueError):
        HashIndex(bm, "x", CPF)
    with pytest.raises(TypeError):
        HashIndex(bm, "x", "CPF", nr_estimado=10)
