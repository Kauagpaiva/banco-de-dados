"""Políticas de substituição do buffer — STUB do M0; implementação: M1 (E02).

Silberschatz 13.5.2 (LRU, MRU, toss-immediate) + FIFO e Clock (second chance).
Interface: `src.storage.contracts.PolicyAPI`. Vítima só entre frames com pin_count == 0.
"""
from __future__ import annotations

from src.storage.contracts import Frame, PolicyAPI


class _Base(PolicyAPI):
    def __init__(self):
        raise NotImplementedError("M1/E02")

    def on_load(self, frame: Frame) -> None:
        raise NotImplementedError

    def on_access(self, frame: Frame) -> None:
        raise NotImplementedError

    def on_unpin(self, frame: Frame, toss: bool = False) -> None:
        raise NotImplementedError

    def on_evict(self, frame: Frame) -> None:
        raise NotImplementedError

    def victim(self, frames: list[Frame]) -> Frame | None:
        raise NotImplementedError


class LRU(_Base):
    nome = "LRU"


class MRU(_Base):
    nome = "MRU"


class FIFO(_Base):
    nome = "FIFO"


class Clock(_Base):
    nome = "CLOCK"


def criar_politica(nome: str) -> PolicyAPI:
    """Fábrica: 'LRU' | 'MRU' | 'FIFO' | 'CLOCK' → instância."""
    raise NotImplementedError("M1/E02")
