"""Gerente de Buffer Pool (Camada 4b) — STUB do M0; implementação: M1 (E02).

Silberschatz 13.5, 19.5 (REFERENCIA_LIVRO §2). Contrato: `BufferManagerAPI`
(os context managers `page`/`fresh_page` já vêm prontos do contrato).
**Único módulo que chama `FileManager.read_block/write_block`.**
"""
from __future__ import annotations

from typing import Any

from src.storage.contracts import BufferManagerAPI, Frame
from src.storage.file_manager import FileManager


class BufferManager(BufferManagerAPI):
    def __init__(self, cfg, fm: FileManager):
        raise NotImplementedError("M1/E02")

    def pin(self, fid: int, bno: int, area: str = "dados") -> Frame:
        raise NotImplementedError

    def unpin(self, frame: Frame, dirty: bool = False, toss: bool = False) -> None:
        raise NotImplementedError

    def new_page(self, fid: int, area: str = "dados") -> Frame:
        raise NotImplementedError

    def free_page(self, fid: int, bno: int) -> None:
        raise NotImplementedError

    def flush(self, fid: int, bno: int) -> None:
        raise NotImplementedError

    def flush_all(self) -> None:
        raise NotImplementedError

    def drop_all(self) -> None:
        raise NotImplementedError

    def set_policy(self, area: str, nome: str) -> None:
        raise NotImplementedError

    def area_capacity(self, area: str) -> int:
        raise NotImplementedError

    def stats(self) -> dict:
        raise NotImplementedError

    def reset_stats(self) -> None:
        raise NotImplementedError

    def assert_no_pins(self) -> None:
        raise NotImplementedError

    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int:
        raise NotImplementedError

    def open(self, nome: str) -> int:
        raise NotImplementedError

    def exists(self, nome: str) -> bool:
        raise NotImplementedError

    def close(self, fid: int) -> None:
        raise NotImplementedError

    def delete(self, nome: str) -> None:
        raise NotImplementedError

    def num_blocks(self, fid: int) -> int:
        raise NotImplementedError

    def header(self, fid: int) -> dict:
        raise NotImplementedError

    def set_header(self, fid: int, **campos: Any) -> None:
        raise NotImplementedError
