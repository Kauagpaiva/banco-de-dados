"""Partition-hash join — STUB do M0; implementação: M5J (E12).

Silberschatz 15.5.5; REFERENCIA_LIVRO §7: nh = ⌈bs/M⌉·fudge, build = menor, particionamento
recursivo quando partição > M−2, hash de partição ≠ hash em memória.
"""
from __future__ import annotations

from typing import Any, Optional

from src.executor.contracts import CondJuncao, Relacao, Resultado, StorageContext


def hash_join(ctx: StorageContext, r: Relacao, s: Relacao, cond: CondJuncao, *,
              M: Optional[int] = None, materializar: bool = False, fudge: float = 1.2,
              nh: Optional[int] = None) -> Resultado:
    raise NotImplementedError("M5J/E12")
