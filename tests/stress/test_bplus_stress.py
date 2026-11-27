
"""Teste de estresse da árvore B+ — E16."""
import random

import pytest

from src.access.bplus import BPlusTree
from src.access.esquemas import TURMA
from tests.fakes import registros_fake


@pytest.mark.stress
def test_bplus_200_mil_insercoes_aleatorias(bm, page_impl, codec):
    total = 200_000

    registros = list(registros_fake(TURMA, total, seed=42))
    random.Random(42).shuffle(registros)

    arvore = BPlusTree(
        bm,
        "stress_bplus",
        TURMA,
        "numero",
        unique=True,
        page_impl=page_impl,
        codec=codec(TURMA),
    )
    arvore.open()

    try:
        for i, registro in enumerate(registros, start=1):
            arvore.insert(registro)

            if i % 10_000 == 0:
                arvore.check_invariants()

        arvore.check_invariants()
        assert arvore.num_registros() == total

        # Confere se a varredura retorna todas as chaves em ordem.
        for esperado, (_, registro) in enumerate(arvore.scan(), start=1):
            assert registro["numero"] == esperado

        assert esperado == total

        # Confere buscas em uma amostra aleatória.
        amostra = random.Random(123).sample(range(1, total + 1), 1_000)

        for chave in amostra:
            rid = arvore.find("numero", chave)
            assert rid is not None
            assert arvore.read(rid)["numero"] == chave

                # Remove 20 mil registros em ordem aleatória.
        removidos = set(random.Random(456).sample(
            range(1, total + 1), 20_000
        ))

        for i, chave in enumerate(removidos, start=1):
            rid = arvore.find("numero", chave)
            assert rid is not None

            arvore.delete(rid)

            if i % 1_000 == 0:
                arvore.check_invariants()

        arvore.check_invariants()
        assert arvore.num_registros() == total - len(removidos)

        # Confere se todas as chaves removidas desapareceram.
        for chave in removidos:
            assert arvore.find("numero", chave) is None

        # Confere se os registros restantes continuam ordenados.
        restantes = [registro["numero"] for _, registro in arvore.scan()]
        esperados = sorted(set(range(1, total + 1)) - removidos)

        assert restantes == esperados

    finally:
        arvore.close()
