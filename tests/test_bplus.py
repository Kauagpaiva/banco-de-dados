"""Testes da B+ primária — E05 (busca, faixa, inserção/split). Oráculos (`sorted`, dict) só aqui.

Roda com a SlottedPage/RecordCodec reais ou com os fakes (fixtures `page_impl`/`codec`).
"""
import math
import random

import pytest

from src.access.bplus import BPlusTree
from src.access.esquemas import ALUNO, TURMA
from src.common.erros import ChaveDuplicadaError, OperacaoNaoSuportada
from src.common.tipos import RID
from tests.fakes import registros_fake


def nova(bm, page_impl, codec, esquema=TURMA, campo="numero", nome="bp"):
    t = BPlusTree(bm, nome, esquema, campo, unique=True, page_impl=page_impl, codec=codec(esquema))
    t.open()
    return t


def embaralhados(esquema, n, seed=1):
    recs = list(registros_fake(esquema, n, seed=seed))
    random.Random(seed).shuffle(recs)
    return recs


def test_arvore_vazia(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    t.check_invariants()
    assert t.altura() == 1 and t.num_registros() == 0
    assert t.find("numero", 1) is None
    assert list(t.scan()) == [] and list(t.find_ordered("numero")) == []
    t.close()


def test_fanout_derivado_do_bloco(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    assert t.fanout() == (bm.block_size - 8 - 4) // (8 + 4) + 1       # chave int = 8 B
    t.close()


def test_10000_insercoes_aleatorias(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    recs = embaralhados(TURMA, 10_000)
    for i, r in enumerate(recs, 1):
        assert isinstance(t.insert(r), RID)
        if i % 500 == 0:
            t.check_invariants()
    t.check_invariants()
    assert t.num_registros() == 10_000
    # busca de todas as chaves
    for r in recs[::7]:
        rid = t.find("numero", r["numero"])
        assert rid is not None and t.read(rid) == r
    assert t.find("numero", 0) is None and t.find("numero", 10_001) is None
    # altura ≤ ⌈log_{⌈n/2⌉}(N)⌉ + 1
    n = t.fanout()
    assert t.altura() <= math.ceil(math.log(10_000, math.ceil(n / 2))) + 1
    assert t.altura() >= 2
    # varredura em ordem de chave = oráculo
    assert [r["numero"] for _, r in t.scan()] == list(range(1, 10_001))
    t.close()


def test_faixa_vs_sorted(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    recs = embaralhados(TURMA, 2_000, seed=5)
    for r in recs:
        t.insert(r)
    ordem = sorted(recs, key=lambda r: r["numero"])
    rng = random.Random(9)
    for _ in range(40):
        lo, hi = sorted((rng.randint(-5, 2_010), rng.randint(-5, 2_010)))
        for il in (True, False):
            for ih in (True, False):
                esperado = [r for r in ordem
                            if (r["numero"] > lo or (il and r["numero"] == lo))
                            and (r["numero"] < hi or (ih and r["numero"] == hi))]
                assert [r for _, r in t.find_ordered("numero", lo, hi, il, ih)] == esperado
    assert [r for _, r in t.find_ordered("numero", None, 10)] == ordem[:10]
    assert [r for _, r in t.find_ordered("numero", 1_995, None)] == ordem[1_994:]
    with pytest.raises(OperacaoNaoSuportada):
        list(t.find_ordered("semestre", 1, 2))
    t.close()


@pytest.mark.parametrize("op", ["=", "<", "<=", ">", ">="])
def test_find_all_ops(bm, page_impl, codec, op):
    import operator
    f = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}[op]
    t = nova(bm, page_impl, codec)
    recs = embaralhados(TURMA, 700, seed=2)
    for r in recs:
        t.insert(r)
    for v in (1, 350, 700, 701):
        got = sorted(r["numero"] for _, r in t.find_all("numero", op, v))
        assert got == sorted(r["numero"] for r in recs if f(r["numero"], v))
    # campo que não é a chave: filtro linear
    got = sorted(r["numero"] for _, r in t.find_all("semestre", "=", recs[0]["semestre"]))
    assert got == sorted(r["numero"] for r in recs if r["semestre"] == recs[0]["semestre"])
    t.close()


def test_chave_duplicada(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    r = next(registros_fake(TURMA, 1))
    t.insert(r)
    with pytest.raises(ChaveDuplicadaError):
        t.insert(dict(r, sala="Z-1"))
    assert t.num_registros() == 1
    t.check_invariants()
    t.close()


def test_find_cursor_em_campo_nao_chave(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    recs = embaralhados(TURMA, 300, seed=4)
    for r in recs:
        t.insert(r)
    sem = recs[0]["semestre"]
    achados, rid = [], t.find("semestre", sem)
    while rid is not None:
        achados.append(t.read(rid)["numero"])
        rid = t.find_next()
    assert sorted(achados) == sorted(r["numero"] for r in recs if r["semestre"] == sem)
    assert t.find("numero", 5) is not None and t.find_next() is None
    t.close()


def test_rid_devolvido_pelo_insert_vale_ate_o_proximo_split(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    for r in embaralhados(TURMA, 400, seed=8):
        rid = t.insert(r)
        assert t.read(rid) == r            # RID do insert aponta para o registro recém-inserido
    t.close()


def test_chave_string_e_reabrir(bm, page_impl, codec):
    t = nova(bm, page_impl, codec, ALUNO, "CPF", "alunos")
    recs = embaralhados(ALUNO, 1_500, seed=6)
    for i, r in enumerate(recs, 1):
        t.insert(r)
        if i % 500 == 0:
            t.check_invariants()
    ordem = sorted(recs, key=lambda r: r["CPF"])
    assert [r["CPF"] for _, r in t.scan()] == [r["CPF"] for r in ordem]
    t.close()
    t2 = nova(bm, page_impl, codec, ALUNO, "CPF", "alunos")          # reabre do "disco"
    t2.check_invariants()
    assert t2.num_registros() == 1_500 and t2.altura() >= 2
    assert t2.read(t2.find("CPF", ordem[700]["CPF"])) == ordem[700]
    t2.close()


def test_ocupacao_e_scan_blocos(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    for r in embaralhados(TURMA, 1_200, seed=3):
        t.insert(r)
    oc = t.ocupacao()
    assert oc["registros"] == 1_200 and oc["dados"] + oc["indice"] == oc["total"] == t.num_blocks()
    blocos = list(t.scan_blocos(toss=True))
    assert len(blocos) == oc["dados"] and sum(map(len, blocos)) == 1_200
    t.close()


def test_invariantes_detectam_corrupcao(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    for r in embaralhados(TURMA, 500, seed=7):
        t.insert(r)
    t.check_invariants()
    t._meta["nregs"] += 1                  # contagem do cabeçalho diverge das folhas
    with pytest.raises(AssertionError):
        t.check_invariants()
    t._meta["nregs"] -= 1
    t.close()
