"""Slotted page (Camada 3) — STUB do M0; implementação: M2 (E03).

Silberschatz 13.2.2 (Fig. 13.6): cabeçalho com nº de slots, fim do espaço livre e vetor de
(offset,len); registros crescem do fim para o início; área reservada no fim do bloco.
Contrato: `SlottedPageAPI` (métodos estáticos sobre `frame.data`).
"""
from __future__ import annotations

from typing import Iterator, Optional

from src.access.contracts import SlottedPageAPI


class SlottedPage(SlottedPageAPI):
    @staticmethod
    def format(buf: bytearray, reserva: int = 0) -> None:
        raise NotImplementedError("M2/E03")

    @staticmethod
    def insert(buf: bytearray, rec: bytes) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def get(buf: bytearray, slot: int) -> Optional[bytes]:
        raise NotImplementedError

    @staticmethod
    def delete(buf: bytearray, slot: int) -> None:
        raise NotImplementedError

    @staticmethod
    def update(buf: bytearray, slot: int, rec: bytes) -> bool:
        raise NotImplementedError

    @staticmethod
    def compact(buf: bytearray) -> None:
        raise NotImplementedError

    @staticmethod
    def free_space(buf: bytearray) -> int:
        raise NotImplementedError

    @staticmethod
    def slots(buf: bytearray) -> Iterator[int]:
        raise NotImplementedError

    @staticmethod
    def count(buf: bytearray) -> int:
        raise NotImplementedError

    @staticmethod
    def reserva(buf: bytearray) -> tuple[int, int]:
        raise NotImplementedError

    @staticmethod
    def capacidade_max(block_size: int, reserva: int = 0) -> int:
        raise NotImplementedError
