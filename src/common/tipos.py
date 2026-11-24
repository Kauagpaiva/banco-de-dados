"""Tipos simples compartilhados entre camadas."""
from typing import NamedTuple


class RID(NamedTuple):
    """Identificador de registro: (bloco, slot) — ver Decisões fixadas."""
    bloco: int
    slot: int


class PageId(NamedTuple):
    """Identificador de página no buffer: (fid, bno)."""
    fid: int
    bno: int
