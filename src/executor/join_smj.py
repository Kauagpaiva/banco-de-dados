"""Sort-merge join — STUB do M0; implementação: M5J (E12).

Silberschatz 15.5.4; REFERENCIA_LIVRO §7. Ordena com `external_sort` (pula se a organização
já fornece ordem via `find_ordered`); merge tratando grupos de duplicatas; grupo maior que M →
fallback BNL para o grupo.
"""
from __future__ import annotations

from typing import Any, Optional

from src.executor.contracts import CondJuncao, Relacao, Resultado, StorageContext


def sort_merge_join(ctx: StorageContext, r: Relacao, s: Relacao, cond: CondJuncao, *,
                    M: Optional[int] = None, materializar: bool = False) -> Resultado:
    raise NotImplementedError("M5J/E12")
