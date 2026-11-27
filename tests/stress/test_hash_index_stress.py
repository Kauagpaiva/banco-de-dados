
import random

import pytest

from src.access.contracts import Campo
from src.access.hash_index import HashIndex
from src.common.tipos import RID


CPF = Campo("CPF", "char(11)")
TOTAL = 20_000


def chave(i):
    return f"{i:011d}"


@pytest.mark.stress
def test_hash_index_20_mil_insercoes_buscas_e_remocoes(bm, page_impl):
    idx = HashIndex(
        bm, "idx_stress_cpf", CPF,
        nr_estimado=TOTAL,
        page_impl=page_impl,
    )
    idx.open()

    try:
        # Insere 20 mil chaves únicas.
        for i in range(TOTAL):
            idx.insert(chave(i), RID(i + 1, 0))

        assert idx.arquivo.ocupacao()["registros"] == TOTAL

        # Busca 2 mil chaves em ordem aleatória.
        amostra = random.Random(123).sample(range(TOTAL), 2_000)

        for i in amostra:
            assert list(idx.search_eq(chave(i))) == [RID(i + 1, 0)]

        # Remove metade das entradas.
        removidos = set(random.Random(456).sample(range(TOTAL), TOTAL // 2))

        for i in removidos:
            idx.delete(chave(i), RID(i + 1, 0))

        assert idx.arquivo.ocupacao()["registros"] == TOTAL // 2

        # Confere as removidas.
        for i in removidos:
            assert list(idx.search_eq(chave(i))) == []

        # Confere as restantes.
        for i in range(TOTAL):
            if i not in removidos:
                assert list(idx.search_eq(chave(i))) == [RID(i + 1, 0)]

        # Confere as estatísticas finais.
        est = idx.estatisticas()
        assert est["buckets"] > 0

    finally:
        idx.close()
