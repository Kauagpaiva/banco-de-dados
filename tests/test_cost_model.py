"""Testes do modelo de custo (M6/E13): números de exemplo do Silberschatz (REFERENCIA_LIVRO §6–7)."""
import math

import pytest

from src.access.contracts import InfoIndice, InfoTabela
from src.access.esquemas import ALUNO, INSCRICAO
from src.bench.cost_model import (comparar, custo_bnl, custo_hash_join, custo_inl, custo_selecao,
                                  custo_smj, custo_sort, detalhar_hash_join)


def tab(nome="t", br=0, nr=0, fr=0.0, V=None, esquema=ALUNO, params=None, org="heap"):
    return InfoTabela(nome=nome, esquema=esquema, org=org, nr=nr, br=br, fr=fr, V=V or {},
                      params=params or {})


def idx(tipo="bplus", unique=True, altura=4, clustering=False, primario=False, params=None,
        campo="id"):
    return InfoIndice(nome="i", tabela="t", campo=campo, tipo=tipo, unique=unique,
                      clustering=clustering, primario=primario, altura=altura, params=params or {})


# Relações do livro: student (b=100, n=5000), takes (b=400, n=10000), fr = 50 e 25.
STUDENT = tab("student", br=100, nr=5000, fr=50, esquema=ALUNO)
TAKES = tab("takes", br=400, nr=10000, fr=25, esquema=INSCRICAO, V={"id": 5000})


# ------------------------------------------------------------------ exemplos do livro
def test_sort_exemplo_livro():
    # br=12, M=3, bb=1 → 60 transferências, 44 seeks (pág. 704)
    assert custo_sort(12, 3, 1) == {"transferencias": 60, "seeks": 44}


def test_bnl_exemplo_livro_pior_caso():
    # student ⋈ takes, student externa, M=3 → 40 100 transferências, 200 seeks (pág. 707)
    assert custo_bnl(STUDENT, TAKES, 3) == {"transferencias": 40100, "seeks": 200}


def test_bnl_melhor_caso_interna_cabe():
    assert custo_bnl(TAKES, STUDENT, 102) == {"transferencias": 500, "seeks": 2}


def test_bnl_com_M():
    # ⌈100/(12−2)⌉ = 10 → 10·400 + 100 = 4 100; 20 seeks
    assert custo_bnl(STUDENT, TAKES, 12) == {"transferencias": 4100, "seeks": 20}


def test_inl_exemplo_livro():
    # student externa, índice B+ em takes com hi=4 (c = hi+1 = 5): 100 + 5000·5 = 25 100
    i = idx(altura=4, unique=True)
    assert custo_inl(STUDENT, TAKES, i)["transferencias"] == 25100
    assert custo_inl(STUDENT, TAKES, i, c={"transferencias": 5, "seeks": 5})["seeks"] == 25100


def test_inl_nao_unico_usa_V():
    # takes.id não-único, V=5000 → sc = 2 tuplas por busca, A4: hi + n = 4 + 2 = 6
    i = idx(altura=4, unique=False)
    assert custo_inl(STUDENT, TAKES, i) == {"transferencias": 100 + 5000 * 6, "seeks": 100 + 5000 * 6}


def test_smj_exemplo_livro_M3():
    # pág. 711: 9 100 transferências; seeks = 6 668 + 1 268 + 500 = 8 436 (o texto diz 8 932: erro de soma)
    c = custo_smj(TAKES, STUDENT, 3, 1)
    assert c["transferencias"] == 9100
    assert c["seeks"] == 6668 + 1268 + 500 == 8436


def test_smj_exemplo_livro_M25():
    assert custo_smj(TAKES, STUDENT, 25, 1) == {"transferencias": 2500, "seeks": 1640}


def test_smj_entradas_ordenadas():
    c = custo_smj(TAKES, STUDENT, 3, 4, ordenado_r=True, ordenado_s=True)
    assert c == {"transferencias": 500, "seeks": 100 + 25}


def test_hash_join_exemplo_livro():
    # takes ⋈ student (student = build), M=20, bb=3 → 1 500 transf., 336 seeks ignorando blocos parciais
    d = detalhar_hash_join(TAKES, STUDENT, 20, 3)
    assert d["modo"] == "simples" and d["nh"] == 5
    assert d["transferencias"] - d["parciais_transf"] == 1500
    assert d["seeks"] - d["parciais_seeks"] == 336
    assert custo_hash_join(TAKES, STUDENT, 20, 3) == {"transferencias": 1520, "seeks": 346}


def test_hash_join_build_em_memoria():
    assert custo_hash_join(TAKES, STUDENT, 102) == {"transferencias": 500, "seeks": 2}


def test_hash_join_recursivo():
    # M=5, bb=1: nh = ⌈100/5⌉ = 20 ≥ M → recursão; ⌈log_4(100/5)⌉ = 3
    c = custo_hash_join(TAKES, STUDENT, 5, 1)
    assert c == {"transferencias": 2 * 500 * 3 + 500, "seeks": 2 * 500 * 3}
    assert detalhar_hash_join(TAKES, STUDENT, 5, 1)["modo"] == "recursivo"


# ------------------------------------------------------------------ seleção (Fig. 15.3)
def test_selecao_linear():
    assert custo_selecao("A1_linear", STUDENT) == {"transferencias": 100, "seeks": 1}
    assert custo_selecao("A1_chave", STUDENT) == {"transferencias": 50, "seeks": 1}


def test_selecao_A2_e_organizacao_bplus():
    assert custo_selecao("A2", STUDENT, indice=idx(altura=3, clustering=True)) == \
        {"transferencias": 4, "seeks": 4}
    # organização B+: registro está na folha → economiza 1 acesso
    assert custo_selecao("A2", STUDENT, indice=idx(altura=3, primario=True)) == \
        {"transferencias": 3, "seeks": 3}


def test_selecao_A3_A5():
    # hi=3, sc=120 tuplas, fr=50 → b=3: 3+3 transf., 3+1 seeks
    for cam in ("A3", "A5"):
        assert custo_selecao(cam, STUDENT, indice=idx(altura=3, unique=False, clustering=True),
                             sc=120) == {"transferencias": 6, "seeks": 4}


def test_selecao_A4_A6():
    assert custo_selecao("A4", STUDENT, indice=idx(altura=3)) == {"transferencias": 4, "seeks": 4}
    assert custo_selecao("A4", STUDENT, indice=idx(altura=3, unique=False), sc=10) == \
        {"transferencias": 13, "seeks": 13}
    assert custo_selecao("A6", STUDENT, indice=idx(altura=3), sc=10) == \
        {"transferencias": 13, "seeks": 13}


def test_selecao_hash_com_overflow():
    i = idx(tipo="hash", altura=1, primario=True, params={"cadeia_media": 0.5})
    assert custo_selecao("HASH_PRIM", STUDENT, indice=i) == {"transferencias": 1.5, "seeks": 1.5}
    j = idx(tipo="hash", altura=1, params={"cadeia_media": 0.25})
    assert custo_selecao("HASH_SEC", STUDENT, indice=j) == {"transferencias": 2.25, "seeks": 2.25}


def test_selecao_erros():
    with pytest.raises(ValueError):
        custo_selecao("A2", STUDENT)
    with pytest.raises(ValueError):
        custo_selecao("XYZ", STUDENT, indice=idx())


# ------------------------------------------------------------------ casos de borda
def test_sort_cabe_em_memoria_e_vazio():
    assert custo_sort(3, 3) == {"transferencias": 3, "seeks": 1}
    assert custo_sort(0, 3) == {"transferencias": 0, "seeks": 0}


def test_sort_memoria_insuficiente():
    with pytest.raises(ValueError):
        custo_sort(100, 3, 2)   # ⌊3/2⌋−1 = 0


def test_sort_passos_sem_erro_de_ponto_flutuante():
    # b/M exatamente potência da base: 4·3 = 12 blocos, base 2 → log2(4) = 2 passos (não 3)
    assert custo_sort(12, 3)["transferencias"] == 12 * 5
    # 8 runs, base 2 → 3 passos
    assert custo_sort(24, 3)["transferencias"] == 24 * 7


# ------------------------------------------------------------------ comparar
def test_comparar():
    d = comparar({"transferencias": 110, "seeks": 2, "reads": 99}, {"transferencias": 100, "seeks": 2})
    assert d["dif_abs_transf"] == 10 and d["dif_rel_transf"] == pytest.approx(0.1)
    assert d["dif_abs_seeks"] == 0 and d["dif_rel_seeks"] == 0
    z = comparar({"transferencias": 0, "seeks": 3}, {"transferencias": 0, "seeks": 0})
    assert z["dif_rel_transf"] == 0 and math.isinf(z["dif_rel_seeks"])
