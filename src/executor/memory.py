"""Orçamento de memória de trabalho (M5, E10).

Silberschatz 15.4/15.5: os algoritmos de ordenação e junção dispõem de M páginas de buffer.
Aqui essas M páginas são páginas de rascunho da área 'trabalho' (`ctx.pin_work_page`), e toda
tupla mantida em estrutura Python (list/dict/heap) pelo operador precisa ser contabilizada
contra a capacidade, em bytes, das páginas reservadas. Contrato: `MemoryBudgetAPI`.

Regras:
- `reservar_paginas(n)` pina n páginas; `paginas_em_uso + n > M` → `MemoryBudgetError`
  (nada é pinado nesse caso).
- `reservar_tuplas(n, tam)` soma n·tam bytes; passar de `paginas_em_uso · block_size`
  → `MemoryBudgetError`. Liberar páginas que ainda guardam tuplas também é erro.
- `liberar_tudo()` (chamado pelo `with`) solta todas as páginas e zera as tuplas.
"""
from __future__ import annotations

from typing import Optional

from src.common.erros import MemoryBudgetError
from src.executor.contracts import MemoryBudgetAPI, StorageContext


class MemoryBudget(MemoryBudgetAPI):
    """M páginas da área 'trabalho' (M=None → `ctx.work_capacity()`)."""

    def __init__(self, ctx: StorageContext, M: Optional[int] = None):
        capacidade = ctx.work_capacity()
        M = capacidade if M is None else M
        if not isinstance(M, int) or M < 1:
            raise ValueError(f"M inválido: {M!r} (mínimo 1 página)")
        if M > capacidade:
            raise MemoryBudgetError(
                f"M={M} excede a capacidade da área 'trabalho' ({capacidade} páginas)")
        self._ctx = ctx
        self._M = M
        self._block_size = ctx.bm.block_size
        self._frames: list = []
        self._bytes_tuplas = 0
        self._n_tuplas = 0

    # ------------------------------------------------------------------ consultas
    @property
    def M(self) -> int:
        return self._M

    @property
    def paginas_em_uso(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> tuple:
        """Frames de rascunho reservados (somente leitura; quem escrever marca dirty)."""
        return tuple(self._frames)

    @property
    def tuplas_em_uso(self) -> int:
        return self._n_tuplas

    @property
    def bytes_disponiveis(self) -> int:
        return len(self._frames) * self._block_size - self._bytes_tuplas

    def tuplas_por_pagina(self, tam: int) -> int:
        if tam <= 0:
            raise ValueError(f"tamanho de tupla inválido: {tam!r}")
        return self._block_size // tam

    # ------------------------------------------------------------------ páginas
    def reservar_paginas(self, n: int) -> None:
        if n < 0:
            raise ValueError(f"n negativo: {n}")
        if len(self._frames) + n > self._M:
            raise MemoryBudgetError(
                f"reservar {n} páginas excede M={self._M} (em uso: {len(self._frames)})")
        novos = []
        try:
            for _ in range(n):
                novos.append(self._ctx.pin_work_page())
        except BaseException:
            for fr in novos:              # reserva atômica: desfaz o que já foi pinado
                self._ctx.unpin_work_page(fr)
            raise
        self._frames.extend(novos)

    def liberar_paginas(self, n: int) -> None:
        if n < 0 or n > len(self._frames):
            raise ValueError(f"liberar {n} páginas, mas há {len(self._frames)} em uso")
        restante = (len(self._frames) - n) * self._block_size
        if self._bytes_tuplas > restante:
            raise MemoryBudgetError(
                f"liberar {n} páginas deixaria {self._bytes_tuplas} B de tuplas em {restante} B")
        for _ in range(n):
            self._ctx.unpin_work_page(self._frames.pop())

    # ------------------------------------------------------------------ tuplas
    def reservar_tuplas(self, n: int, tam: int) -> None:
        if n < 0 or tam <= 0:
            raise ValueError(f"reserva inválida: n={n}, tam={tam}")
        novo = self._bytes_tuplas + n * tam
        cap = len(self._frames) * self._block_size
        if novo > cap:
            raise MemoryBudgetError(
                f"{n} tuplas de {tam} B excedem as {len(self._frames)} páginas reservadas "
                f"({novo} B > {cap} B)")
        self._bytes_tuplas = novo
        self._n_tuplas += n

    def liberar_tuplas(self, n: int, tam: int) -> None:
        if n < 0 or tam <= 0 or n > self._n_tuplas or n * tam > self._bytes_tuplas:
            raise ValueError(f"liberar_tuplas({n}, {tam}) sem reserva correspondente")
        self._bytes_tuplas -= n * tam
        self._n_tuplas -= n

    # ------------------------------------------------------------------ tudo
    def liberar_tudo(self) -> None:
        self._bytes_tuplas = 0
        self._n_tuplas = 0
        erro = None
        while self._frames:
            fr = self._frames.pop()
            try:
                self._ctx.unpin_work_page(fr)
            except Exception as e:        # continua soltando as demais; relança no fim
                erro = erro or e
        if erro is not None:
            raise erro
