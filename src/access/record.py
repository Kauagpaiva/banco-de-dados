"""Codificação de registros (Camada 3) — STUB do M0; implementação: M2 (E03).

Silberschatz 13.2.2 (Fig. 13.5): null bitmap + parte fixa + (offset,len) dos variáveis +
área variável; datas como int (dias); listas serializadas. Contrato: `RecordCodecAPI`.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.access.contracts import Esquema, RecordCodecAPI


class RecordCodec(RecordCodecAPI):
    def __init__(self, esquema: Esquema):
        raise NotImplementedError("M2/E03")

    def encode(self, rec: Mapping[str, Any]) -> bytes:
        raise NotImplementedError

    def decode(self, data: bytes) -> dict:
        raise NotImplementedError

    @property
    def max_size(self) -> int:
        raise NotImplementedError
