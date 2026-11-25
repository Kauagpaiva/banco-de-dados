"""E11 (M5): block nested-loop (15.5.2) e indexed nested-loop (15.5.3).

Oráculo: junção por laço aninhado em Python sobre as listas de registros (a referência
SQLite é do M7; validação contra SQLite fica para o M10). Comparação por multiconjunto.
"""
from __future__ import annotations

import math
import random
from collections import Counter

import pytest

from src.access.esquemas import ALUNO, INSCRICAO, TURMA
from src.common.config import load_config
from src.common.erros import MemoryBudgetError
from src.common.tipos import CHAVES_STATS, CondJuncao
from src.executor import join_bnl as bnl_mod
from src.executor import join_inl as inl_mod
from src.executor import memory as memory_mod
from src.executor.contracts import AccessMethod, combinar
from src.executor.join_bnl import block_nested_loop
from src.executor.join_inl import indexed_nested_loop
from tests.conftest import bm_fake, bm_real, real_ou_fake
from tests.fakes import FakeIndex, FakeStorageContext, FakeTable, registros_fake
from tests.test_selection import OrgHashFake, OrgOrdenadaFake

NA, NI = 200, 1000
COND = CondJuncao("DRE", "DRE")              # Inscricao.DRE = Aluno.DRE


def _alunos(n=NA):
    regs = list(registros_fake(ALUNO, n, seed=5))
    for i, r in enumerate(regs):
        r["prof_orientador"] = None if i % 4 == 0 else f"prof{i % 13}"
    return regs


def _inscricoes(n=NI):
    rng = random.Random(9)
    regs = list(registros_fake(INSCRICAO, n, seed=6))
    for r in regs:
        r["DRE"] = rng.randint(1, NA + 50)       # parte sem par em Aluno
    return regs


def _turmas(n=60):
    regs = list(registros_fake(TURMA, n, seed=8))
    for i, r in enumerate(regs):
        r["professor"] = f"prof{i % 17}"
    return regs


ALUNOS, INSCRICOES, TURMAS = _alunos(), _inscricoes(), _turmas()


def _chave(rec):
    return repr(sorted(rec.items()))


def _oraculo(nome_r, regs_r, nome_s, regs_s, cond):
    return Counter(_chave(combinar(nome_r, a, nome_s, b)) for a in regs_r for b in regs_s
                   if a[cond.campo_r] is not None and a[cond.campo_r] == b[cond.campo_s])


def _multiconjunto(it):
    return Counter(_chave(t) for t in it)


@pytest.fixture
def rels(tabela):
    return tabela("Inscricao_Aluno_Turma", registros=INSCRICOES), tabela("Aluno", registros=ALUNOS)


@pytest.fixture
def rastreio(monkeypatch):
    picos = []

    class Rastreado(memory_mod.MemoryBudget):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.pico = 0
            picos.append(self)

        def reservar_paginas(self, n):
            super().reservar_paginas(n)
            self.pico = max(self.pico, self.paginas_em_uso)

        def reservar_paginas_io(self, n):
            super().reservar_paginas_io(n)
            self.pico = max(self.pico, self.paginas_em_uso)
    monkeypatch.setattr(bnl_mod, "MemoryBudget", Rastreado)
    monkeypatch.setattr(inl_mod, "MemoryBudget", Rastreado)
    return picos


ESPERADO = _oraculo("Inscricao_Aluno_Turma", INSCRICOES, "Aluno", ALUNOS, COND)


# =========================================================================== BNL
@pytest.mark.parametrize("M", [3, 64])
@pytest.mark.parametrize("externa", ["r", "s", "auto"])
@pytest.mark.parametrize("materializar", [False, True])
def test_bnl_igual_ao_oraculo(ctx, rels, rastreio, M, externa, materializar):
    r, s = rels
    it, m = block_nested_loop(ctx, r, s, COND, M=M, externa=externa, materializar=materializar)
    assert _multiconjunto(it) == ESPERADO
    assert m["tuplas_saida"] == sum(ESPERADO.values())
    assert set(CHAVES_STATS) <= set(m)
    if materializar:
        assert m["escrita_saida"] > 0 and m["writes"] >= m["escrita_saida"]
    else:
        assert m["escrita_saida"] == 0
    assert rastreio[0].pico == M and rastreio[0].paginas_em_uso == 0


def test_bnl_toss_e_access_method(ctx, rels):
    r, s = rels
    it, _ = block_nested_loop(ctx, AccessMethod(r), AccessMethod(s), COND, M=4, toss=True)
    assert _multiconjunto(it) == ESPERADO


def test_bnl_nulos_nao_casam(ctx, tabela):
    a, t = tabela("Aluno", registros=ALUNOS), tabela("Turma", registros=TURMAS)
    cond = CondJuncao("prof_orientador", "professor")
    it, _ = block_nested_loop(ctx, a, t, cond, M=3)
    obtido = _multiconjunto(it)
    assert obtido == _oraculo("Aluno", ALUNOS, "Turma", TURMAS, cond)
    assert sum(obtido.values()) > 0


def test_bnl_fechar_no_meio(ctx, rels):
    r, s = rels
    it, m = block_nested_loop(ctx, r, s, COND, M=3, materializar=True)
    next(it)
    it.close()                                   # autouse verifica que nada ficou pinado
    assert m["tuplas_saida"] == 1


@pytest.mark.parametrize("kw", [{"M": 2}, {"externa": "x"}])
def test_bnl_parametros_invalidos(ctx, rels, kw):
    r, s = rels
    with pytest.raises(ValueError):
        block_nested_loop(ctx, r, s, COND, **kw)
    with pytest.raises(ValueError):
        block_nested_loop(ctx, r, s, CondJuncao("DRE", "nao_existe"), M=3)
    with pytest.raises(MemoryBudgetError):
        block_nested_loop(ctx, r, s, COND, M=10_000)


# --------------------------------------------------------------------------- custo da interna
def _ctx_pequeno(tmp_path, so_fakes, regs_buffers, M, dados):
    cfg = load_config(overrides={"buffer.areas.trabalho": M, "buffer.areas.dados": dados,
                                 "buffer.total_pages": 8 + 64 + dados + M})
    bm = real_ou_fake(lambda: bm_real(cfg, tmp_path), lambda: bm_fake(cfg), so_fakes)
    regs_buffers.append(bm)
    return FakeStorageContext(cfg, bm=bm)


def _carregar(bm, nome, esquema, regs):
    t = FakeTable(bm, nome, esquema)
    t.open()
    for r in regs:
        t.insert(r)
    return t


@pytest.mark.parametrize("M", [3, 6])
def test_bnl_transferencias_da_interna(tmp_path, so_fakes, _buffers_sem_pins, M):
    """Buffer frio, área 'dados' menor que a interna, LRU: leituras em 'dados' =
    br + ⌈br/(M−2)⌉·bs (cabeçalhos não passam pelo buffer)."""
    ctx = _ctx_pequeno(tmp_path, so_fakes, _buffers_sem_pins, M, dados=4)
    r = _carregar(ctx.bm, "insc", INSCRICAO, INSCRICOES)
    s = _carregar(ctx.bm, "alu", ALUNO, ALUNOS)
    br, bs = r.num_blocks(), s.num_blocks()
    assert bs > 4
    ctx.drop_all()
    ctx.reset_stats()
    it, m = block_nested_loop(ctx, r, s, COND, M=M, externa="r")
    assert _multiconjunto(it) == ESPERADO
    lidos = ctx.buffer_stats()["por_area"]["dados"]["misses"]
    assert lidos == br + math.ceil(br / (M - 2)) * bs
    assert m["reads"] >= lidos
    ctx.close()


def test_bnl_mru_e_toss_reduzem_leituras_da_interna(tmp_path, so_fakes, _buffers_sem_pins):
    """15.5.2/13.5.1: varredura repetida da interna maior que a área — LRU não aproveita
    nada; MRU mantém parte da interna entre varreduras."""
    leituras = {}
    for politica, toss in [("LRU", False), ("MRU", False), ("LRU", True)]:
        ctx = _ctx_pequeno(tmp_path / f"{politica}{toss}", so_fakes, _buffers_sem_pins, 3,
                           dados=8)
        r = _carregar(ctx.bm, "insc", INSCRICAO, INSCRICOES)
        s = _carregar(ctx.bm, "alu", ALUNO, ALUNOS)
        ctx.drop_all()
        ctx.set_policy("dados", politica)
        ctx.reset_stats()
        it, _ = block_nested_loop(ctx, r, s, COND, M=3, externa="r", toss=toss)
        assert _multiconjunto(it) == ESPERADO
        leituras[(politica, toss)] = ctx.buffer_stats()["por_area"]["dados"]["misses"]
        ctx.close()
    assert leituras[("MRU", False)] < leituras[("LRU", False)]
    assert leituras[("LRU", True)] < leituras[("LRU", False)]


# =========================================================================== INL
def _am_indice(ctx, tabela_s, campo, unique):
    ix = FakeIndex(ctx.bm, f"{tabela_s.nome}_ix_{campo}", campo, unique=unique)
    ix.open()
    for rid, rec in tabela_s.scan():
        if rec[campo] is not None:
            ix.insert(rec[campo], rid)
    return AccessMethod(tabela_s, {campo: ix})


def _org(ctx, cls, campo, unique, esquema, regs):
    t = cls(ctx.bm, f"{cls.__name__}_{campo}", esquema, campo=campo, unique=unique)
    t.open()
    for r in regs:
        t.insert(r)
    return AccessMethod(t)


@pytest.mark.parametrize("M", [3, 64])
@pytest.mark.parametrize("materializar", [False, True])
@pytest.mark.parametrize("estrutura", ["indice", "bplus", "hash"])
def test_inl_igual_ao_oraculo(ctx, rels, rastreio, M, materializar, estrutura):
    r, s = rels
    if estrutura == "indice":
        am = _am_indice(ctx, s, "DRE", unique=True)
    elif estrutura == "bplus":
        am = _org(ctx, OrgOrdenadaFake, "DRE", True, ALUNO, ALUNOS)
    else:
        am = _org(ctx, OrgHashFake, "DRE", True, ALUNO, ALUNOS)
    it, m = indexed_nested_loop(ctx, r, am, COND, M=M, materializar=materializar)
    assert _multiconjunto(it) == ESPERADO
    assert m["tuplas_saida"] == sum(ESPERADO.values())
    assert (m["escrita_saida"] > 0) == materializar
    assert rastreio[0].pico <= M and rastreio[0].paginas_em_uso == 0


def test_inl_indice_nao_unico_e_nulos(ctx, tabela):
    a = tabela("Aluno", registros=ALUNOS)
    t = tabela("Turma", registros=TURMAS)
    am = _am_indice(ctx, t, "professor", unique=False)
    cond = CondJuncao("prof_orientador", "professor")
    it, _ = indexed_nested_loop(ctx, a, am, cond, M=3)
    assert _multiconjunto(it) == _oraculo("Aluno", ALUNOS, "Turma", TURMAS, cond)


def test_inl_uma_busca_por_tupla_externa(ctx, rels):
    """15.5.3: custo br + nr·c — com índice fake (1 acesso por busca), as requisições na
    área 'indice' = nº de tuplas de r com valor não nulo."""
    r, s = rels
    am = _am_indice(ctx, s, "DRE", unique=True)
    antes = ctx.buffer_stats()["por_area"]["indice"]["requests"]
    it, _ = indexed_nested_loop(ctx, r, am, COND, M=3)
    list(it)
    depois = ctx.buffer_stats()["por_area"]["indice"]["requests"]
    assert depois - antes == NI


def test_inl_sem_estrutura_e_tipos(ctx, rels):
    r, s = rels
    with pytest.raises(ValueError):
        indexed_nested_loop(ctx, r, AccessMethod(s), COND, M=3)
    with pytest.raises(TypeError):
        indexed_nested_loop(ctx, r, s, COND, M=3)
    with pytest.raises(ValueError):
        indexed_nested_loop(ctx, r, _am_indice(ctx, s, "DRE", True), COND, M=1)
