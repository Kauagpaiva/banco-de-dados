"""Referência SQLite — STUB do M0; implementação: M7 (E09).

Exporta a mesma base para `data/<perfil>/ref.sqlite` e responde consultas de referência
(oráculo de resultado para seleções e junções).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def exportar(cfg, caminho: Path | str | None = None) -> Path:
    """Cria o banco SQLite com as 6 tabelas geradas por `datagen`; devolve o caminho."""
    raise NotImplementedError("M7/E09")


def consultar(caminho: Path | str, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
    raise NotImplementedError("M7/E09")
