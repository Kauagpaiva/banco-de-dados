"""Contrato de SecondaryIndex (Silberschatz 14.2, 14.3.5, 14.5)."""
import pytest

from src.access.contracts import Campo
from src.common.erros import ChaveDuplicadaError, OperacaoNaoSuportada
from src.common.tipos import RID
from tests.contratos import construir
from tests.fakes import FakeIndex

CAMPO = Campo("CPF", "char(11)")


def _hash(bm, page_impl):
    from src.access.hash_index import HashIndex
    return HashIndex(bm, "idx", CAMPO, nr_estimado=500, page_impl=page_impl)


def _bplus(bm, page_impl):
    from src.access.secondary_bplus import BPlusIndex
    return BPlusIndex(bm, "idx", CAMPO, unique=False, page_impl=page_impl)


@pytest.fixture(params=["fake-unique", "fake-nonunique", "real-hash", "real-bplus"])
def idx(request, bm, page_impl):
    tipo, nome = request.param.split("-")
    if tipo == "fake":
        i = FakeIndex(bm, "idx", CAMPO, unique=(nome == "unique"))
    else:
        i = construir("real", lambda: {"hash": _hash, "bplus": _bplus}[nome](bm, page_impl), None)
    i.open()
    return i


def _k(i):
    return f"{i:011d}"


def test_insere_busca_remove(idx):
    for i in range(500):
        idx.insert(_k(i), RID(i // 10 + 1, i % 10))
    for i in range(0, 500, 37):
        assert list(idx.search_eq(_k(i))) == [RID(i // 10 + 1, i % 10)]
    assert list(idx.search_eq(_k(9999))) == []
    idx.delete(_k(5), RID(1, 5))
    assert list(idx.search_eq(_k(5))) == []
    with pytest.raises(KeyError):
        idx.delete(_k(5), RID(1, 5))
    assert idx.altura() >= 1 and idx.num_blocks() >= 1


def test_unique_rejeita_duplicata(idx):
    idx.insert(_k(1), RID(1, 0))
    if idx.unique:
        with pytest.raises(ChaveDuplicadaError):
            idx.insert(_k(1), RID(1, 1))
    else:
        for s in range(1, 300):                     # muitas duplicatas da mesma chave
            idx.insert(_k(1), RID(1 + s // 50, s % 50))
        assert len(list(idx.search_eq(_k(1)))) == 300
        idx.delete(_k(1), RID(1, 7))
        assert RID(1, 7) not in set(idx.search_eq(_k(1)))


def test_faixa(idx):
    for i in range(200):
        idx.insert(_k(i), RID(1, i))
    try:
        got = list(idx.search_range(_k(10), _k(20), incl_lo=False, incl_hi=True))
    except OperacaoNaoSuportada:
        return                                      # hash não suporta faixa
    assert got == [RID(1, i) for i in range(11, 21)]
    assert len(list(idx.search_range(None, _k(9)))) == 10
