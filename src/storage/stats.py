"""Contadores de I/O por arquivo e globais (M1/E01).

Silberschatz 12.3 / 12.6 / 15.1 (tT e tS). Modelo de seek D05 — **braço de disco global**:
o acesso a (fid, b) é sequencial se o último acesso físico (leitura ou escrita, de qualquer
arquivo) foi (fid, b-1); caso contrário é aleatório (1 seek). O primeiro acesso é aleatório.
Chaves: `src.common.tipos.CHAVES_IO`.
"""
from __future__ import annotations

from collections import defaultdict

from src.common.tipos import CHAVES_IO


def _zeros() -> dict[str, int]:
    return dict.fromkeys(CHAVES_IO, 0)


class IOStats:
    """Contadores globais e por fid + posição do braço do disco."""

    def __init__(self):
        self._glob: dict[str, int] = _zeros()
        self._por: defaultdict[int, dict[str, int]] = defaultdict(_zeros)
        self.braco: tuple[int, int] | None = None   # último acesso físico (fid, bno)

    def registrar(self, fid: int, bno: int, escrita: bool) -> None:
        """Conta 1 leitura/escrita, classificando como sequencial ou aleatória."""
        seq = self.braco == (fid, bno - 1)
        self.braco = (fid, bno)
        tipo = "writes" if escrita else "reads"
        det = ("seq_" if seq else "rand_") + tipo
        for d in (self._glob, self._por[fid]):
            d[tipo] += 1
            d[det] += 1

    def snapshot(self, fid: int | None = None) -> dict[str, int]:
        if fid is None:
            return dict(self._glob)
        return dict(self._por[fid]) if fid in self._por else _zeros()

    def reset(self) -> None:
        """Zera os contadores. A posição do braço é estado físico e **não** é zerada."""
        self._glob = _zeros()
        self._por.clear()
