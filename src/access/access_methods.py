"""Registry de métodos de acesso (organização × índices) — STUB do M0; implementação: M8 (E08).

Combinações da tabela 4.2 do enunciado (Silberschatz 14.2, 14.4.2):
  Heap {sem índice, Hash UNIQUE secundário, B+ NOT UNIQUE secundário}
  B+   {primário UNIQUE/NOT UNIQUE, secundário clustering NOT UNIQUE}
  Hash {primário UNIQUE, primário NOT UNIQUE, secundário clustering B+ NOT UNIQUE}
Inserção/remoção pela `AccessMethod` mantém todos os índices da tabela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.access.contracts import AccessMethod, Esquema, StorageContext
from src.common.tipos import RID


@dataclass(frozen=True)
class EspecIndice:
    """Índice secundário pedido: campo, tipo ('hash'|'bplus'), unique, clustering."""
    campo: str
    tipo: str
    unique: bool = False
    clustering: bool = False


@dataclass(frozen=True)
class EspecMetodo:
    """Especificação de um método de acesso: organização + campo + índices secundários."""
    org: str                                  # 'heap' | 'bplus' | 'hash'
    campo: str | None = None                  # campo da organização (B+/Hash)
    unique: bool = True
    indices: tuple[EspecIndice, ...] = field(default_factory=tuple)
    nome: str = ""                            # rótulo usado nos CSVs (ex.: 'heap+hash(CPF)')


#: rótulo -> EspecMetodo (preenchido pelo M8 com as combinações da tabela 4.2).
REGISTRY: dict[str, EspecMetodo] = {}


def montar(ctx: StorageContext, esquema: Esquema, espec: EspecMetodo, *,
           nr_estimado: int | None = None, nome_arquivo: str | None = None) -> AccessMethod:
    """Cria (ou abre) a organização e os índices de `espec` e devolve o AccessMethod."""
    raise NotImplementedError("M8/E08")


def inserir(am: AccessMethod, rec: Mapping[str, Any]) -> RID:
    """Insere na organização e em todos os índices."""
    raise NotImplementedError("M8/E08")


def remover(am: AccessMethod, rid: RID) -> None:
    """Remove da organização e de todos os índices."""
    raise NotImplementedError("M8/E08")
