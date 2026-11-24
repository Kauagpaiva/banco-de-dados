"""Carga de tabelas em qualquer método de acesso — STUB do M0; implementação: M8 (E09, parte loader).

Cria (tabela × EspecMetodo) via `fachada.montar`, carrega os registros do gerador (bulk load
para B+, Silberschatz 14.5) e atualiza as estatísticas do catálogo (nr, br, fr, V).
"""
from __future__ import annotations

from typing import Iterable, Optional

from src.executor.contracts import AccessMethod, StorageContext
from src.executor.fachada import EspecMetodo


def carregar(ctx: StorageContext, nome_tabela: str, espec: EspecMetodo,
             registros: Optional[Iterable[dict]] = None) -> AccessMethod:
    """`registros=None` → `datagen.gerar_tabela(ctx.cfg, nome_tabela)`."""
    raise NotImplementedError("M8/E09")
