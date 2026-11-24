"""Arquivo Heap (Camada 3) — STUB do M0; implementação: M2 (E04).

Silberschatz 13.3.1 (heap file organization). Free-space map (escolha em docs/decisoes/M2.md);
compactação de bloco quando a fragmentação passa de `fragmentacao_max`. Contrato: `FileOrganization`.
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional

from src.access.contracts import Esquema, FileOrganization, RecordCodecAPI
from src.common.tipos import RID
from src.storage.contracts import BufferManagerAPI


class HeapFile(FileOrganization):
    tipo_org = "heap"

    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, *,
                 page_impl: type | None = None, codec: RecordCodecAPI | None = None,
                 fragmentacao_max: float = 0.25):
        raise NotImplementedError("M2/E04")

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError

    def find(self, campo: str, valor: Any) -> Optional[RID]:
        raise NotImplementedError

    def find_next(self) -> Optional[RID]:
        raise NotImplementedError

    def read(self, rid: RID) -> dict:
        raise NotImplementedError

    def insert(self, rec: Mapping[str, Any]) -> RID:
        raise NotImplementedError

    def delete(self, rid: RID) -> None:
        raise NotImplementedError

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        raise NotImplementedError

    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        raise NotImplementedError

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        raise NotImplementedError

    def find_all(self, campo: str, op: str, valor: Any) -> Iterator[tuple[RID, dict]]:
        raise NotImplementedError

    def find_ordered(self, campo: str, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[tuple[RID, dict]]:
        raise NotImplementedError

    def reorganize(self) -> None:
        raise NotImplementedError

    def num_blocks(self) -> int:
        raise NotImplementedError

    def num_registros(self) -> int:
        raise NotImplementedError

    def ocupacao(self) -> dict[str, int]:
        raise NotImplementedError
