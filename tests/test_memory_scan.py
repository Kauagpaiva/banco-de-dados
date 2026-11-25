"""E10 (M5): MemoryBudget, scan_registros, Medidor e IteradorMedido."""
from __future__ import annotations

import pytest

from src.access.esquemas import CURSO
from src.common.erros import MemoryBudgetError
from src.common.tipos import CHAVES_STATS
from src.executor.memory import MemoryBudget
from src.executor.scan import Medidor, operacao_medida, scan_registros
from tests.fakes import registros_fake


# ----------------------------------------------------------------------------- MemoryBudget
def test_budget_padrao_usa_capacidade_de_trabalho(ctx):
    mb = MemoryBudget(ctx)
    assert mb.M == ctx.work_capacity()
    assert mb.paginas_em_uso == 0


def test_budget_M_invalido(ctx):
    with pytest.raises(ValueError):
        MemoryBudget(ctx, 0)
    with pytest.raises(MemoryBudgetError):
        MemoryBudget(ctx, ctx.work_capacity() + 1)


def test_reservar_e_liberar_paginas_pina_e_solta(ctx):
    with MemoryBudget(ctx, 3) as mb:
        mb.reservar_paginas(2)
        assert mb.paginas_em_uso == 2
        assert all(fr.pin_count == 1 and fr.area == "trabalho" for fr in mb.frames)
        mb.reservar_paginas(1)
        with pytest.raises(MemoryBudgetError):
            mb.reservar_paginas(1)
        assert mb.paginas_em_uso == 3          # reserva recusada não pina nada
        mb.liberar_paginas(2)
        assert mb.paginas_em_uso == 1
    assert mb.paginas_em_uso == 0
    ctx.bm.assert_no_pins()


def test_reservar_tuplas_limitado_pelas_paginas(ctx):
    bs = ctx.bm.block_size
    with MemoryBudget(ctx, 2) as mb:
        with pytest.raises(MemoryBudgetError):
            mb.reservar_tuplas(1, 10)          # sem páginas reservadas → nada cabe
        mb.reservar_paginas(1)
        tpp = mb.tuplas_por_pagina(100)
        assert tpp == bs // 100
        mb.reservar_tuplas(tpp, 100)
        with pytest.raises(MemoryBudgetError):
            mb.reservar_tuplas(tpp, 100)       # a 2ª página não foi reservada
        with pytest.raises(MemoryBudgetError):
            mb.liberar_paginas(1)              # ainda há tuplas nela
        mb.liberar_tuplas(tpp, 100)
        assert mb.tuplas_em_uso == 0
        mb.liberar_paginas(1)


def test_liberacoes_invalidas(ctx):
    with MemoryBudget(ctx, 2) as mb:
        with pytest.raises(ValueError):
            mb.liberar_paginas(1)
        with pytest.raises(ValueError):
            mb.liberar_tuplas(1, 10)
        with pytest.raises(ValueError):
            mb.tuplas_por_pagina(0)


def test_liberar_tudo_em_excecao(ctx):
    with pytest.raises(RuntimeError):
        with MemoryBudget(ctx, 4) as mb:
            mb.reservar_paginas(4)
            mb.reservar_tuplas(3, 50)
            raise RuntimeError("falha no operador")
    assert mb.paginas_em_uso == 0 and mb.tuplas_em_uso == 0
    ctx.bm.assert_no_pins()


# ----------------------------------------------------------------------------- scan_registros
def test_scan_registros_de_tabela_temp_e_lista(ctx, tabela):
    regs = list(registros_fake(CURSO, 30, seed=1))
    t = tabela("Curso", registros=regs)
    assert list(scan_registros(t)) == regs

    tmp = ctx.temp_file(CURSO)
    for r in regs:
        tmp.append(r)
    tmp.close()
    assert list(scan_registros(tmp)) == regs

    assert list(scan_registros(iter(regs))) == regs
    assert list(scan_registros(regs)) == regs


def test_scan_registros_rejeita_entrada_invalida():
    with pytest.raises(TypeError):
        scan_registros(42)
    with pytest.raises(TypeError):
        list(scan_registros([1, 2]))


def test_scan_registros_fechado_no_meio_nao_deixa_pin(ctx, tabela):
    t = tabela("Curso", 30)
    it = scan_registros(t)
    next(it)
    it.close()
    ctx.bm.assert_no_pins()


# ----------------------------------------------------------------------------- Medidor
def test_medidor_conta_leituras_do_scan(ctx, tabela):
    t = tabela("Curso", 40)
    ctx.drop_all()
    with Medidor(ctx) as m:
        n = sum(1 for _ in scan_registros(t))
        parcial = m.metricas
    final = m.metricas
    assert n == 40
    assert set(CHAVES_STATS) <= set(final)
    assert final["requests"] == t.num_blocks()
    assert final["misses"] == t.num_blocks()
    assert parcial["requests"] == final["requests"]
    assert final["transferencias"] == final["reads"] + final["writes"]


def test_medidor_fora_do_with_devolve_zeros(ctx):
    m = Medidor(ctx)
    assert m.metricas["requests"] == 0


# ----------------------------------------------------------------------------- IteradorMedido
def test_iterador_medido_preenche_ao_esgotar(ctx, tabela):
    t = tabela("Curso", 25)
    it, met = operacao_medida(ctx, scan_registros(t))
    assert met["tuplas_saida"] == 0
    assert len(list(it)) == 25
    assert met["tuplas_saida"] == 25
    assert met["requests"] == t.num_blocks()
    assert met["escrita_saida"] == 0


def test_iterador_medido_preenche_ao_fechar(ctx, tabela):
    t = tabela("Curso", 25)
    it, met = operacao_medida(ctx, scan_registros(t))
    next(it)
    next(it)
    it.close()
    assert met["tuplas_saida"] == 2
    assert met["requests"] >= 1
    assert list(it) == []                      # fechado: nada mais
    ctx.bm.assert_no_pins()


def test_iterador_medido_fechado_sem_iniciar(ctx, tabela):
    t = tabela("Curso", 5)
    it, met = operacao_medida(ctx, scan_registros(t))
    it.close()
    assert met["tuplas_saida"] == 0 and met["requests"] == 0
