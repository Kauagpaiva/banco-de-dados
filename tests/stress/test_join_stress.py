
"""Testes de estresse dos algoritmos de junção — E16."""

import pytest

from src.access.esquemas import ALUNO, INSCRICAO
from src.common.tipos import CondJuncao
from src.executor.join_hash import hash_join
from src.executor.join_smj import sort_merge_join
from tests.fakes import registros_fake


TOTAL = 500
COND = CondJuncao("DRE", "DRE")


@pytest.mark.stress
@pytest.mark.parametrize(
    "join_fn",
    [hash_join, sort_merge_join],
    ids=["hash", "sort-merge"],
)
def test_join_com_memoria_minima_e_chaves_concentradas(
    ctx, tabela, join_fn
):
    alunos = list(registros_fake(ALUNO, TOTAL, seed=71))
    inscricoes = list(registros_fake(INSCRICAO, TOTAL, seed=72))

    # Concentra metade das inscrições na mesma chave (DRE = 1).
    # A outra metade usa chaves distintas.
    for i, registro in enumerate(inscricoes):
        registro["DRE"] = 1 if i < TOTAL // 2 else i + 1
        registro["numero_turma"] = i + 1

    rel_inscricoes = tabela("Inscricao_Aluno_Turma", registros=inscricoes)
    rel_alunos = tabela("Aluno", registros=alunos)

    resultado, metricas = join_fn(
        ctx, rel_inscricoes, rel_alunos, COND, M=3
    )

    try:
        tuplas = list(resultado)
        assert len(tuplas) == TOTAL
        assert metricas["tuplas_saida"] == TOTAL
    finally:
        resultado.close()


@pytest.mark.stress
@pytest.mark.parametrize(
    "join_fn",
    [hash_join, sort_merge_join],
    ids=["hash", "sort-merge"],
)
def test_join_com_100_porcento_de_chaves_duplicadas(
    ctx, tabela, join_fn
):
    alunos = list(registros_fake(ALUNO, TOTAL, seed=81))
    inscricoes = list(registros_fake(INSCRICAO, TOTAL, seed=82))

    for i, registro in enumerate(inscricoes):
        registro["DRE"] = 1
        registro["numero_turma"] = i + 1

    rel_inscricoes = tabela(
        "Inscricao_Aluno_Turma", registros=inscricoes
    )
    rel_alunos = tabela("Aluno", registros=alunos)

    resultado, metricas = join_fn(
        ctx, rel_inscricoes, rel_alunos, COND, M=3
    )

    try:
        tuplas = list(resultado)
        assert len(tuplas) == TOTAL
        assert metricas["tuplas_saida"] == TOTAL
    finally:
        resultado.close()