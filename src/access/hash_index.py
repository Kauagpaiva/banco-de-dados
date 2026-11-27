"""Índice hash secundário UNIQUE (chave -> RID) — M4 (E07).

Silberschatz 14.5 (hash index; 14.5.1 buckets e overflow). Reaproveita o `HashFile`: o índice é
um arquivo hash cujos "registros" são entradas (chave, RID), guardadas na área 'indice' do buffer.
Busca e remoção percorrem a cadeia de overflow inteira. Contrato: `SecondaryIndex`
(`search_range` → `OperacaoNaoSuportada`: hash não preserva ordem).

Entrada codificada por `CodecEntrada` (formato fixo, sem depender do RecordCodec do M2):
    flag(1: 0 = chave nula) · bloco(<I) · slot(<H) · bytes da chave
com a chave em `<q` (int), `<d` (float), `<i` ordinal (date) ou UTF-8 (char/varchar).
"""
from __future__ import annotations

import datetime as dt
import struct
from typing import Any, Iterator, Mapping

from src.access.contracts import Campo, Esquema, RecordCodecAPI, SecondaryIndex
from src.access.hashfile import RESERVA_OVERFLOW, HashFile
from src.common.erros import OperacaoNaoSuportada, RecordError
from src.common.tipos import RID
from src.storage.contracts import BufferManagerAPI

_REF = struct.Struct("<BIH")          # flag, bloco, slot
_FIXOS = {"int": struct.Struct("<q"), "float": struct.Struct("<d"), "date": struct.Struct("<i")}


def esquema_entrada(campo: Campo) -> Esquema:
    """Esquema lógico da entrada do índice: (chave, bloco, slot)."""
    return Esquema(f"idx_{campo.nome}", (Campo("chave", campo.tipo, campo.nulo, campo.max_itens),
                                         Campo("bloco", "int"), Campo("slot", "int")), ("chave",))


class CodecEntrada(RecordCodecAPI):
    """Codec compacto das entradas (chave, RID) do HashIndex. Valida tamanhos (offset-safe)."""

    def __init__(self, campo: Campo):
        if campo.base == "list":
            raise ValueError(f"HashIndex não suporta chave do tipo lista ({campo.nome})")
        self.campo = campo
        self.esquema = esquema_entrada(campo)
        self._fixo = _FIXOS.get(campo.base)
        self._max = _REF.size + (self._fixo.size if self._fixo else campo.n)

    @property
    def max_size(self) -> int:
        return self._max

    def encode(self, rec: Mapping[str, Any]) -> bytes:
        chave, bloco, slot = rec["chave"], rec["bloco"], rec["slot"]
        if not (0 <= bloco < 2 ** 32 and 0 <= slot < 2 ** 16):
            raise RecordError(f"RID fora do limite da entrada: ({bloco}, {slot})")
        if chave is None:
            if not self.campo.nulo:
                raise RecordError(f"{self.campo.nome}: chave nula em campo NOT NULL")
            return _REF.pack(0, bloco, slot)
        b = self.campo.base
        try:
            if b == "date":
                corpo = self._fixo.pack(chave.toordinal())
            elif self._fixo:
                corpo = self._fixo.pack(chave)
            else:
                corpo = str(chave).encode("utf-8")
                if len(corpo) > self.campo.n:
                    raise RecordError(f"{self.campo.nome}: chave com {len(corpo)} B > {self.campo.n}")
        except (struct.error, AttributeError) as e:
            raise RecordError(f"{self.campo.nome}: chave inválida {chave!r}: {e}") from None
        return _REF.pack(1, bloco, slot) + corpo

    def decode(self, data: bytes) -> dict:
        data = bytes(data)
        if len(data) < _REF.size or len(data) > self._max:
            raise RecordError(f"entrada de índice com tamanho inválido ({len(data)} B)")
        flag, bloco, slot = _REF.unpack_from(data, 0)
        corpo = data[_REF.size:]
        if flag == 0:
            chave = None
        elif self._fixo:
            if len(corpo) != self._fixo.size:
                raise RecordError("entrada de índice com chave de tamanho errado")
            v = self._fixo.unpack(corpo)[0]
            chave = dt.date.fromordinal(v) if self.campo.base == "date" else v
        else:
            chave = corpo.decode("utf-8")
        return {"chave": chave, "bloco": bloco, "slot": slot}


class HashIndex(SecondaryIndex):
    """Índice hash secundário UNIQUE sobre `campo` (Silberschatz 14.5): chave → RID."""
    unique = True
    clustering = False
    refs_por_chave = False

    def __init__(self, bm: BufferManagerAPI, nome: str, campo: Campo, *,
                 nr_estimado: int | None = None, n_buckets: int | None = None,
                 page_impl: type | None = None):
        if not isinstance(campo, Campo):
            raise TypeError("HashIndex: `campo` deve ser um Campo (o tipo define a codificação)")
        self.bm = bm
        self.nome = nome
        self.campo = campo.nome
        self._codec = CodecEntrada(campo)
        if n_buckets is None and nr_estimado is None:
            raise ValueError("HashIndex: informe n_buckets ou nr_estimado")
        self._hf = HashFile(bm, nome, self._codec.esquema, "chave", unique=True,
                            n_buckets=n_buckets, nr_estimado=nr_estimado,
                            page_impl=page_impl, codec=self._codec)
        self._hf.area = "indice"

    @property
    def arquivo(self) -> HashFile:
        """Arquivo hash subjacente (para `estatisticas()`/`ocupacao()`)."""
        return self._hf

    def open(self) -> None:
        self._hf.open()

    def close(self) -> None:
        self._hf.close()

    @staticmethod
    def _rid(ref: Any) -> RID:
        if not isinstance(ref, tuple) or len(ref) != 2:
            raise TypeError(f"HashIndex guarda RID; recebeu {ref!r}")
        return RID(int(ref[0]), int(ref[1]))

    def insert(self, chave: Any, ref: Any) -> None:
        rid = self._rid(ref)
        self._hf.insert({"chave": chave, "bloco": rid.bloco, "slot": rid.slot})

    def delete(self, chave: Any, ref: Any) -> None:
        """Procura (chave, ref) na cadeia toda do bucket; KeyError se ausente."""
        rid = self._rid(ref)
        hf = self._hf
        for anterior, bno, itens, _ in hf._cadeia(hf.bucket_de(chave)):
            for slot, dado in itens:
                e = self._codec.decode(dado)
                if e["chave"] == chave and (e["bloco"], e["slot"]) == rid:
                    hf._remover(anterior, bno, slot)
                    return
        raise KeyError(f"{self.nome}: par inexistente ({chave!r}, {rid})")

    def search_eq(self, chave: Any) -> Iterator[Any]:
        for _, e in self._hf.find_all("chave", "=", chave):
            yield RID(e["bloco"], e["slot"])

    def search_range(self, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[Any]:
        raise OperacaoNaoSuportada("índice hash não suporta busca por faixa (Silberschatz 14.5)")

    def altura(self) -> int:
        return 1

    def num_blocks(self) -> int:
        return self._hf.num_blocks()

    def estatisticas(self) -> dict:
        return self._hf.estatisticas()


__all__ = ["HashIndex", "CodecEntrada", "esquema_entrada", "RESERVA_OVERFLOW"]
