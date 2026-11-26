
"""Fábrica de componentes da camada de armazenamento."""

from pathlib import Path

from src.storage.buffer_manager import BufferManager
from src.storage.file_manager import FileManager


def criar_armazenamento(cfg, base_dir: Path | str | None = None):
    """Cria o FileManager e o BufferManager associados."""
    fm = FileManager(cfg, base_dir)
    bm = BufferManager(cfg, fm)
    return fm, bm
