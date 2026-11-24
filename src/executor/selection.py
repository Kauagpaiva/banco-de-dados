"""Seleção (Camada 2) — STUB do M0; implementação: M5 (E10).

Silberschatz 15.2 / Fig. 15.3 (A1–A6) e 15.3; REFERENCIA_LIVRO §6. Caminho escolhido pelo
chamador (sem otimizador): A1_linear, A1_chave, A2..A6, HASH_PRIM, HASH_SEC.
"""
from __future__ import annotations

from src.executor.contracts import AccessMethod, Predicado, Resultado, StorageContext


def select(ctx: StorageContext, am: AccessMethod, predicado: Predicado, caminho: str) -> Resultado:
    """Ver `SelectFn`. Caminho incompatível com o método de acesso → ValueError."""
    raise NotImplementedError("M5/E10")
