from collections import Counter

import pytest

from src.access.esquemas import ALUNO, INSCRICAO
from src.common.tipos import CHAVES_STATS, CondJuncao
from src.executor import join_hash as hash_mod
from src.executor import memory as memory_mod
from src.executor.contracts import combinar
from src.executor.join_hash import hash_join
from tests.fakes import registros_fake
from src.executor.join_smj import sort_merge_join

NA, NI = 200, 1000
COND = CondJuncao("DRE", "DRE")


def _alunos():
    return list(registros_fake(ALUNO, NA, seed=5))


def _inscricoes():
    regs = list(registros_fake(INSCRICAO, NI, seed=6))
    for i, r in enumerate(regs):
        r["DRE"] = (i % NA) + 1
    return regs


def _chave(rec):
    return repr(sorted(rec.items()))


def _oraculo(nome_r, regs_r, nome_s, regs_s):
    return Counter(
        _chave(combinar(nome_r, a, nome_s, b))
        for a in regs_r
        for b in regs_s
        if a["DRE"] is not None and a["DRE"] == b["DRE"]
    )


def _multiconjunto(it):
    return Counter(_chave(r) for r in it)


@pytest.fixture
def rels(tabela):
    return (
        tabela("Inscricao_Aluno_Turma", registros=_inscricoes()),
        tabela("Aluno", registros=_alunos()),
    )


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

    monkeypatch.setattr(hash_mod, "MemoryBudget", Rastreado)
    return picos


def test_hash_igual_ao_oraculo(ctx, rels, rastreio):
    r, s = rels
    regs_r, regs_s = _inscricoes(), _alunos()

    it, m = hash_join(ctx, r, s, COND, M=64)

    assert _multiconjunto(it) == _oraculo(
        "Inscricao_Aluno_Turma", regs_r, "Aluno", regs_s
    )
    assert m["tuplas_saida"] == sum(
        _oraculo("Inscricao_Aluno_Turma", regs_r, "Aluno", regs_s).values()
    )
    assert set(CHAVES_STATS) <= set(m)
    assert rastreio[0].pico <= 64
    assert rastreio[0].paginas_em_uso == 0


def test_hash_materializar(ctx, rels):
    r, s = rels
    it, m = hash_join(ctx, r, s, COND, M=64, materializar=True)

    assert len(list(it)) > 0
    assert m["escrita_saida"] > 0
    assert m["writes"] >= m["escrita_saida"]


def test_hash_parametros_invalidos(ctx, rels):
    r, s = rels

    with pytest.raises(ValueError):
        hash_join(ctx, r, s, COND, M=2)

    with pytest.raises(ValueError):
        hash_join(ctx, r, s, COND, fudge=0)

    with pytest.raises(ValueError):
        hash_join(ctx, r, s, COND, nh=0)

    with pytest.raises(ValueError):
        hash_join(ctx, r, s, CondJuncao("DRE", "inexistente"), M=3)


def test_hash_com_memoria_minima(ctx, rels):
    r, s = rels
    regs_r, regs_s = _inscricoes(), _alunos()

    it, m = hash_join(ctx, r, s, COND, M=3)

    esperado = _oraculo(
        "Inscricao_Aluno_Turma",
        regs_r,
        "Aluno",
        regs_s,
    )

    assert _multiconjunto(it) == esperado
    assert m["tuplas_saida"] == sum(esperado.values())

def test_hash_preserva_chaves_duplicadas(ctx, tabela):
    regs_r = list(registros_fake(ALUNO, 3, seed=10))
    regs_s = list(registros_fake(INSCRICAO, 2, seed=11))

    for rec in regs_r + regs_s:
        rec["DRE"] = 1

    r = tabela("Aluno", registros=regs_r)
    s = tabela("Inscricao_Aluno_Turma", registros=regs_s)

    it, m = hash_join(ctx, r, s, COND, M=3)

    resultado = list(it)

    assert len(resultado) == 6
    assert m["tuplas_saida"] == 6

def test_hash_ignora_chaves_nulas(ctx, tabela):
    regs_r = list(registros_fake(ALUNO, 3, seed=12))
    regs_s = list(registros_fake(INSCRICAO, 3, seed=13))

    r_base = tabela("Aluno", registros=regs_r)
    s_base = tabela("Inscricao_Aluno_Turma", registros=regs_s)

    class RelacaoComNulos:
        def __init__(self, base):
            self.base = base
            self.esquema = base.esquema

        def num_blocks(self):
            return self.base.num_blocks()

        def num_registros(self):
            return self.base.num_registros()

        def scan_blocos(self, toss=False):
            for bloco in self.base.scan_blocos(toss):
                novos = []
                for rec in bloco:
                    copia = dict(rec)
                    copia["DRE"] = None
                    novos.append(copia)
                yield novos

    r = RelacaoComNulos(r_base)
    s = RelacaoComNulos(s_base)

    it, m = hash_join(ctx, r, s, COND, M=3)

    assert list(it) == []
    assert m["tuplas_saida"] == 0

def test_hash_chaves_todas_iguais(ctx, tabela):
    regs_r = list(registros_fake(ALUNO, 20, seed=20))
    regs_s = list(registros_fake(INSCRICAO, 15, seed=21))

    for rec in regs_r + regs_s:
        rec["DRE"] = 1

    r = tabela("Aluno", registros=regs_r)
    s = tabela("Inscricao_Aluno_Turma", registros=regs_s)

    it, m = hash_join(ctx, r, s, COND, M=3)

    resultado = list(it)

    assert len(resultado) == 20 * 15
    assert m["tuplas_saida"] == 20 * 15

def test_hash_libera_memoria_ao_fechar_antecipadamente(ctx, rels, rastreio):
    r, s = rels

    it, _ = hash_join(ctx, r, s, COND, M=64)

    next(it)
    it.close()

    assert rastreio[0].paginas_em_uso == 0

def test_hash_remove_temporarios_ao_fechar(ctx, rels):
    r, s = rels

    inicio = len(ctx._temps)

    it, _ = hash_join(ctx, r, s, COND, M=64)

    next(it)
    it.close()

    temporarios = ctx._temps[inicio:]

    assert temporarios
    assert all(t._apagado for t in temporarios)

def test_hash_limita_quantidade_particoes(ctx, rels):
    r, s = rels

    it, m = hash_join(
        ctx, r, s, COND,
        M=3,
        nh=100,
    )

    resultado = list(it)

    assert len(resultado) > 0
    assert m["tuplas_saida"] == len(resultado)    

def test_hash_fecha_antecipadamente(ctx, rels, rastreio):
    r, s = rels

    it, m = hash_join(ctx, r, s, COND, M=64)

    next(it)
    it.close()

    assert rastreio[0].paginas_em_uso == 0

def test_smj_igual_ao_oraculo(ctx, rels):
    r, s = rels
    regs_r, regs_s = _inscricoes(), _alunos()

    it, m = sort_merge_join(ctx, r, s, COND, M=64)

    esperado = _oraculo(
        "Inscricao_Aluno_Turma", regs_r, "Aluno", regs_s
    )

    assert _multiconjunto(it) == esperado
    assert m["tuplas_saida"] == sum(esperado.values())

def test_smj_preserva_chaves_duplicadas(ctx, tabela):
    regs_r = list(registros_fake(ALUNO, 3, seed=10))
    regs_s = list(registros_fake(INSCRICAO, 2, seed=11))

    for rec in regs_r + regs_s:
        rec["DRE"] = 1

    r = tabela("Aluno", registros=regs_r)
    s = tabela("Inscricao_Aluno_Turma", registros=regs_s)

    it, m = sort_merge_join(ctx, r, s, COND, M=64)

    assert len(list(it)) == 6
    assert m["tuplas_saida"] == 6

def test_smj_ignora_chaves_nulas(ctx, rels):
    r, s = rels

    class RelacaoNula:
        def __init__(self, base):
            self.esquema = base.esquema

        def scan_blocos(self, *args):
            for bloco in (r if self.esquema.nome == "Inscricao_Aluno_Turma" else s).scan_blocos(False):
                yield [
                    {**rec, "DRE": None}
                    for rec in bloco
                ]

    it, m = sort_merge_join(
        ctx, RelacaoNula(r), RelacaoNula(s), COND, M=64
    )

    assert list(it) == []
    assert m["tuplas_saida"] == 0

def test_smj_fecha_antecipadamente(ctx, rels):
    r, s = rels
    inicio = len(ctx._temps)

    it, _ = sort_merge_join(ctx, r, s, COND, M=64)
    next(it)
    it.close()

    temporarios = ctx._temps[inicio:]
    assert temporarios
    assert all(t._apagado for t in temporarios)