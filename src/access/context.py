
"""Contexto de armazenamento entregue ao executor.

Monta FileManager + BufferManager + Catalog a partir do cfg e expõe
os recursos necessários às camadas superiores.
"""

from __future__ import annotations

from pathlib import Path

from src.access.catalog import Catalog
from src.access.contracts import CatalogAPI, Esquema, StorageContext, TempFile
from src.access.tempfile import ArquivoTemporario
from src.storage.contracts import BufferManagerAPI, Frame
from src.storage.factory import criar_armazenamento


class ContextoArmazenamento(StorageContext):
    _RASCUNHO = "__rascunho__"

    def __init__(
        self,
        cfg,
        base_dir: Path | str | None = None,
        *,
        bm: BufferManagerAPI | None = None,
        catalog: CatalogAPI | None = None,
    ):
        self.cfg = cfg
        self._fm = None

        if bm is None:
            self._fm, self._bm = criar_armazenamento(cfg, base_dir)
        else:
            self._bm = bm

        self._catalog = catalog if catalog is not None else Catalog(self._bm)

        self._temps = []
        self._seq = 0
        self._fid_rascunho = None

    @property
    def bm(self) -> BufferManagerAPI:
        return self._bm

    @property
    def catalog(self) -> CatalogAPI:
        return self._catalog

    def buffer_stats(self) -> dict:
        return self._bm.stats()

    def reset_stats(self) -> None:
        self._bm.reset_stats()

    def drop_all(self) -> None:
        self._bm.drop_all()

    def set_policy(self, area: str, nome: str) -> None:
        self._bm.set_policy(area, nome)

    def work_capacity(self) -> int:
        return self._bm.area_capacity("trabalho")

    def pin_work_page(self) -> Frame:
        if self._fid_rascunho is None:
            nome = self._RASCUNHO
            self._fid_rascunho = (
                self._bm.open(nome)
                if self._bm.exists(nome)
                else self._bm.create(nome, "temp")
            )
        return self._bm.new_page(self._fid_rascunho, "trabalho")

    def unpin_work_page(self, frame: Frame) -> None:
        self._bm.unpin(frame)
        self._bm.free_page(frame.fid, frame.bno)

    def temp_file(self, esquema: Esquema, prefixo: str = "tmp") -> TempFile:
        self._seq += 1
        nome = f"{prefixo}_{self._seq}"

        while self._bm.exists(nome):
            self._seq += 1
            nome = f"{prefixo}_{self._seq}"

        temp = ArquivoTemporario(self._bm, nome, esquema)
        self._temps.append(temp)
        return temp

    def close(self) -> None:
        for temp in self._temps:
            temp.delete()
        self._temps.clear()

        self._bm.flush_all()

        if self._fid_rascunho is not None:
            self._bm.close(self._fid_rascunho)
            self._fid_rascunho = None

        if hasattr(self._catalog, "close"):
            self._catalog.close()

        if self._fm is not None:
            self._fm.close_all()


def criar_contexto(
    cfg,
    base_dir: Path | str | None = None,
    *,
    bm: BufferManagerAPI | None = None,
    catalog: CatalogAPI | None = None,
) -> StorageContext:
    """Fábrica usada pelo executor e pelos benchmarks."""
    return ContextoArmazenamento(cfg, base_dir, bm=bm, catalog=catalog)
