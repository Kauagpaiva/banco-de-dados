"""Gerente de Arquivos (Camada 4a) — STUB do M0; implementação: M1 (E01).

Silberschatz 12.3, 12.6, 13.2 (REFERENCIA_LIVRO §1). Contrato: `FileManagerAPI`.
Cabeçalho no bloco 0 (struct: magic, versão, tipo_org, nº alocados, cabeça da lista livre,
extent + `meta` JSON); alocação por extents; lista livre encadeada; modelo de seek D05.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.storage.contracts import FileManagerAPI


class FileManager(FileManagerAPI):
    def __init__(self, cfg, base_dir: Path | str | None = None):
        raise NotImplementedError("M1/E01")

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

    def read_block(self, fid: int, bno: int) -> bytearray:
        raise NotImplementedError

    def write_block(self, fid: int, bno: int, data: bytes) -> None:
        raise NotImplementedError

    def allocate_block(self, fid: int) -> int:
        raise NotImplementedError

    def free_block(self, fid: int, bno: int) -> None:
        raise NotImplementedError

    def num_blocks(self, fid: int) -> int:
        raise NotImplementedError

    def header(self, fid: int) -> dict:
        raise NotImplementedError

    def set_header(self, fid: int, **campos: Any) -> None:
        raise NotImplementedError

    def io_stats(self, fid: int | None = None) -> dict[str, int]:
        raise NotImplementedError

    def reset_io_stats(self) -> None:
        raise NotImplementedError
