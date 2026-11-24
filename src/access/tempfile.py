"""Arquivo temporário (runs, partições, saída materializada) — STUB do M0; implementação: M2.

Silberschatz 15.4 (runs da ordenação externa) e 15.5.5 (partições do hash join).
Páginas na área 'trabalho' via BufferManager. Contrato: `TempFile`.
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping

from src.access.contracts import Esquema, RecordCodecAPI, TempFile
from src.storage.contracts import BufferManagerAPI


class ArquivoTemporario(TempFile):
    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, *,
                 page_impl: type | None = None, codec: RecordCodecAPI | None = None):
        raise NotImplementedError("M2")

    def append(self, rec: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def blocks(self) -> Iterator[int]:
        raise NotImplementedError

    def records_in_block(self, bno: int) -> list[dict]:
        raise NotImplementedError

    def scan(self, toss: bool = False) -> Iterator[dict]:
        raise NotImplementedError

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        raise NotImplementedError

    def num_blocks(self) -> int:
        raise NotImplementedError

    def num_registros(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def delete(self) -> None:
        raise NotImplementedError
