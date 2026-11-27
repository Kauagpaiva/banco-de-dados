
"""Codificação de registros (Camada 3).

Silberschatz 13.2.2 (Fig. 13.5):
bitmap de nulos + parte fixa + descritores (offset, tamanho)
dos campos variáveis + área variável.
"""
from __future__ import annotations

import datetime as dt
import math
import struct
from typing import Any, Mapping

from src.access.contracts import Campo, Esquema, RecordCodecAPI
from src.common.erros import RecordError


_EPOCA = dt.date(1970, 1, 1)


def _validar_valor(campo: Campo, valor: Any) -> None:
    """Valida um valor individual conforme o tipo declarado no esquema."""
    base = campo.base

    if base == "int":
        valido = isinstance(valor, int) and not isinstance(valor, bool)

    elif base == "float":
        valido = isinstance(valor, (int, float)) and not isinstance(valor, bool)

    elif base == "date":
        valido = isinstance(valor, dt.date) and not isinstance(valor, dt.datetime)

    elif base in ("char", "varchar"):
        valido = (
            isinstance(valor, str)
            and len(valor.encode("utf-8")) <= campo.n
        )
        if valido and base == "char" and valor != valor.rstrip(" \0"):
            raise RecordError(
                f"{campo.nome}: char(n) não pode terminar em espaço ou \\0"
            )

    elif base == "list":
        valido = (
            isinstance(valor, list)
            and len(valor) <= campo.max_itens
            and all(
                isinstance(item, str)
                and len(item.encode("utf-8")) <= campo.n
                for item in valor
            )
        )

    else:
        valido = False

    if not valido:
        raise RecordError(
            f"{campo.nome}: valor inválido para {campo.tipo}: {valor!r}"
        )


def _validar_registro(esquema: Esquema, registro: Mapping[str, Any]) -> None:
    """Valida campos obrigatórios, extras, nulos e tipos."""
    extras = set(registro) - set(esquema.nomes())

    if extras:
        raise RecordError(
            f"{esquema.nome}: campos desconhecidos {sorted(extras)}"
        )

    for campo in esquema.campos:
        if campo.nome not in registro:
            raise RecordError(
                f"{esquema.nome}: falta o campo {campo.nome}"
            )

        valor = registro[campo.nome]

        if valor is None:
            if not campo.nulo:
                raise RecordError(
                    f"{esquema.nome}.{campo.nome}: nulo em campo NOT NULL"
                )
        else:
            _validar_valor(campo, valor)


class RecordCodec(RecordCodecAPI):
    """Codifica e decodifica registros em formato binário."""

    def __init__(self, esquema: Esquema):
        self.esquema = esquema
        self._campos = esquema.campos
        self._bitmap_size = (len(self._campos) + 7) // 8

        # Tamanho da parte fixa: bitmap + campos fixos + descritores.
        self._fixed_size = self._bitmap_size

        # Tamanho máximo da área variável.
        self._variable_max = 0

        for campo in self._campos:
            base = campo.base

            if base == "int":
                self._fixed_size += 4

            elif base == "float":
                self._fixed_size += 8

            elif base == "date":
                self._fixed_size += 4

            elif base == "char":
                self._fixed_size += campo.n

            elif base == "varchar":
                # offset (4 bytes) + tamanho (4 bytes)
                self._fixed_size += 8
                self._variable_max += campo.n

            elif base == "list":
                self._fixed_size += 8
                self._variable_max += (
                    4 + campo.max_itens * (4 + campo.n)
                )

            else:
                raise RecordError(
                    f"Tipo não suportado no esquema: {campo.tipo}"
                )

        self._max_size = self._fixed_size + self._variable_max

    @property
    def max_size(self) -> int:
        return self._max_size

    def encode(self, rec: Mapping[str, Any]) -> bytes:
        """Transforma um dicionário em uma sequência binária."""
        _validar_registro(self.esquema, rec)

        # Reserva o espaço da parte fixa.
        fixo = bytearray(self._fixed_size)
        variavel = bytearray()

        pos = self._bitmap_size

        for i, campo in enumerate(self._campos):
            valor = rec[campo.nome]
            base = campo.base

            # Bit 1 significa campo nulo.
            if valor is None:
                fixo[i // 8] |= 1 << (i % 8)

                if base in ("varchar", "list"):
                    struct.pack_into("<II", fixo, pos, 0, 0)
                    pos += 8
                elif base == "char":
                    pos += campo.n
                elif base == "int":
                    pos += 4
                elif base == "float":
                    pos += 8
                elif base == "date":
                    pos += 4

                continue

            if base == "int":
                if not -(2**31) <= valor <= 2**31 - 1:
                    raise RecordError(
                        f"{campo.nome}: inteiro fora do intervalo de 32 bits"
                    )
                struct.pack_into("<i", fixo, pos, valor)
                pos += 4

            elif base == "float":
                try:
                    struct.pack_into("<d", fixo, pos, float(valor))
                except (OverflowError, struct.error):
                    raise RecordError(
                        f"{campo.nome}: float fora do intervalo permitido"
                    ) from None
                pos += 8

            elif base == "date":
                dias = (valor - _EPOCA).days
                struct.pack_into("<i", fixo, pos, dias)
                pos += 4

            elif base == "char":
                bruto = valor.encode("utf-8")
                fixo[pos:pos + campo.n] = (
                    bruto + bytes(campo.n - len(bruto))
                )
                pos += campo.n

            elif base == "varchar":
                bruto = valor.encode("utf-8")
                offset = self._fixed_size + len(variavel)

                struct.pack_into(
                    "<II", fixo, pos, offset, len(bruto)
                )
                variavel.extend(bruto)
                pos += 8

            elif base == "list":
                # Formato: quantidade + (tamanho + conteúdo) de cada item.
                bruto = bytearray()
                struct.pack_into("<I", bruto := bytearray(4), 0, len(valor))

                for item in valor:
                    item_bytes = item.encode("utf-8")
                    bruto.extend(struct.pack("<I", len(item_bytes)))
                    bruto.extend(item_bytes)

                offset = self._fixed_size + len(variavel)

                struct.pack_into(
                    "<II", fixo, pos, offset, len(bruto)
                )
                variavel.extend(bruto)
                pos += 8

        resultado = bytes(fixo + variavel)

        if len(resultado) > self.max_size:
            raise RecordError("Registro codificado excede max_size")

        return resultado

    def decode(self, data: bytes) -> dict:
        """Reconstrói o dicionário a partir de sua representação binária."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise RecordError("Dados do registro devem ser bytes")

        data = bytes(data)

        if len(data) < self._fixed_size:
            raise RecordError("Registro menor que a parte fixa esperada")

        if len(data) > self.max_size:
            raise RecordError("Registro maior que max_size")

        resultado = {}
        pos = self._bitmap_size

        for i, campo in enumerate(self._campos):
            base = campo.base
            nulo = bool(data[i // 8] & (1 << (i % 8)))

            if base == "int":
                if nulo:
                    valor = None
                    pos += 4
                else:
                    valor = struct.unpack_from("<i", data, pos)[0]
                    pos += 4

            elif base == "float":
                if nulo:
                    valor = None
                    pos += 8
                else:
                    valor = struct.unpack_from("<d", data, pos)[0]
                    pos += 8

            elif base == "date":
                if nulo:
                    valor = None
                    pos += 4
                else:
                    dias = struct.unpack_from("<i", data, pos)[0]
                    try:
                        valor = _EPOCA + dt.timedelta(days=dias)
                    except OverflowError:
                        raise RecordError(
                            f"{campo.nome}: data inválida"
                        ) from None
                    pos += 4

            elif base == "char":
                if nulo:
                    valor = None
                else:
                    bruto = data[pos:pos + campo.n].rstrip(b"\0")
                    try:
                        valor = bruto.decode("utf-8")
                    except UnicodeDecodeError:
                        raise RecordError(
                            f"{campo.nome}: texto UTF-8 inválido"
                        ) from None
                pos += campo.n

            elif base in ("varchar", "list"):
                offset, tamanho = struct.unpack_from("<II", data, pos)
                pos += 8

                if nulo:
                    if offset != 0 or tamanho != 0:
                        raise RecordError(
                            f"{campo.nome}: descritor inválido para campo nulo"
                        )
                    valor = None
                    resultado[campo.nome] = valor
                    continue

                fim = offset + tamanho

                if (
                    offset < self._fixed_size
                    or fim < offset
                    or fim > len(data)
                ):
                    raise RecordError(
                        f"{campo.nome}: offset/tamanho fora do registro"
                    )

                bruto = data[offset:fim]

                if base == "varchar":
                    try:
                        valor = bruto.decode("utf-8")
                    except UnicodeDecodeError:
                        raise RecordError(
                            f"{campo.nome}: texto UTF-8 inválido"
                        ) from None

                else:
                    if len(bruto) < 4:
                        raise RecordError(
                            f"{campo.nome}: lista truncada"
                        )

                    quantidade = struct.unpack_from("<I", bruto, 0)[0]

                    if quantidade > campo.max_itens:
                        raise RecordError(
                            f"{campo.nome}: quantidade de itens inválida"
                        )

                    valor = []
                    p = 4

                    for _ in range(quantidade):
                        if p + 4 > len(bruto):
                            raise RecordError(
                                f"{campo.nome}: tamanho de item ausente"
                            )

                        tamanho_item = struct.unpack_from(
                            "<I", bruto, p
                        )[0]
                        p += 4

                        if (
                            tamanho_item > campo.n
                            or p + tamanho_item > len(bruto)
                        ):
                            raise RecordError(
                                f"{campo.nome}: item fora dos limites"
                            )

                        try:
                            item = bruto[p:p + tamanho_item].decode("utf-8")
                        except UnicodeDecodeError:
                            raise RecordError(
                                f"{campo.nome}: item UTF-8 inválido"
                            ) from None

                        valor.append(item)
                        p += tamanho_item

                    if p != len(bruto):
                        raise RecordError(
                            f"{campo.nome}: bytes excedentes na lista"
                        )

            else:
                raise RecordError(f"Tipo não suportado: {campo.tipo}")

            resultado[campo.nome] = valor

        return resultado
