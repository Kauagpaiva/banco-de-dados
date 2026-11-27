
"""Slotted page (Camada 3).

Cabeçalho fixo, diretório de slots e registros armazenados do fim para o início.
Os slots são estáveis: exclusões e compactações não renumeram registros.
"""
from __future__ import annotations

import struct
from typing import Iterator, Optional

from src.access.contracts import SlottedPageAPI
from src.common.erros import CorruptedPageError


# Cabeçalho: quantidade de slots, início dos dados, tamanho reservado e assinatura.
_HEADER = struct.Struct("<4H")
# Cada slot guarda: offset do registro e tamanho em bytes.
_SLOT = struct.Struct("<2H")

_HEADER_SIZE = _HEADER.size
_SLOT_SIZE = _SLOT.size
_MAGIC = 0x5A50


def _cabecalho(buf: bytearray) -> tuple[int, int, int, int]:
    """Lê e valida o cabeçalho da página."""
    if len(buf) < _HEADER_SIZE:
        raise CorruptedPageError("bloco menor que o cabeçalho da página")

    nslots, inicio_dados, reserva, magic = _HEADER.unpack_from(buf, 0)

    if magic != _MAGIC:
        raise CorruptedPageError("página não formatada ou assinatura inválida")

    inicio_diretorio = _HEADER_SIZE + nslots * _SLOT_SIZE
    fim_reserva = len(buf) - reserva

    if (
        reserva > len(buf) - _HEADER_SIZE
        or inicio_diretorio > len(buf)
        or inicio_diretorio > inicio_dados
        or inicio_dados > fim_reserva
    ):
        raise CorruptedPageError("cabeçalho da página contém limites inválidos")

    return nslots, inicio_dados, reserva, inicio_diretorio


def _ler_slots(buf: bytearray) -> tuple[list[Optional[bytes]], list[tuple[int, int]]]:
    """Lê os slots e valida todos os offsets e tamanhos."""
    nslots, inicio_dados, reserva, inicio_diretorio = _cabecalho(buf)
    fim_reserva = len(buf) - reserva

    registros: list[Optional[bytes]] = []
    intervalos: list[tuple[int, int]] = []

    for i in range(nslots):
        pos = _HEADER_SIZE + i * _SLOT_SIZE
        off, tamanho = _SLOT.unpack_from(buf, pos)

        # Offset zero e tamanho zero representam um slot removido.
        if off == 0 and tamanho == 0:
            registros.append(None)
            continue

        fim = off + tamanho

        if (
            off < inicio_dados
            or off < inicio_diretorio
            or fim < off
            or fim > fim_reserva
        ):
            raise CorruptedPageError(
                f"slot {i} aponta para uma região inválida: "
                f"offset={off}, tamanho={tamanho}"
            )

        if tamanho:
            intervalos.append((off, fim))

        registros.append(bytes(buf[off:fim]))

    # Registros ocupados não podem compartilhar a mesma região da página.
    intervalos.sort()
    for anterior, atual in zip(intervalos, intervalos[1:]):
        if anterior[1] > atual[0]:
            raise CorruptedPageError("registros sobrepostos na página")

    return registros, [
        _SLOT.unpack_from(buf, _HEADER_SIZE + i * _SLOT_SIZE)
        for i in range(nslots)
    ]


def _reconstruir(buf: bytearray, registros: list[Optional[bytes]]) -> None:
    """Reorganiza os dados sem alterar os números dos slots ou a reserva."""
    _, _, reserva, _ = _cabecalho(buf)

    # Guarda a área reservada: ela pertence ao chamador.
    fim_reserva = len(buf) - reserva
    bytes_reservados = bytes(buf[fim_reserva:])

    inicio_diretorio = _HEADER_SIZE + len(registros) * _SLOT_SIZE
    cursor = fim_reserva

    # Limpa somente a área da página que não é reservada.
    buf[:fim_reserva] = b"\x00" * fim_reserva

    for i, registro in enumerate(registros):
        if registro is None:
            _SLOT.pack_into(buf, _HEADER_SIZE + i * _SLOT_SIZE, 0, 0)
            continue

        cursor -= len(registro)
        if cursor < inicio_diretorio:
            raise CorruptedPageError("não há espaço para reconstruir a página")

        buf[cursor:cursor + len(registro)] = registro
        _SLOT.pack_into(
            buf, _HEADER_SIZE + i * _SLOT_SIZE, cursor, len(registro)
        )

    _HEADER.pack_into(
        buf, 0, len(registros), cursor, reserva, _MAGIC
    )

    # Restaura os bytes reservados exatamente como estavam.
    buf[fim_reserva:] = bytes_reservados


class SlottedPage(SlottedPageAPI):
    @staticmethod
    def format(buf: bytearray, reserva: int = 0) -> None:
        if not isinstance(buf, bytearray):
            raise TypeError("buf deve ser bytearray")
        if len(buf) < _HEADER_SIZE:
            raise ValueError("bloco pequeno demais para uma página")
        if not isinstance(reserva, int) or isinstance(reserva, bool):
            raise ValueError("reserva deve ser um inteiro")
        if reserva < 0 or reserva > len(buf) - _HEADER_SIZE:
            raise ValueError("tamanho de reserva inválido")

        inicio_dados = len(buf) - reserva
        buf[:] = b"\x00" * len(buf)
        _HEADER.pack_into(buf, 0, 0, inicio_dados, reserva, _MAGIC)

    @staticmethod
    def insert(buf: bytearray, rec: bytes) -> Optional[int]:
        registro = bytes(rec)
        registros, _ = _ler_slots(buf)
        nslots, inicio_dados, reserva, inicio_diretorio = _cabecalho(buf)

        # Reutiliza um slot removido, se houver.
        try:
            slot = registros.index(None)
            novo_slot = False
        except ValueError:
            slot = nslots
            novo_slot = True

        custo_slot = _SLOT_SIZE if novo_slot else 0
        novo_inicio_dados = inicio_dados - len(registro)
        novo_fim_diretorio = inicio_diretorio + custo_slot

        if novo_inicio_dados < novo_fim_diretorio:
            return None

        buf[novo_inicio_dados:inicio_dados] = registro

        if novo_slot:
            _HEADER.pack_into(
                buf, 0, nslots + 1, novo_inicio_dados, reserva, _MAGIC
            )
        else:
            _HEADER.pack_into(
                buf, 0, nslots, novo_inicio_dados, reserva, _MAGIC
            )

        _SLOT.pack_into(
            buf, _HEADER_SIZE + slot * _SLOT_SIZE,
            novo_inicio_dados, len(registro)
        )
        return slot

    @staticmethod
    def get(buf: bytearray, slot: int) -> Optional[bytes]:
        registros, _ = _ler_slots(buf)
        if not isinstance(slot, int) or isinstance(slot, bool):
            return None
        if slot < 0 or slot >= len(registros):
            return None
        return registros[slot]

    @staticmethod
    def delete(buf: bytearray, slot: int) -> None:
        registros, _ = _ler_slots(buf)
        if not isinstance(slot, int) or isinstance(slot, bool):
            return
        if slot < 0 or slot >= len(registros):
            return
        if registros[slot] is None:
            return

        _SLOT.pack_into(
            buf, _HEADER_SIZE + slot * _SLOT_SIZE, 0, 0
        )

    @staticmethod
    def update(buf: bytearray, slot: int, rec: bytes) -> bool:
        registro = bytes(rec)
        registros, _ = _ler_slots(buf)

        if not isinstance(slot, int) or isinstance(slot, bool):
            return False
        if slot < 0 or slot >= len(registros):
            return False
        if registros[slot] is None:
            return False

        _, inicio_dados, _, inicio_diretorio = _cabecalho(buf)
        antigo = registros[slot]
        espaco_disponivel = inicio_dados - inicio_diretorio + len(antigo)

        if len(registro) > espaco_disponivel:
            return False

        # Reconstrói em uma cópia para garantir que falhas não alterem a página.
        novos_registros = list(registros)
        novos_registros[slot] = registro
        copia = bytearray(buf)
        _reconstruir(copia, novos_registros)
        buf[:] = copia
        return True

    @staticmethod
    def compact(buf: bytearray) -> None:
        registros, _ = _ler_slots(buf)
        _reconstruir(buf, registros)

    @staticmethod
    def free_space(buf: bytearray) -> int:
        registros, _ = _ler_slots(buf)
        _, inicio_dados, _, inicio_diretorio = _cabecalho(buf)

        # Se há slot removido, uma nova inserção pode reutilizá-lo.
        custo_slot = 0 if None in registros else _SLOT_SIZE
        return max(0, inicio_dados - inicio_diretorio - custo_slot)

    @staticmethod
    def slots(buf: bytearray) -> Iterator[int]:
        registros, _ = _ler_slots(buf)
        return iter(i for i, registro in enumerate(registros) if registro is not None)

    @staticmethod
    def count(buf: bytearray) -> int:
        registros, _ = _ler_slots(buf)
        return sum(registro is not None for registro in registros)

    @staticmethod
    def reserva(buf: bytearray) -> tuple[int, int]:
        _, _, tamanho, _ = _cabecalho(buf)
        return len(buf) - tamanho, tamanho

    @staticmethod
    def capacidade_max(block_size: int, reserva: int = 0) -> int:
        if (
            not isinstance(block_size, int)
            or isinstance(block_size, bool)
            or not isinstance(reserva, int)
            or isinstance(reserva, bool)
            or block_size < 0
            or reserva < 0
        ):
            raise ValueError("block_size e reserva devem ser inteiros não negativos")

        return max(0, block_size - _HEADER_SIZE - _SLOT_SIZE - reserva)
