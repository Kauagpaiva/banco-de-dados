
"""Heap File (Camada 4a).

Organização heap de registros sobre páginas slotted.
Silberschatz 13.3.1.

Mantém uma lista de blocos e um mapa de espaço livre em memória,
reconstruído quando o arquivo é aberto.
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional

from src.access.contracts import Esquema, FileOrganization, RecordCodecAPI
from src.access.page import SlottedPage
from src.access.record import RecordCodec
from src.common.erros import OperacaoNaoSuportada, RecordError
from src.common.tipos import Predicado, RID
from src.storage.contracts import BufferManagerAPI


class HeapFile(FileOrganization):
    tipo_org = "heap"
    campo = None
    unique = False
    area = "dados"

    def __init__(
        self,
        bm: BufferManagerAPI,
        nome: str,
        esquema: Esquema,
        *,
        page_impl=None,
        codec: Optional[RecordCodecAPI] = None,
        fragmentacao_max: float = 0.25,
    ):
        if (
            not isinstance(fragmentacao_max, (int, float))
            or isinstance(fragmentacao_max, bool)
            or not 0 <= fragmentacao_max <= 1
        ):
            raise ValueError("fragmentacao_max deve estar entre 0 e 1")

        self.bm = bm
        self.nome = nome
        self.esquema = esquema
        self.page = page_impl or SlottedPage
        self.codec = codec or RecordCodec(esquema)
        self.fragmentacao_max = float(fragmentacao_max)

        self.fid: Optional[int] = None
        self._blocos: list[int] = []
        self._n = 0
        self._espaco_livre: dict[int, int] = {}
        self._cursor: Optional[Iterator] = None

    # ------------------------------------------------------------------ abertura

    def open(self) -> None:
        if self.fid is not None:
            return

        if self.bm.exists(self.nome):
            self.fid = self.bm.open(self.nome)
            meta = self.bm.header(self.fid).get("meta", {})
            self._blocos = list(meta.get("blocos", []))
        else:
            self.fid = self.bm.create(
                self.nome, self.tipo_org, {"blocos": [], "n": 0}
            )
            self._blocos = []

        self._reconstruir_estado()
        self.reset()

    def close(self) -> None:
        if self.fid is None:
            return

        self.bm.set_header(
            self.fid,
            blocos=list(self._blocos),
            n=self._n,
        )
        self.bm.close(self.fid)
        self.fid = None
        self._cursor = None

    def reset(self) -> None:
        self._cursor = None

    def _exigir_aberto(self) -> None:
        if self.fid is None:
            raise RuntimeError("HeapFile não está aberto")

    def _reconstruir_estado(self) -> None:
        """Reconstrói quantidade de registros e mapa de espaço livre."""
        self._exigir_aberto()
        self._n = 0
        self._espaco_livre = {}

        for bno in self._blocos:
            with self.bm.page(self.fid, bno, self.area) as fr:
                self._n += self.page.count(fr.data)
                self._espaco_livre[bno] = self.page.free_space(fr.data)

    # ------------------------------------------------------------------ fragmentação

    def _fragmentacao(self, buf: bytearray) -> float:
        """Calcula a fração da página ocupada por espaço recuperável."""
        compactada = bytearray(buf)
        self.page.compact(compactada)

        recuperavel = max(
            0,
            self.page.free_space(compactada) - self.page.free_space(buf),
        )
        return recuperavel / max(1, len(buf))

    def _compactar_se_necessario(
        self,
        fr,
        bno: int,
        *,
        forcar: bool = False,
    ) -> bool:
        """Compacta se a fragmentação exceder o limite ou se for solicitado."""
        fragmentacao = self._fragmentacao(fr.data)

        if forcar or fragmentacao > self.fragmentacao_max:
            self.page.compact(fr.data)
            fr.mark_dirty()
            self._espaco_livre[bno] = self.page.free_space(fr.data)
            return True

        self._espaco_livre[bno] = self.page.free_space(fr.data)
        return False

    # ------------------------------------------------------------------ inserção

    def insert(self, rec: Mapping[str, Any]) -> RID:
        self._exigir_aberto()
        return self._append(rec)

    def _append(self, rec: Mapping[str, Any]) -> RID:
        data = self.codec.encode(rec)

        # Tenta aproveitar os blocos já existentes.
        for bno in self._blocos:
            with self.bm.page(self.fid, bno, self.area) as fr:
                self._compactar_se_necessario(fr, bno)

                slot = self.page.insert(fr.data, data)

                # Se não coube, tenta novamente após compactar.
                if slot is None:
                    self._compactar_se_necessario(
                        fr, bno, forcar=True
                    )
                    slot = self.page.insert(fr.data, data)

                if slot is not None:
                    fr.mark_dirty()
                    self._n += 1
                    self._espaco_livre[bno] = self.page.free_space(fr.data)
                    return RID(bno, slot)

        # Nenhum bloco existente comportou o registro.
        with self.bm.fresh_page(self.fid, self.area) as fr:
            bno = fr.bno
            self.page.format(fr.data)
            slot = self.page.insert(fr.data, data)

            if slot is not None:
                fr.mark_dirty()

        if slot is None:
            self.bm.free_page(self.fid, bno)
            raise RecordError(
                f"registro de {len(data)} bytes não cabe em uma página vazia"
            )

        self._blocos.append(bno)
        self._n += 1

        with self.bm.page(self.fid, bno, self.area) as fr:
            self._espaco_livre[bno] = self.page.free_space(fr.data)

        return RID(bno, slot)

    # ------------------------------------------------------------------ leitura

    def read(self, rid: RID) -> dict:
        self._exigir_aberto()

        if rid.bloco not in self._blocos:
            raise KeyError(f"RID inexistente: {rid}")

        with self.bm.page(self.fid, rid.bloco, self.area) as fr:
            bruto = self.page.get(fr.data, rid.slot)

        if bruto is None:
            raise KeyError(f"RID inexistente: {rid}")

        return self.codec.decode(bruto)

    # ------------------------------------------------------------------ exclusão

    def delete(self, rid: RID) -> None:
        self._exigir_aberto()

        if rid.bloco not in self._blocos:
            raise KeyError(f"RID inexistente: {rid}")

        with self.bm.page(
            self.fid, rid.bloco, self.area, dirty=True
        ) as fr:
            if self.page.get(fr.data, rid.slot) is None:
                raise KeyError(f"RID inexistente: {rid}")

            self.page.delete(fr.data, rid.slot)
            self._n -= 1

            self._compactar_se_necessario(fr, rid.bloco)

            self._espaco_livre[rid.bloco] = self.page.free_space(fr.data)

    # ------------------------------------------------------------------ atualização

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        self._exigir_aberto()

        if rid.bloco not in self._blocos:
            raise KeyError(f"RID inexistente: {rid}")

        data = self.codec.encode(rec)

        with self.bm.page(
            self.fid, rid.bloco, self.area, dirty=True
        ) as fr:
            if self.page.get(fr.data, rid.slot) is None:
                raise KeyError(f"RID inexistente: {rid}")

            if self.page.update(fr.data, rid.slot, data):
                self._espaco_livre[rid.bloco] = self.page.free_space(fr.data)
                return rid

            # Uma compactação pode liberar espaço suficiente.
            self._compactar_se_necessario(
                fr, rid.bloco, forcar=True
            )

            if self.page.update(fr.data, rid.slot, data):
                self._espaco_livre[rid.bloco] = self.page.free_space(fr.data)
                return rid

        # O registro não coube nem após compactar.
        self.delete(rid)
        return self.insert(rec)

    # ------------------------------------------------------------------ varredura

    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        self._exigir_aberto()

        for bno in list(self._blocos):
            with self.bm.page(
                self.fid, bno, self.area, toss=toss
            ) as fr:
                brutos = [
                    (slot, self.page.get(fr.data, slot))
                    for slot in self.page.slots(fr.data)
                ]

            # A página já foi liberada antes de entregar os registros.
            for slot, bruto in brutos:
                if bruto is not None:
                    yield RID(bno, slot), self.codec.decode(bruto)

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        self._exigir_aberto()

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

    # ------------------------------------------------------------------ busca

    def find(self, campo: str, valor: Any) -> Optional[RID]:
        self._cursor = self.find_all(campo, "=", valor)
        return self.find_next()

    def find_next(self) -> Optional[RID]:
        if self._cursor is None:
            return None

        par = next(self._cursor, None)

        if par is None:
            self._cursor = None
            return None

        return par[0]

    def find_all(
        self,
        campo: str,
        op: str,
        valor: Any,
    ) -> Iterator[tuple[RID, dict]]:
        pred = Predicado(campo, op, valor).validar()
        self.esquema.campo(campo)

        def iterar():
            for rid, rec in self.scan():
                if pred.avaliar(rec):
                    yield rid, rec

        return iterar()

    def find_ordered(
        self,
        campo: str,
        lo: Any = None,
        hi: Any = None,
        incl_lo: bool = True,
        incl_hi: bool = True,
    ):
        raise OperacaoNaoSuportada("Heap não fornece ordenação")

    # ------------------------------------------------------------------ manutenção

    def reorganize(self) -> None:
        self._exigir_aberto()

        for bno in self._blocos:
            with self.bm.page(
                self.fid, bno, self.area, dirty=True
            ) as fr:
                self.page.compact(fr.data)
                self._espaco_livre[bno] = self.page.free_space(fr.data)

    # ------------------------------------------------------------------ métricas

    def num_blocks(self) -> int:
        return len(self._blocos)

    def num_registros(self) -> int:
        return self._n

    def ocupacao(self) -> dict[str, int]:
        n = len(self._blocos)
        return {
            "dados": n,
            "overflow": 0,
            "indice": 0,
            "total": n,
            "registros": self._n,
        }
