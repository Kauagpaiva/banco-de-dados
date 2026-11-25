"""E11 (M5): ordenação externa sort-merge (Silberschatz 15.4).

Oráculo: `sorted` do Python (estável) sobre os registros na ordem de varredura da entrada
(a referência SQLite é do M7; validação contra SQLite fica para o M10).
"""
from __future__ import annotations

import math
from collections import Counter

import pytest

from src.access.esquemas import ALUNO
from src.common.config import load_config
from src.common.erros import MemoryBudgetError
from src.common.tipos import CHAVES_STATS
from src.executor import memory as memory_mod
from src.executor import sort as sort_mod
from src.executor.sort import external_sort
from tests.conftest import bm_fake, bm_real, real_ou_fake
from tests.fakes import FakeStorageContext, FakeTable, registros_fake

N = 1000


def _regs(n=N, seed=3):
    regs = []
    for i, r in enumerate(registros_fake(ALUNO, n, seed=seed)):
        r["cod_curso"] = (i * 7919) % 37             # muitas repetições (estabilidade)
        r["prof_orientador"] = None if i % 5 == 0 else f"prof{(i * 31) % 23}"
        regs.append(r)
    return regs


def _ordenado(regs, campos):
    campos = (campos,) if isinstance(campos, str) else tuple(campos)
    return sorted(regs, key=lambda r: tuple((r[c] is not None, r[c]) for c in campos))


@pytest.fixture
def aluno(tabela):
    return tabela("Aluno", registros=_regs())


@pytest.fixture
def rastreio(monkeypatch):
    """Registra o maior uso de cada MemoryBudget criado pelo sort."""
    picos = []

    class Rastreado(memory_mod.MemoryBudget):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.pico_pag = 0
            self.pico_bytes = 0
            picos.append(self)

        def _marcar(self):
            self.pico_pag = max(self.pico_pag, self.paginas_em_uso)
            self.pico_bytes = max(self.pico_bytes, self._bytes_tuplas)

        def reservar_paginas(self, n):
            super().reservar_paginas(n)
            self._marcar()

        def reservar_paginas_io(self, n):
            super().reservar_paginas_io(n)
            self._marcar()

        def reservar_tuplas(self, n, tam):
            super().reservar_tuplas(n, tam)
            self._marcar()
    monkeypatch.setattr(sort_mod, "MemoryBudget", Rastreado)
    return picos


def _ler(tmp):
    return list(tmp.scan())


# =========================================================================== correção
@pytest.mark.parametrize("M", [3, 4, 64])
@pytest.mark.parametrize("chave", ["DRE", "cod_curso", ("cod_curso", "CR"), "prof_orientador"])
def test_resultado_igual_ao_oraculo(ctx, aluno, rastreio, M, chave):
    base = [r for _, r in aluno.scan()]
    tmp, m = external_sort(ctx, aluno, ALUNO, chave, M=M)
    try:
        assert _ler(tmp) == _ordenado(base, chave)        # ordem e estabilidade
        assert m["tuplas_saida"] == N
        assert set(CHAVES_STATS) <= set(m)
        assert m["escrita_saida"] == tmp.num_blocks() > 0
    finally:
        tmp.delete()
    (mb,) = rastreio
    assert mb.pico_pag <= M
    assert mb.pico_bytes <= M * ctx.bm.block_size
    assert mb.paginas_em_uso == 0


def test_bb_maior_que_1(ctx, aluno, rastreio):
    base = [r for _, r in aluno.scan()]
    tmp, _ = external_sort(ctx, aluno, ALUNO, "CR", M=9, bb=2)    # merge ⌊9/2⌋−1 = 3 vias
    try:
        assert _ler(tmp) == _ordenado(base, "CR")
    finally:
        tmp.delete()
    assert rastreio[0].pico_pag <= 9


def test_entrada_iteravel_e_tempfile(ctx, rastreio):
    regs = _regs(300)
    tmp, m = external_sort(ctx, iter(regs), ALUNO, "nome", M=3)
    try:
        assert _ler(tmp) == _ordenado(regs, "nome")
        assert m["tuplas_saida"] == 300
        tmp2, _ = external_sort(ctx, tmp, ALUNO, "DRE", M=3)        # entrada = TempFile
        try:
            assert _ler(tmp2) == _ordenado(regs, "DRE")
        finally:
            tmp2.delete()
    finally:
        tmp.delete()
    assert all(mb.pico_pag <= 3 for mb in rastreio)


def test_entrada_vazia(ctx):
    tmp, m = external_sort(ctx, [], ALUNO, "DRE", M=3)
    try:
        assert _ler(tmp) == [] and tmp.num_registros() == 0
        assert m["tuplas_saida"] == 0
    finally:
        tmp.delete()


def test_temporarios_intermediarios_apagados(ctx, aluno, monkeypatch):
    criados = []
    original = ctx.temp_file

    def espiar(esquema, prefixo="tmp"):
        t = original(esquema, prefixo)
        criados.append(t.nome)
        return t
    monkeypatch.setattr(ctx, "temp_file", espiar)
    tmp, _ = external_sort(ctx, aluno, ALUNO, "DRE", M=3)
    assert len(criados) > 3                                  # houve runs e passos de merge
    vivos = [n for n in criados if ctx.bm.exists(n)]
    assert vivos == [tmp.nome]
    tmp.delete()


def test_erro_no_meio_apaga_temporarios(ctx, aluno, monkeypatch):
    criados = []
    original = ctx.temp_file

    def espiar(esquema, prefixo="tmp"):
        t = original(esquema, prefixo)
        criados.append(t.nome)
        if len(criados) == 4:
            raise RuntimeError("falha simulada")
        return t
    monkeypatch.setattr(ctx, "temp_file", espiar)
    with pytest.raises(RuntimeError):
        external_sort(ctx, aluno, ALUNO, "DRE", M=3)
    assert not [n for n in criados[:3] if ctx.bm.exists(n)]


# =========================================================================== validação
@pytest.mark.parametrize("kw, erro", [
    ({"M": 2}, ValueError), ({"M": 5, "bb": 2}, ValueError), ({"M": 3, "bb": 0}, ValueError),
    ({"M": 10_000}, MemoryBudgetError),
])
def test_parametros_invalidos(ctx, aluno, kw, erro):
    antes = dict(ctx.buffer_stats())
    with pytest.raises(erro):
        external_sort(ctx, aluno, ALUNO, "DRE", **kw)
    assert ctx.buffer_stats()["requests"] == antes["requests"]


def test_campo_inexistente(ctx, aluno):
    with pytest.raises(ValueError):
        external_sort(ctx, aluno, ALUNO, "nao_existe", M=3)
    with pytest.raises(ValueError):
        external_sort(ctx, aluno, ALUNO, (), M=3)


# =========================================================================== custo (15.4.2)
@pytest.mark.parametrize("M", [3, 5])
def test_transferencias_proximas_do_livro(tmp_path, so_fakes, _buffers_sem_pins, M):
    """Área 'trabalho' com exatamente M páginas e buffer frio: runs gravados e relidos de
    fato. Transferências ≈ b·(2⌈log_{M−1}(b/M)⌉ + 1) + b (gravação do resultado)."""
    cfg = load_config(overrides={"buffer.areas.trabalho": M,
                                 "buffer.total_pages": 8 + 64 + 120 + M})
    bm = real_ou_fake(lambda: bm_real(cfg, tmp_path), lambda: bm_fake(cfg), so_fakes)
    _buffers_sem_pins.append(bm)
    ctx = FakeStorageContext(cfg, bm=bm)
    t = FakeTable(bm, "aluno_custo", ALUNO)
    t.open()
    for r in _regs():
        t.insert(r)
    b = t.num_blocks()
    ctx.drop_all()
    ctx.reset_stats()
    tmp, m = external_sort(ctx, t, ALUNO, "CR", M=M)
    try:
        assert [r["CR"] for r in tmp.scan()] == sorted(r["CR"] for r in _regs())
    finally:
        tmp.delete()
    passos = math.ceil(math.log(math.ceil(b / M), M - 1))
    esperado = b * (2 * passos + 1) + b
    assert abs(m["transferencias"] - esperado) <= 0.15 * esperado, (m["transferencias"], esperado)
    ctx.close()
