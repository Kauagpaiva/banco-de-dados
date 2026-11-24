"""Ordenação externa (sort-merge) — STUB do M0; implementação: M5 (E11).

Silberschatz 15.4; REFERENCIA_LIVRO §7: runs de M páginas, merge (M−1)-way (ou ⌊M/bb⌋−1 com
bb blocos por run), temporários na área 'trabalho', apagados ao final.
"""
from __future__ import annotations

from typing import Optional, Sequence, Union

from src.executor.contracts import Entrada, Esquema, Metricas, StorageContext, TempFile


def external_sort(ctx: StorageContext, entrada: Entrada, esquema: Esquema,
                  chave: Union[str, Sequence[str]], *, M: Optional[int] = None,
                  bb: int = 1) -> tuple[TempFile, Metricas]:
    """Ver `ExternalSortFn`."""
    raise NotImplementedError("M5/E11")
