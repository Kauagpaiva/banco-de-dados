"""Orçamento de memória de trabalho — STUB do M0; implementação: M5 (E10).

Silberschatz 15.4/15.5: os algoritmos dispõem de M páginas de buffer. Contrato: `MemoryBudgetAPI`.
"""
from __future__ import annotations

from typing import Optional

from src.executor.contracts import MemoryBudgetAPI, StorageContext


class MemoryBudget(MemoryBudgetAPI):
    def __init__(self, ctx: StorageContext, M: Optional[int] = None):
        raise NotImplementedError("M5/E10")

    @property
    def M(self) -> int:
        raise NotImplementedError

    @property
    def paginas_em_uso(self) -> int:
        raise NotImplementedError

    def reservar_paginas(self, n: int) -> None:
        raise NotImplementedError

    def liberar_paginas(self, n: int) -> None:
        raise NotImplementedError

    def reservar_tuplas(self, n: int, tam: int) -> None:
        raise NotImplementedError

    def liberar_tuplas(self, n: int, tam: int) -> None:
        raise NotImplementedError

    def tuplas_por_pagina(self, tam: int) -> int:
        raise NotImplementedError

    def liberar_tudo(self) -> None:
        raise NotImplementedError
