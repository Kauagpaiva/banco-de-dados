"""Contrato de FileOrganization (Silberschatz 13.3; enunciado §3) para Heap, B+ e Hash.

Usa o esquema Turma (chave `numero`). As variantes reais viram xfail enquanto forem stub.
"""
import pytest

from src.access.esquemas import TURMA
from src.common.erros import OperacaoNaoSuportada
from src.common.tipos import CHAVES_OCUPACAO, RID
from tests.contratos import construir
from tests.fakes import FakeTable, registros_fake

N = 300


def _heap(bm, page_impl, codec):
    from src.access.heap import HeapFile
    return HeapFile(bm, "org", TURMA, page_impl=page_impl, codec=codec(TURMA))


def _bplus(bm, page_impl, codec):
    from src.access.bplus import BPlusTree
    return BPlusTree(bm, "org", TURMA, "numero", unique=True, page_impl=page_impl,
                     codec=codec(TURMA))


def _hash(bm, page_impl, codec):
    from src.access.hashfile import HashFile
    return HashFile(bm, "org", TURMA, "numero", unique=True, nr_estimado=N,
                    page_impl=page_impl, codec=codec(TURMA))


REAIS = {"heap": _heap, "bplus": _bplus, "hash": _hash}


@pytest.fixture(params=["fake-heap", "real-heap", "real-bplus", "real-hash"])
def org(request, bm, page_impl, codec):
    tipo, nome = request.param.split("-")

    def real():
        o = REAIS[nome](bm, page_impl, codec)
        o.open()
        return o
    o = construir(tipo, real, lambda: FakeTable(bm, "org", TURMA, page_impl=page_impl,
                                                codec=codec(TURMA)))
    if tipo == "fake":
        o.open()
    return o


@pytest.fixture
def cheia(org):
    """Tabela com N registros. Não guarda RIDs: na B+ primária eles mudam em split/fusão
    (Silberschatz 14.4.2) — os testes obtêm o RID atual com `find`."""
    recs = list(registros_fake(TURMA, N, seed=3))
    for r in recs:
        assert isinstance(org.insert(r), RID)
    return org, recs, None


def _rid(org, numero):
    rid = org.find("numero", numero)
    assert rid is not None
    return rid


def test_scan_devolve_todos(cheia):
    org, recs, _ = cheia
    vistos = [r for _, r in org.scan()]
    assert sorted(vistos, key=lambda r: r["numero"]) == recs
    assert org.num_registros() == N


def test_read_por_rid(cheia):
    org, recs, _ = cheia
    for r in recs[::17]:
        assert org.read(_rid(org, r["numero"])) == r


def test_find_e_find_next(cheia):
    org, recs, _ = cheia
    alvo = recs[123]
    rid = org.find("numero", alvo["numero"])
    assert rid is not None and org.read(rid) == alvo
    assert org.find_next() is None
    assert org.find("numero", -1) is None
    # campo que não é o da organização: busca linear com duplicatas
    prof = recs[0]["semestre"]
    achados = []
    rid = org.find("semestre", prof)
    while rid is not None:
        achados.append(org.read(rid))
        rid = org.find_next()
    assert sorted(achados, key=lambda r: r["numero"]) == [r for r in recs if r["semestre"] == prof]


@pytest.mark.parametrize("op", ["=", "<", "<=", ">", ">="])
def test_find_all(cheia, op):
    org, recs, _ = cheia
    v = recs[N // 2]["numero"]
    import operator
    f = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}[op]
    got = sorted((r for _, r in org.find_all("numero", op, v)), key=lambda r: r["numero"])
    assert got == [r for r in recs if f(r["numero"], v)]


def test_find_ordered(cheia):
    org, recs, _ = cheia
    try:
        got = [r for _, r in org.find_ordered("numero", 10, 50, incl_lo=True, incl_hi=False)]
    except OperacaoNaoSuportada:
        assert org.tipo_org in ("heap", "hash")
        return
    assert got == [r for r in recs if 10 <= r["numero"] < 50]


def test_delete_update(cheia):
    org, recs, _ = cheia
    for r in recs[:50]:
        org.delete(_rid(org, r["numero"]))
    assert org.num_registros() == N - 50
    assert org.find("numero", recs[0]["numero"]) is None
    alvo = dict(recs[60], sala="X-999")
    novo = org.update(_rid(org, alvo["numero"]), alvo)
    assert org.read(novo) == alvo
    assert sorted((r["numero"] for _, r in org.scan())) == [r["numero"] for r in recs[50:]]


def test_scan_blocos_e_ocupacao(cheia):
    org, _, _ = cheia
    blocos = list(org.scan_blocos())
    assert sum(len(b) for b in blocos) == N
    oc = org.ocupacao()
    assert set(CHAVES_OCUPACAO) <= set(oc)
    assert oc["registros"] == N and oc["total"] == org.num_blocks() >= len(blocos) > 1


def test_scan_toss_e_reorganize(cheia):
    org, _, _ = cheia
    assert sum(1 for _ in org.scan(toss=True)) == N
    org.reorganize()
    assert sum(1 for _ in org.scan()) == N


def test_reabrir(cheia):
    org, recs, _ = cheia
    org.close()
    org.open()
    assert org.num_registros() == N
    assert sorted((r for _, r in org.scan()), key=lambda r: r["numero"]) == recs
