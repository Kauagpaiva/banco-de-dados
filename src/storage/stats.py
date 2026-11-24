"""Contadores de I/O por arquivo e globais — STUB do M0; implementação: M1 (E01).

Silberschatz 12.3 / 15.1 (tT e tS). Modelo de seek D05: (fid,b) é sequencial se o último
acesso físico foi (fid,b-1). Chaves: `src.common.tipos.CHAVES_IO`.
"""
from __future__ import annotations


class IOStats:
    def __init__(self):
        raise NotImplementedError("M1/E01")

    def registrar(self, fid: int, bno: int, escrita: bool) -> None:
        """Conta 1 leitura/escrita, classificando como sequencial ou aleatória."""
        raise NotImplementedError

    def snapshot(self, fid: int | None = None) -> dict[str, int]:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError
