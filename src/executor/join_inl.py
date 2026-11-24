"""Indexed nested-loop join — STUB do M0; implementação: M5 (E11).

Silberschatz 15.5.3: br + nr·c, c = custo de uma seleção pelo índice de s.
"""
from __future__ import annotations

from typing import Optional

from src.executor.contracts import AccessMethod, CondJuncao, Relacao, Resultado, StorageContext


def indexed_nested_loop(ctx: StorageContext, r: Relacao, s: AccessMethod, cond: CondJuncao, *,
                        M: Optional[int] = None, materializar: bool = False) -> Resultado:
    raise NotImplementedError("M5/E11")
