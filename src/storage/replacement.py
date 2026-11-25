"""Políticas de substituição do buffer (Camada 4b) — M1/E02.

Silberschatz 13.5.2 (LRU, MRU, toss-immediate) + FIFO e Clock (second chance).
Interface: `src.storage.contracts.PolicyAPI`. Vítima só entre frames com pin_count == 0.

Protocolo usado pelo BufferManager (uma instância de política por área):
- falta (miss): `victim(frames)` → `on_evict(vitima)` → `on_load(novo)`;
- acerto (hit): `on_access(frame)`;
- `unpin`: `on_unpin(frame, toss)` (toss só quando o pin_count chega a 0).

Toss-immediate (13.5.2): a página "tossed" passa à frente da ordem da política e é a
próxima vítima (entre várias, a mais recentemente tossed). Um novo acesso cancela o toss.
"""
from __future__ import annotations

from src.common.erros import StorageError
from src.storage.contracts import Frame, PolicyAPI

# chaves usadas em frame.extra (uso livre da política, ver contracts.Frame)
_T_USO = "t_uso"        # instante do último acesso (LRU/MRU)
_T_CARGA = "t_carga"    # instante da carga (FIFO)
_TOSS = "toss"          # instante do toss-immediate


class _Base(PolicyAPI):
    """Relógio lógico + tratamento comum de toss-immediate."""

    def __init__(self) -> None:
        self._relogio = 0

    def _tick(self) -> int:
        self._relogio += 1
        return self._relogio

    # ---- eventos
    def on_load(self, frame: Frame) -> None:
        t = self._tick()
        frame.extra.pop(_TOSS, None)
        frame.extra[_T_CARGA] = t
        frame.extra[_T_USO] = t

    def on_access(self, frame: Frame) -> None:
        frame.extra.pop(_TOSS, None)
        frame.extra[_T_USO] = self._tick()

    def on_unpin(self, frame: Frame, toss: bool = False) -> None:
        if toss:
            frame.extra[_TOSS] = self._tick()

    def on_evict(self, frame: Frame) -> None:
        for k in (_TOSS, _T_CARGA, _T_USO):
            frame.extra.pop(k, None)

    # ---- escolha da vítima
    def victim(self, frames: list[Frame]) -> Frame | None:
        livres = [f for f in frames if f.pin_count == 0]
        if not livres:
            return None
        tossed = [f for f in livres if _TOSS in f.extra]
        if tossed:
            return max(tossed, key=lambda f: f.extra[_TOSS])
        return self._escolher(livres)

    def _escolher(self, livres: list[Frame]) -> Frame:
        raise NotImplementedError


class LRU(_Base):
    """Least Recently Used: expulsa a página não pinada de acesso mais antigo (13.5.2)."""
    nome = "LRU"

    def _escolher(self, livres: list[Frame]) -> Frame:
        return min(livres, key=lambda f: f.extra[_T_USO])


class MRU(_Base):
    """Most Recently Used: expulsa a de acesso mais recente — boa para varreduras cíclicas
    maiores que o buffer, como a relação interna do nested-loop (13.5.2)."""
    nome = "MRU"

    def _escolher(self, livres: list[Frame]) -> Frame:
        return max(livres, key=lambda f: f.extra[_T_USO])


class FIFO(_Base):
    """First In First Out: expulsa a carregada há mais tempo (acessos não reordenam)."""
    nome = "FIFO"

    def _escolher(self, livres: list[Frame]) -> Frame:
        return min(livres, key=lambda f: f.extra[_T_CARGA])


class Clock(_Base):
    """Clock / second chance: anel de quadros com ponteiro; bit de referência ligado na carga
    e a cada acesso. O ponteiro desliga bits até achar um quadro não pinado com bit 0.
    A página nova ocupa a posição da vítima (o ponteiro já está depois dela)."""
    nome = "CLOCK"

    def __init__(self) -> None:
        super().__init__()
        self._anel: list[Frame | None] = []
        self._vagas: list[int] = []       # posições liberadas por on_evict (pilha)
        self._mao = 0

    def _pos(self, frame: Frame) -> int:
        for i, f in enumerate(self._anel):
            if f is frame:
                return i
        raise StorageError(f"Clock: frame {(frame.fid, frame.bno)} fora do anel")

    def on_load(self, frame: Frame) -> None:
        super().on_load(frame)
        frame.ref_bit = True
        if self._vagas:
            self._anel[self._vagas.pop()] = frame
        else:
            self._anel.append(frame)

    def on_access(self, frame: Frame) -> None:
        super().on_access(frame)
        frame.ref_bit = True

    def on_unpin(self, frame: Frame, toss: bool = False) -> None:
        super().on_unpin(frame, toss)
        if toss:
            frame.ref_bit = False

    def on_evict(self, frame: Frame) -> None:
        super().on_evict(frame)
        i = self._pos(frame)
        self._anel[i] = None
        self._vagas.append(i)
        frame.ref_bit = False

    def _escolher(self, livres: list[Frame]) -> Frame:
        candidatos = {id(f) for f in livres}
        n = len(self._anel)
        # no máximo 2 voltas: a 1ª desliga os bits, a 2ª encontra bit 0
        for _ in range(2 * n + 1):
            f = self._anel[self._mao]
            self._mao = (self._mao + 1) % n
            if f is None or id(f) not in candidatos:
                continue
            if f.ref_bit:
                f.ref_bit = False
                continue
            return f
        raise StorageError("Clock: nenhum candidato no anel")  # inalcançável se livres ⊆ anel


_POLITICAS = {"LRU": LRU, "MRU": MRU, "FIFO": FIFO, "CLOCK": Clock}


def criar_politica(nome: str) -> PolicyAPI:
    """Fábrica: 'LRU' | 'MRU' | 'FIFO' | 'CLOCK' → instância."""
    try:
        return _POLITICAS[str(nome).upper()]()
    except KeyError:
        raise StorageError(f"política inválida: {nome!r} (válidas: {sorted(_POLITICAS)})") from None
