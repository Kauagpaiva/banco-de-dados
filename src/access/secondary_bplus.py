"""Índice B+ secundário — STUB do M0; implementação: M8 (E08).

Silberschatz 14.3.5 / 14.4.2: NOT UNIQUE **sem repetir chave nas folhas** (folha = chave ->
ponteiro para cadeia de blocos de RIDs); `clustering=True` mantém as listas de RIDs ordenadas
por endereço físico; `refs_por_chave=True` guarda a chave primária (organização B+).
Contrato: `SecondaryIndex`.
"""
from __future__ import annotations

from typing import Any, Iterator

from src.access.contracts import Campo, SecondaryIndex
from src.storage.contracts import BufferManagerAPI


class BPlusIndex(SecondaryIndex):
    def __init__(self, bm: BufferManagerAPI, nome: str, campo: Campo, *, unique: bool = False,
                 clustering: bool = False, refs_por_chave: bool = False,
                 page_impl: type | None = None):
        raise NotImplementedError("M8/E08")

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def insert(self, chave: Any, ref: Any) -> None:
        raise NotImplementedError

    def delete(self, chave: Any, ref: Any) -> None:
        raise NotImplementedError

    def search_eq(self, chave: Any) -> Iterator[Any]:
        raise NotImplementedError

    def search_range(self, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[Any]:
        raise NotImplementedError

    def altura(self) -> int:
        raise NotImplementedError

    def num_blocks(self) -> int:
        raise NotImplementedError
