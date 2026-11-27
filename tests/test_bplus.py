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


# =========================================================================== E06
# Esquema de teste com chave larga (char(60)) e bloco de 512 B ⇒ fan-out 8 e folhas pequenas:
# árvores profundas com poucos registros (exercita fusão/redistribuição em vários níveis).
from hypothesis import HealthCheck, given, settings, strategies as st

from src.access.contracts import Campo, Esquema
from src.common.config import load_config
from tests.conftest import bm_fake, bm_real, real_ou_fake
from tests.fakes import FakeCodec, FakeSlottedPage

ESQ = Esquema("T", (Campo("k", "char(60)"), Campo("v", "varchar(40)")), chave=("k",))


def rec(i: int, v: str | None = None) -> dict:
    return {"k": f"{i:05d}", "v": "x" * (i % 30) if v is None else v}


@pytest.fixture
def cfg512():
    return load_config("teste", overrides={"disco.block_size": 512})


@pytest.fixture
def bm512(cfg512, tmp_path, so_fakes, _buffers_sem_pins):
    b = real_ou_fake(lambda: bm_real(cfg512, tmp_path), lambda: bm_fake(cfg512), so_fakes)
    _buffers_sem_pins.append(b)
    return b


def peq(bm, unique=True, nome="t"):
    t = BPlusTree(bm, nome, ESQ, "k", unique=unique, page_impl=FakeSlottedPage, codec=FakeCodec(ESQ))
    t.open()
    return t


def test_fanout_pequeno_gera_arvore_profunda(bm512):
    t = peq(bm512)
    assert t.fanout() == 8
    for i in random.Random(1).sample(range(3000), 3000):
        t.insert(rec(i))
    t.check_invariants()
    assert t.altura() >= 4
    t.close()


@settings(max_examples=40, deadline=None, suppress_health_check=list(HealthCheck))
@given(st.lists(st.tuples(st.sampled_from("iiiduu"), st.integers(0, 250)), max_size=300))
def test_propriedade_insert_delete_update_vs_dict(ops):
    cfg = load_config("teste", overrides={"disco.block_size": 512})
    bm = bm_fake(cfg)
    t = peq(bm)
    ref: dict[int, str] = {}
    for op, i in ops:
        k = f"{i:05d}"
        if op == "i":
            if i in ref:
                with pytest.raises(ChaveDuplicadaError):
                    t.insert(rec(i))
            else:
                ref[i] = rec(i)["v"]
                t.insert(rec(i))
        elif op == "d":
            rid = t.find("k", k)
            assert (rid is not None) == (i in ref)
            if rid is not None:
                t.delete(rid)
                del ref[i]
        else:                                   # u: troca o valor (tamanho variável)
            rid = t.find("k", k)
            if rid is not None:
                novo = "y" * ((i * 7) % 40)
                r2 = t.update(rid, {"k": k, "v": novo})
                assert t.read(r2) == {"k": k, "v": novo}
                ref[i] = novo
        t.check_invariants()
        assert t.num_registros() == len(ref)
    assert [(r["k"], r["v"]) for _, r in t.scan()] == [(f"{i:05d}", ref[i]) for i in sorted(ref)]
    t.close()
    bm.assert_no_pins()


def test_remover_tudo_deixa_arvore_vazia_valida(bm512):
    t = peq(bm512)
    ids = list(range(2000))
    random.Random(2).shuffle(ids)
    for i in ids:
        t.insert(rec(i))
    altura_cheia = t.altura()
    random.Random(3).shuffle(ids)
    for j, i in enumerate(ids, 1):
        t.delete(t.find("k", f"{i:05d}"))
        if j % 100 == 0:
            t.check_invariants()
        if j == 1900:
            assert t.altura() < altura_cheia            # a altura encolhe
    t.check_invariants()
    assert t.altura() == 1 and t.num_registros() == 0 and t.num_blocks() == 1
    assert list(t.scan()) == [] and t.find("k", "00001") is None
    t.insert(rec(7))                                    # continua utilizável
    t.check_invariants()
    assert [r["k"] for _, r in t.scan()] == ["00007"]
    t.close()


def test_delete_rid_invalido(bm512):
    t = peq(bm512)
    for i in range(100):
        t.insert(rec(i))
    rid = t.find("k", "00050")
    t.delete(rid)
    assert t.find("k", "00050") is None and t.num_registros() == 99
    with pytest.raises(KeyError):
        t.delete(RID(rid.bloco, 10_000))                # slot fora da folha
    with pytest.raises(KeyError):
        t.delete(RID(9999, 0))                          # bloco inexistente
    t.check_invariants()
    t.close()


def test_update_no_lugar_e_com_mudanca_de_chave(bm512):
    t = peq(bm512)
    for i in range(300):
        t.insert(rec(i))
    rid = t.find("k", "00100")
    assert t.update(rid, rec(100, "novo")) == rid       # mesma chave, cabe: mesmo RID
    assert t.read(rid)["v"] == "novo"
    novo = t.update(t.find("k", "00100"), rec(1000))    # chave mudou: remove + insere
    assert t.read(novo) == rec(1000) and t.find("k", "00100") is None
    with pytest.raises(ChaveDuplicadaError):
        t.update(t.find("k", "00001"), rec(2))
    assert t.find("k", "00001") is not None             # nada foi perdido na tentativa
    # encolher muito os registros pode deixar a folha abaixo do mínimo: a árvore se ajusta
    for i in range(300):
        rid = t.find("k", f"{i:05d}")
        if rid is not None:
            t.update(rid, {"k": f"{i:05d}", "v": ""})
        t.check_invariants()
    t.close()


# ---------------------------------------------------------------------------- NOT UNIQUE
def dup(i: int, chave: int) -> dict:
    return {"k": f"{chave:05d}", "v": f"{i:05d}"}


def test_not_unique_mil_duplicatas(bm512):
    t = peq(bm512, unique=False)
    seq = [dup(i, 5 if i % 3 == 0 else i + 10) for i in range(3000)]      # 1000 com chave 5
    random.Random(4).shuffle(seq)
    for j, r in enumerate(seq, 1):
        t.insert(r)
        if j % 500 == 0:
            t.check_invariants()
    ordem_ins = [r["v"] for r in seq if r["k"] == "00005"]
    assert len(ordem_ins) == 1000
    # find_all devolve todas, na ordem de inserção
    assert [r["v"] for _, r in t.find_all("k", "=", "00005")] == ordem_ins
    # find/find_next percorrem todas
    vistos, rid = [], t.find("k", "00005")
    while rid is not None:
        vistos.append(t.read(rid)["v"])
        rid = t.find_next()
    assert vistos == ordem_ins
    # faixas e varredura
    menores = sum(1 for r in seq if r["k"] < "00005")
    assert sum(1 for _ in t.find_all("k", ">", "00005")) == 3000 - 1000 - menores
    assert sum(1 for _ in t.find_all("k", "<", "00005")) == menores
    assert sum(1 for _ in t.find_ordered("k", "00005", "00005", False, True)) == 0
    assert sum(1 for _ in t.find_ordered("k", "00005", "00005", True, True)) == 1000
    assert [r["k"] for _, r in t.scan()] == sorted(r["k"] for r in seq)
    # remove 400 duplicatas (sempre a primeira)
    for _ in range(400):
        t.delete(t.find("k", "00005"))
    t.check_invariants()
    assert [r["v"] for _, r in t.find_all("k", "=", "00005")] == ordem_ins[400:]
    t.close()


def test_not_unique_reabrir_preserva_uniquificador(bm512):
    t = peq(bm512, unique=False)
    for i in range(50):
        t.insert(dup(i, 1))
    t.close()
    t = peq(bm512, unique=False)
    for i in range(50, 100):
        t.insert(dup(i, 1))
    assert [r["v"] for _, r in t.find_all("k", "=", "00001")] == [f"{i:05d}" for i in range(100)]
    t.check_invariants()
    t.close()


def test_modo_unique_diferente_do_arquivo(bm512):
    peq(bm512, unique=False).close()
    with pytest.raises(ValueError):
        peq(bm512, unique=True)


# ---------------------------------------------------------------------------- bulk load
def test_bulk_load_20000(bm, page_impl, codec):
    t = nova(bm, page_impl, codec)
    recs = list(registros_fake(TURMA, 20_000, seed=11))
    t.bulk_load(recs, fill=0.8)
    t.check_invariants()
    assert t.num_registros() == 20_000
    nfolhas = t.ocupacao()["dados"]
    cap = math.ceil(0.8 * t.fanout())
    assert t.altura() <= math.ceil(math.log(nfolhas, cap)) + 1                 # altura mínima
    cd = codec(TURMA)
    total = sum(len(cd.encode(r)) + 4 for r in recs)
    assert 0.7 <= total / (nfolhas * t.C) <= 0.85                              # ocupação ≈ fill
    assert [r["numero"] for _, r in t.scan()] == list(range(1, 20_001))
    for r in recs[::499]:
        assert t.read(t.find("numero", r["numero"])) == r
    for i in range(20_001, 20_200):                      # depois da carga aceita inserções/remoções
        t.insert(dict(recs[0], numero=i))
    for r in recs[:150]:
        t.delete(t.find("numero", r["numero"]))
    t.check_invariants()
    assert t.num_registros() == 20_000 + 199 - 150
    t.close()


@pytest.mark.parametrize("fill", [0.5, 0.8, 1.0])
def test_bulk_load_tamanhos_pequenos(bm512, fill):
    for n in list(range(0, 40)) + [100, 257, 600]:
        t = peq(bm512, nome=f"b{n}_{int(fill * 10)}")
        t.bulk_load([rec(i) for i in range(n)], fill=fill)
        t.check_invariants()
        assert t.num_registros() == n
        assert [r["k"] for _, r in t.scan()] == [f"{i:05d}" for i in range(n)]
        t.close()


def test_bulk_load_erros(bm512):
    t = peq(bm512, nome="a")
    with pytest.raises(ValueError):
        t.bulk_load([rec(2), rec(1)])                   # fora de ordem
    t = peq(bm512, nome="b")
    with pytest.raises(ValueError):
        t.bulk_load([rec(1), rec(1)])                   # duplicada (UNIQUE)
    t = peq(bm512, nome="c")
    t.insert(rec(1))
    with pytest.raises(ValueError):
        t.bulk_load([rec(5)])                           # árvore não vazia
    t.close()


def test_bulk_load_not_unique(bm512):
    t = peq(bm512, unique=False)
    seq = sorted((dup(i, i % 40) for i in range(1200)), key=lambda r: r["k"])
    t.bulk_load(seq)
    t.check_invariants()
    assert sum(1 for _ in t.find_all("k", "=", "00007")) == 30
    t.insert(dup(5000, 7))
    assert [r["v"] for _, r in t.find_all("k", "=", "00007")][-1] == "05000"
    t.check_invariants()
    t.close()


# ---------------------------------------------------------------------------- reorganize
def test_reorganize_compacta_e_preserva(bm512):
    t = peq(bm512)
    ids = list(range(2500))
    random.Random(5).shuffle(ids)
    for i in ids:
        t.insert(rec(i))
    for i in ids[:1800]:
        t.delete(t.find("k", f"{i:05d}"))
    antes = t.num_blocks()
    restantes = sorted(ids[1800:])
    t.reorganize()
    t.check_invariants()
    assert [r["k"] for _, r in t.scan()] == [f"{i:05d}" for i in restantes]
    assert t.num_blocks() <= antes
    assert not bm512.exists("t.reorg")                  # temporária removida
    t.close()


def test_reorganize_vazia_e_not_unique(bm512):
    t = peq(bm512)
    t.reorganize()
    t.check_invariants()
    assert t.num_registros() == 0
    t.close()
    u = peq(bm512, unique=False, nome="nu")
    for i in range(400):
        u.insert(dup(i, i % 7))
    esperado = [(r["k"], r["v"]) for _, r in u.scan()]
    u.reorganize()
    u.check_invariants()
    assert [(r["k"], r["v"]) for _, r in u.scan()] == esperado
    u.insert(dup(999, 3))                               # uniquificadores continuam crescendo
    u.check_invariants()
    u.close()
