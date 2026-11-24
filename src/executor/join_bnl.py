"""Block nested-loop join — STUB do M0; implementação: M5 (E11).

Silberschatz 15.5.2; REFERENCIA_LIVRO §7: M−2 blocos para a externa, 1 para a interna,
1 de saída; custo br + ⌈br/(M−2)⌉·bs transferências. MRU/toss-immediate na interna (13.5).
"""
from __future__ import annotations

from typing import Any, Optional

from src.executor.contracts import CondJuncao, Relacao, Resultado, StorageContext


def block_nested_loop(ctx: StorageContext, r: Relacao, s: Relacao, cond: CondJuncao, *,
                      M: Optional[int] = None, materializar: bool = False,
                      externa: str = "auto", toss: bool = False) -> Resultado:
    raise NotImplementedError("M5/E11")
