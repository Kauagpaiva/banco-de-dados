"""Contexto de armazenamento entregue ao executor — STUB do M0; implementação: M2.

Monta FileManager + BufferManager + Catalog a partir do `cfg` e expõe só o que o executor
precisa (Silberschatz 15.1: medida de custo = transferências de bloco + seeks).
Contrato: `StorageContext`. Única porta de criação do armazenamento para as camadas de cima.
"""
from __future__ import annotations

from pathlib import Path

from src.access.contracts import CatalogAPI, Esquema, StorageContext, TempFile
from src.storage.contracts import BufferManagerAPI, Frame


class ContextoArmazenamento(StorageContext):
    def __init__(self, cfg, base_dir: Path | str | None = None, *,
                 bm: BufferManagerAPI | None = None, catalog: CatalogAPI | None = None):
        """`bm`/`catalog` injetáveis (testes com fakes); None → FileManager+BufferManager+Catalog reais."""
        raise NotImplementedError("M2")

    @property
    def bm(self) -> BufferManagerAPI:
        raise NotImplementedError

    @property
    def catalog(self) -> CatalogAPI:
        raise NotImplementedError

    def buffer_stats(self) -> dict:
        raise NotImplementedError

    def reset_stats(self) -> None:
        raise NotImplementedError

    def drop_all(self) -> None:
        raise NotImplementedError

    def set_policy(self, area: str, nome: str) -> None:
        raise NotImplementedError

    def work_capacity(self) -> int:
        raise NotImplementedError

    def pin_work_page(self) -> Frame:
        raise NotImplementedError

    def unpin_work_page(self, frame: Frame) -> None:
        raise NotImplementedError

    def temp_file(self, esquema: Esquema, prefixo: str = "tmp") -> TempFile:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def criar_contexto(cfg, base_dir: Path | str | None = None, *,
                   bm: BufferManagerAPI | None = None,
                   catalog: CatalogAPI | None = None) -> StorageContext:
    """Fábrica usada pelo executor/bench: `ContextoArmazenamento(cfg, base_dir, bm=, catalog=)`."""
    return ContextoArmazenamento(cfg, base_dir, bm=bm, catalog=catalog)
