"""Hash estático externo como organização primária (Camada 3) — STUB do M0; implementação: M4 (E07).

Silberschatz 14.5 (hashing estático, buckets, overflow chaining). REFERENCIA_LIVRO §5.
nB buckets primários contíguos (blocos 1..nB), nB = ceil(nr/(fr*fill_factor)); bucket = slotted
page + ponteiro de overflow na área reservada; FNV-1a 64. Busca **e** remoção percorrem a
cadeia de overflow inteira. Contrato: `FileOrganization`.
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional

from src.access.contracts import Esquema, FileOrganization, RecordCodecAPI
from src.common.tipos import RID
from src.storage.contracts import BufferManagerAPI


class HashFile(FileOrganization):
    tipo_org = "hash"

    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, campo: str, *,
                 unique: bool = True, n_buckets: int | None = None,
                 nr_estimado: int | None = None, page_impl: type | None = None,
                 codec: RecordCodecAPI | None = None):
        raise NotImplementedError("M4/E07")

    def estatisticas(self) -> dict:
        """{'buckets', 'overflow', 'cadeia_max', 'cadeia_media', 'fator_carga', 'cv_ocupacao'}."""
        raise NotImplementedError


    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError

    def find(self, campo: str, valor: Any) -> Optional[RID]:
        raise NotImplementedError

    def find_next(self) -> Optional[RID]:
        raise NotImplementedError

    def read(self, rid: RID) -> dict:
        raise NotImplementedError

    def insert(self, rec: Mapping[str, Any]) -> RID:
        raise NotImplementedError

    def delete(self, rid: RID) -> None:
        raise NotImplementedError

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        raise NotImplementedError

    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        raise NotImplementedError

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        raise NotImplementedError

    def find_all(self, campo: str, op: str, valor: Any) -> Iterator[tuple[RID, dict]]:
        raise NotImplementedError

    def find_ordered(self, campo: str, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[tuple[RID, dict]]:
        raise NotImplementedError

    def reorganize(self) -> None:
        raise NotImplementedError

    def num_blocks(self) -> int:
        raise NotImplementedError

    def num_registros(self) -> int:
        raise NotImplementedError

    def ocupacao(self) -> dict[str, int]:
        raise NotImplementedError


def fnv1a64(dado: bytes) -> int:
    """FNV-1a de 64 bits (determinístico, ao contrário de `hash()` do Python)."""
    raise NotImplementedError("M4/E07")
