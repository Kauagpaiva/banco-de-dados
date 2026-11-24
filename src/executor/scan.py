"""Varreduras auxiliares do executor — STUB do M0; implementação: M5 (E10).

Silberschatz 15.2 (A1: varredura linear). Adapta FileOrganization/TempFile/iteráveis em
iteradores de registros e mede a operação (Metricas = diferença de `ctx.buffer_stats()`).
"""
from __future__ import annotations

from typing import Iterator

from src.executor.contracts import Entrada, Metricas, StorageContext


def scan_registros(entrada: Entrada, toss: bool = False) -> Iterator[dict]:
    """Registros de FileOrganization (sem RID), TempFile ou iterável de dicts."""
    raise NotImplementedError("M5/E10")


class Medidor:
    """`with Medidor(ctx) as m: ...` → `m.metricas` com a diferença de stats no período."""

    def __init__(self, ctx: StorageContext):
        raise NotImplementedError("M5/E10")

    def __enter__(self) -> "Medidor":
        raise NotImplementedError

    def __exit__(self, *exc) -> None:
        raise NotImplementedError

    @property
    def metricas(self) -> Metricas:
        raise NotImplementedError
