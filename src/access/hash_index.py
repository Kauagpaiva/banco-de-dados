"""Índice hash secundário UNIQUE (chave -> RID) — STUB do M0; implementação: M4 (E07).

Silberschatz 14.5 (hash index), reaproveitando buckets/overflow do hashfile.
Contrato: `SecondaryIndex` (search_range -> OperacaoNaoSuportada).
"""
from __future__ import annotations

from typing import Any, Iterator

from src.access.contracts import Campo, SecondaryIndex
from src.storage.contracts import BufferManagerAPI


class HashIndex(SecondaryIndex):
    unique = True

    def __init__(self, bm: BufferManagerAPI, nome: str, campo: Campo, *,
                 nr_estimado: int | None = None, n_buckets: int | None = None,
                 page_impl: type | None = None):
        raise NotImplementedError("M4/E07")

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
