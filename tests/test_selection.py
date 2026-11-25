"""E10 (M5): seleção — todos os caminhos de CAMINHOS_SELECAO × seletividade {1%, 50%}.

Oráculo: filtro em Python sobre a lista de registros inseridos (a referência SQLite é do M7;
a validação contra SQLite fica para o M10). Comparação por multiconjunto.

Organizações primárias B+/hash ainda não estão em `main` (M3/M4): `OrgOrdenadaFake` e
`OrgHashFake` abaixo simulam só a *interface* que a seleção usa (tipo_org, campo, unique,
find_ordered / find+find_next). Heap usa a fixture `tabela` (FakeTable ou HeapFile real).
"""
from __future__ import annotations

from collections import Counter

import pytest

from src.access.esquemas import ALUNO
from src.common.erros import OperacaoNaoSuportada
from src.common.tipos import CAMINHOS_SELECAO, CHAVES_STATS, Predicado
from src.executor.contracts import AccessMethod
from src.executor.selection import select
from tests.fakes import FakeIndex, FakeTable, registros_fake

N = 400                       # Aluno com N registros: 1% = 4 tuplas, 50% = 200


# =========================================================================== dados
def _registros() -> list[dict]:
    regs = []
    for i, r in enumerate(registros_fake(ALUNO, N, seed=7)):
        r["cod_curso"] = i % 100                  # igualdade 1% (NOT UNIQUE)
        r["sexo"] = "MF"[i % 2]                   # igualdade 50% (NOT UNIQUE)
        r["CR"] = round((i * 37 % N) / 40, 3)     # valores distintos 0..9.975 (faixas exatas)
        regs.append(r)
    return regs


REGS = _registros()
CR_1 = sorted(r["CR"] for r in REGS)[N // 100]    # CR < CR_1  → 1%
CR_50 = sorted(r["CR"] for r in REGS)[N // 2]     # CR >= CR_50 → 50%


def _multiconjunto(regs) -> Counter:
    return Counter(repr(sorted(r.items())) for r in regs)


def _esperado(pred: Predicado) -> list[dict]:
    return [r for r in REGS if pred.avaliar(r)]


# =========================================================================== fakes de org.
class OrgOrdenadaFake(FakeTable):
    """Simula a interface de uma B+ primária (só teste): `find_ordered` em ordem de campo."""
    tipo_org = "bplus"

    def __init__(self, *a, campo: str, unique: bool, **k):
        super().__init__(*a, **k)
        self.campo, self.unique = campo, unique

    def find_ordered(self, campo, lo=None, hi=None, incl_lo=True, incl_hi=True):
        if campo != self.campo:
            raise OperacaoNaoSuportada("ordem só no campo da organização")

        def dentro(v):
            if v is None:
                return False
            if lo is not None and (v < lo or (v == lo and not incl_lo)):
                return False
            if hi is not None and (v > hi or (v == hi and not incl_hi)):
                return False
            return True
        pares = [(rid, r) for rid, r in self.scan() if dentro(r[campo])]
        return iter(sorted(pares, key=lambda p: p[1][campo]))


class OrgHashFake(FakeTable):
    """Simula a interface de um hash primário (só teste): `find`/`find_next`/`read`."""
    tipo_org = "hash"

    def __init__(self, *a, campo: str, unique: bool, **k):
        super().__init__(*a, **k)
        self.campo, self.unique = campo, unique


# =========================================================================== fixtures
@pytest.fixture
def heap(tabela):
    return tabela("Aluno", registros=[dict(r) for r in REGS])


@pytest.fixture
def montar(ctx, page_impl, codec):
    """`montar(org, campo_org, unique, indices={campo: (unique, refs_por_chave)}, tabela=None)`."""
    cont = {"n": 0}

    def fabrica(org="heap", campo=None, unique=False, indices=None, tabela=None):
        cont["n"] += 1
        nome = f"Aluno_{org}_{cont['n']}"
        if tabela is None:
            cls = {"heap": FakeTable, "bplus": OrgOrdenadaFake, "hash": OrgHashFake}[org]
            kw = {} if org == "heap" else {"campo": campo, "unique": unique}
            tabela = cls(ctx.bm, nome, ALUNO, page_impl=page_impl, codec=codec(ALUNO), **kw)
            tabela.open()
            rids = [tabela.insert(dict(r)) for r in REGS]
        else:
            rids = [rid for rid, _ in tabela.scan()]
        idxs = {}
        for c, (u, por_chave) in (indices or {}).items():
            ix = FakeIndex(ctx.bm, f"{nome}_ix_{c}", ALUNO.campo(c), unique=u,
                           refs_por_chave=por_chave)
            ix.open()
            for rid, r in zip(rids, tabela_registros(tabela, rids)):
                if r[c] is not None:
                    chave = tabela.campo or ALUNO.chave[0]   # heap não tem campo de org.
                    ix.insert(r[c], r[chave] if por_chave else rid)
            idxs[c] = ix
        return AccessMethod(tabela, idxs, f"{org}:{campo}")
    return fabrica


def tabela_registros(tabela, rids):
    return [tabela.read(rid) for rid in rids]


def _rodar(ctx, am, pred, caminho, frio=True):
    if frio:
        ctx.drop_all()
        ctx.reset_stats()
    it, met = select(ctx, am, pred, caminho)
    res = list(it)
    return res, met


def _conferir(ctx, am, pred, caminho):
    res, met = _rodar(ctx, am, pred, caminho)
    esp = _esperado(pred)
    assert _multiconjunto(res) == _multiconjunto(esp), f"{caminho} {pred}"
    assert met["tuplas_saida"] == len(res)
    assert set(CHAVES_STATS) <= set(met)
    ctx.bm.assert_no_pins()
    return res, met


# =========================================================================== casos válidos
SEL = {                                   # (predicado) por seletividade
    "igual_nao_unique": {"1%": Predicado("cod_curso", "=", 7),
                         "50%": Predicado("sexo", "=", "M")},
    "faixa_nao_unique": {"1%": Predicado("CR", "<", CR_1),
                         "50%": Predicado("CR", ">=", CR_50)},
    "faixa_unique": {"1%": Predicado("DRE", "<=", N // 100),
                     "50%": Predicado("DRE", ">", N // 2)},
}


@pytest.mark.parametrize("sel", ["1%", "50%"])
@pytest.mark.parametrize("tipo", list(SEL))
def test_A1_linear_campo_sem_indice(ctx, heap, sel, tipo):
    am = AccessMethod(heap)
    pred = SEL[tipo][sel]
    res, met = _conferir(ctx, am, pred, "A1_linear")
    assert len(res) in (N // 100, N // 2)
    # varredura completa com buffer frio: 1 leitura por bloco (± cabeçalho)
    assert heap.num_blocks() <= met["reads"] <= heap.num_blocks() + 1


@pytest.mark.parametrize("dre", [1, N // 2, N, N + 1000])
def test_A1_chave_para_no_primeiro(ctx, heap, dre):
    am = AccessMethod(heap)
    pred = Predicado("DRE", "=", dre)
    res, met = _conferir(ctx, am, pred, "A1_chave")
    assert len(res) == (1 if dre <= N else 0)
    if dre == 1:
        assert met["requests"] == 1          # achou no 1º bloco e parou (média br/2)
    if dre > N:
        assert met["requests"] == heap.num_blocks()   # pior caso: br


@pytest.mark.parametrize("sel", ["1%", "50%"])
@pytest.mark.parametrize("caminho,pred_de", [
    ("A4", lambda sel: SEL["igual_nao_unique"][sel]),
    ("A6", lambda sel: SEL["faixa_nao_unique"][sel]),
    ("A6", lambda sel: SEL["faixa_unique"][sel]),
])
def test_indice_secundario_rid(ctx, montar, sel, caminho, pred_de):
    am = montar("heap", indices={"cod_curso": (False, False), "sexo": (False, False),
                                 "CR": (False, False), "DRE": (True, False)})
    pred = pred_de(sel)
    res, met = _conferir(ctx, am, pred, caminho)     # stats zeradas antes da operação
    # cada ref custa 1 acesso ao arquivo de dados (15.2: A4/A6 não clustering)
    assert ctx.buffer_stats()["por_area"]["dados"]["requests"] == len(res)
    assert met["requests"] >= len(res)


@pytest.mark.parametrize("caminho", ["A4", "HASH_SEC"])
def test_igualdade_em_indice_unique(ctx, montar, caminho):
    am = montar("heap", indices={"DRE": (True, False)})
    res, met = _conferir(ctx, am, Predicado("DRE", "=", 123), caminho)
    assert len(res) == 1
    res, _ = _conferir(ctx, am, Predicado("DRE", "=", N + 5), caminho)
    assert res == []


@pytest.mark.parametrize("sel", ["1%", "50%"])
def test_indice_secundario_refs_por_chave(ctx, montar, sel):
    """14.4.2: índice secundário sobre organização B+ guarda a chave primária, não o RID."""
    am = montar("bplus", "DRE", True, indices={"cod_curso": (False, True), "sexo": (False, True),
                                               "CR": (False, True)})
    _conferir(ctx, am, SEL["igual_nao_unique"][sel], "A4")
    _conferir(ctx, am, SEL["faixa_nao_unique"][sel], "A6")


def test_A2_igualdade_chave_bplus(ctx, montar):
    am = montar("bplus", "DRE", True)
    res, _ = _conferir(ctx, am, Predicado("DRE", "=", 77), "A2")
    assert len(res) == 1
    res, _ = _conferir(ctx, am, Predicado("DRE", "=", -1), "A2")
    assert res == []


@pytest.mark.parametrize("sel", ["1%", "50%"])
def test_A3_igualdade_nao_chave_bplus(ctx, montar, sel):
    campo = "cod_curso" if sel == "1%" else "sexo"
    am = montar("bplus", campo, False)
    _conferir(ctx, am, SEL["igual_nao_unique"][sel], "A3")


@pytest.mark.parametrize("sel", ["1%", "50%"])
@pytest.mark.parametrize("org_campo,unique,tipo", [
    ("DRE", True, "faixa_unique"), ("CR", False, "faixa_nao_unique"),
])
def test_A5_comparacao_bplus(ctx, montar, sel, org_campo, unique, tipo):
    am = montar("bplus", org_campo, unique)
    res, _ = _conferir(ctx, am, SEL[tipo][sel], "A5")
    valores = [r[org_campo] for r in res]
    assert valores == sorted(valores)        # saída em ordem do campo (folhas encadeadas)


@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
def test_A5_todos_operadores(ctx, montar, op):
    am = montar("bplus", "DRE", True)
    _conferir(ctx, am, Predicado("DRE", op, N // 3), "A5")


@pytest.mark.parametrize("sel", ["1%", "50%"])
def test_HASH_PRIM(ctx, montar, sel):
    if sel == "1%":
        am = montar("hash", "cod_curso", False)
    else:
        am = montar("hash", "sexo", False)
    _conferir(ctx, am, SEL["igual_nao_unique"][sel], "HASH_PRIM")


def test_HASH_PRIM_unique(ctx, montar):
    am = montar("hash", "DRE", True)
    res, _ = _conferir(ctx, am, Predicado("DRE", "=", 250), "HASH_PRIM")
    assert len(res) == 1


def test_campo_nulo_nunca_satisfaz(ctx, heap):
    am = AccessMethod(heap)
    pred = Predicado("prof_orientador", ">=", "")
    res, _ = _conferir(ctx, am, pred, "A1_linear")
    assert all(r["prof_orientador"] is not None for r in res)


# =========================================================================== métricas / pins
def test_metricas_preenchidas_ao_fechar_no_meio(ctx, heap):
    it, met = select(ctx, AccessMethod(heap), Predicado("sexo", "=", "M"), "A1_linear")
    next(it)
    next(it)
    it.close()
    assert met["tuplas_saida"] == 2
    assert met["requests"] >= 1
    ctx.bm.assert_no_pins()


def test_iterador_preguicoso_nao_faz_io_antes_de_consumir(ctx, heap):
    ctx.drop_all()
    ctx.reset_stats()
    it, met = select(ctx, AccessMethod(heap), Predicado("sexo", "=", "M"), "A1_linear")
    assert ctx.buffer_stats()["requests"] == 0
    assert met["tuplas_saida"] == 0
    it.close()


def test_metricas_somente_da_operacao(ctx, heap):
    am = AccessMethod(heap)
    _, met1 = _rodar(ctx, am, Predicado("DRE", "=", 1), "A1_chave")
    _, met2 = _rodar(ctx, am, Predicado("DRE", "=", 1), "A1_chave", frio=False)
    assert met1["misses"] == 1
    assert met2["misses"] == 0 and met2["hits"] == 1     # buffer quente: hit


# =========================================================================== combinações inválidas
@pytest.mark.parametrize("org,campo,unique,indices,pred,caminho", [
    ("heap", None, False, None, Predicado("DRE", "=", 1), "XYZ"),
    ("heap", None, False, None, Predicado("inexistente", "=", 1), "A1_linear"),
    ("heap", None, False, None, Predicado("DRE", "!=", 1), "A1_linear"),
    ("heap", None, False, None, Predicado("cod_curso", "=", 1), "A1_chave"),
    ("heap", None, False, None, Predicado("DRE", "<", 10), "A1_chave"),
    ("heap", None, False, None, Predicado("DRE", "=", 1), "A2"),
    ("heap", None, False, None, Predicado("DRE", "<", 1), "A5"),
    ("bplus", "DRE", True, None, Predicado("DRE", "<", 3), "A2"),
    ("bplus", "cod_curso", False, None, Predicado("cod_curso", "=", 3), "A2"),
    ("bplus", "DRE", True, None, Predicado("cod_curso", "=", 3), "A3"),
    ("bplus", "DRE", True, None, Predicado("DRE", "=", 3), "A5"),
    ("bplus", "DRE", True, None, Predicado("DRE", "=", 3), "HASH_PRIM"),
    ("hash", "DRE", True, None, Predicado("DRE", "<", 3), "HASH_PRIM"),
    ("hash", "DRE", True, None, Predicado("DRE", "=", 3), "A2"),
    ("heap", None, False, None, Predicado("cod_curso", "=", 3), "A4"),
    ("heap", None, False, {"CR": (False, False)}, Predicado("CR", "=", 3.0), "A6"),
    ("heap", None, False, {"CR": (False, False)}, Predicado("CR", "<", 3.0), "A4"),
    ("heap", None, False, {"CR": (False, False)}, Predicado("CR", "<", 3.0), "HASH_SEC"),
    ("heap", None, False, {"CR": (False, True)}, Predicado("CR", "<", 3.0), "A6"),
])
def test_combinacao_invalida_ValueError_sem_io(ctx, montar, org, campo, unique, indices, pred,
                                               caminho):
    am = montar(org, campo, unique, indices)
    ctx.reset_stats()
    with pytest.raises(ValueError):
        select(ctx, am, pred, caminho)
    assert ctx.buffer_stats()["requests"] == 0
    ctx.bm.assert_no_pins()


def test_todos_os_caminhos_cobertos():
    cobertos = {"A1_linear", "A1_chave", "A2", "A3", "A4", "A5", "A6", "HASH_PRIM", "HASH_SEC"}
    assert cobertos == set(CAMINHOS_SELECAO)
