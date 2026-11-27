
"""Arquivo temporário (runs, partições, saída materializada).

Silberschatz 15.4 e 15.5.5.
Páginas na área 'trabalho' via BufferManager.
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping

from src.access.contracts import Esquema, RecordCodecAPI, TempFile
from src.access.page import SlottedPage
from src.access.record import RecordCodec
from src.common.erros import RecordError
from src.storage.contracts import BufferManagerAPI


class ArquivoTemporario(TempFile):
    area = "trabalho"

    def __init__(
        self,
        bm: BufferManagerAPI,
        nome: str,
        esquema: Esquema,
        *,
        page_impl: type | None = None,
        codec: RecordCodecAPI | None = None,
    ):
        self.bm = bm
        self.nome = nome
        self.esquema = esquema
        self.page = page_impl or SlottedPage
        self.codec = codec or RecordCodec(esquema)

        self.fid = bm.create(nome, "temp")
        self._blocos: list[int] = []
        self._n = 0
        self._apagado = False

    def append(self, rec: Mapping[str, Any]) -> None:
        if self._apagado:
            raise RuntimeError("Arquivo temporário já foi excluído")

        data = self.codec.encode(rec)

        # Tenta inserir no último bloco.
        if self._blocos:
            bno = self._blocos[-1]

            with self.bm.page(self.fid, bno, self.area) as fr:
                slot = self.page.insert(fr.data, data)

                if slot is not None:
                    fr.mark_dirty()
                    self._n += 1
                    return

        # Se não coube, cria uma nova página.
        with self.bm.fresh_page(self.fid, self.area) as fr:
            bno = fr.bno
            self.page.format(fr.data)
            slot = self.page.insert(fr.data, data)
            fr.mark_dirty()

        if slot is None:
            self.bm.free_page(self.fid, bno)
            raise RecordError(
                f"registro de {len(data)} bytes não cabe em uma página vazia"
            )

        self._blocos.append(bno)
        self._n += 1

    def blocks(self) -> Iterator[int]:
        return iter(list(self._blocos))

    def records_in_block(self, bno: int) -> list[dict]:
        if bno not in self._blocos:
            raise KeyError(f"Bloco inexistente: {bno}")

        with self.bm.page(self.fid, bno, self.area) as fr:
            brutos = [
                self.page.get(fr.data, slot)
                for slot in self.page.slots(fr.data)
            ]

        return [
            self.codec.decode(bruto)
            for bruto in brutos
            if bruto is not None
        ]

    def scan(self, toss: bool = False) -> Iterator[dict]:
        for bno in list(self._blocos):
            with self.bm.page(
                self.fid, bno, self.area, toss=toss
            ) as fr:
                brutos = [
                    self.page.get(fr.data, slot)
                    for slot in self.page.slots(fr.data)
                ]

            for bruto in brutos:
                if bruto is not None:
                    yield self.codec.decode(bruto)

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        for bno in list(self._blocos):
            with self.bm.page(
                self.fid, bno, self.area, toss=toss
            ) as fr:
                brutos = [
                    self.page.get(fr.data, slot)
                    for slot in self.page.slots(fr.data)
                ]

            yield [
                self.codec.decode(bruto)
                for bruto in brutos
                if bruto is not None
            ]

    def num_blocks(self) -> int:
        return len(self._blocos)

    def num_registros(self) -> int:
        return self._n

    def close(self) -> None:
        # Mantém o arquivo acessível até delete(), como no contrato do fake.
        self.bm.flush_all()

    def delete(self) -> None:
        if not self._apagado:
            self.bm.delete(self.nome)
            self._apagado = True
            self.fid = None
            self._blocos.clear()
            self._n = 0
