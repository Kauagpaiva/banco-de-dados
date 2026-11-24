"""Fakes da Camada 4 (M0): FileManager em memória + BufferManager LRU/MRU/FIFO simples.

Seguem o mesmo contrato (`src.storage.contracts`) e **contam I/O do mesmo jeito**
(modelo de seek D05: braço global). Simplificações (não usar para medir experimentos):
- o cabeçalho não ocupa bloco nem conta I/O;
- CLOCK é tratado como LRU (aproximação);
- sem extents (alocação sequencial + reuso da lista livre).
"""
from __future__ import annotations

import json
from collections import OrderedDict, defaultdict
from typing import Any

from src.common.config import POLITICAS_VALIDAS
from src.common.erros import BufferFullError, StorageError
from src.common.tipos import CHAVES_BUFFER, CHAVES_IO
from src.storage.contracts import BufferManagerAPI, FileManagerAPI, Frame


def _zeros(chaves) -> dict:
    return {k: 0 for k in chaves if k != "hit_rate"}


class FakeFileManager(FileManagerAPI):
    """Blocos em dict; um 'arquivo' = {tipo_org, meta, blocos, livres, prox}."""

    def __init__(self, cfg, base_dir=None):
        self.cfg = cfg
        self.block_size = cfg.block_size
        self._arqs: dict[str, dict] = {}
        self._fid_nome: dict[int, str] = {}
        self._prox_fid = 1
        self._braco: tuple[int, int] | None = None
        self._glob = _zeros(CHAVES_IO)
        self._por = defaultdict(lambda: _zeros(CHAVES_IO))

    # ---- arquivos
    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int:
        if nome in self._arqs:
            raise StorageError(f"arquivo já existe: {nome}")
        self._arqs[nome] = {"tipo_org": tipo_org, "meta": dict(meta or {}), "blocos": {},
                            "livres": [], "prox": 1, "fid": None}
        return self.open(nome)

    def open(self, nome: str) -> int:
        if nome not in self._arqs:
            raise StorageError(f"arquivo inexistente: {nome}")
        a = self._arqs[nome]
        if a["fid"] is None:
            a["fid"] = self._prox_fid
            self._fid_nome[self._prox_fid] = nome
            self._prox_fid += 1
        return a["fid"]

    def exists(self, nome: str) -> bool:
        return nome in self._arqs

    def fid_de(self, nome: str) -> int | None:
        """Fid se o arquivo estiver aberto (uso interno do FakeBufferManager)."""
        a = self._arqs.get(nome)
        return a["fid"] if a else None

    def close(self, fid: int) -> None:
        nome = self._fid_nome.pop(fid, None)
        if nome is not None:
            self._arqs[nome]["fid"] = None

    def delete(self, nome: str) -> None:
        a = self._arqs.pop(nome, None)
        if a is None:
            raise StorageError(f"arquivo inexistente: {nome}")
        if a["fid"] is not None:
            self._fid_nome.pop(a["fid"], None)

    def _arq(self, fid: int) -> dict:
        try:
            return self._arqs[self._fid_nome[fid]]
        except KeyError:
            raise StorageError(f"fid inválido/fechado: {fid}") from None

    # ---- blocos
    def _registrar(self, fid: int, bno: int, escrita: bool) -> None:
        seq = self._braco == (fid, bno - 1)
        self._braco = (fid, bno)
        tipo = "writes" if escrita else "reads"
        det = ("seq_" if seq else "rand_") + tipo
        for d in (self._glob, self._por[fid]):
            d[tipo] += 1
            d[det] += 1

    def _checar(self, a: dict, bno: int) -> None:
        if bno < 1 or bno >= a["prox"] or bno in a["livres"]:
            raise StorageError(f"bloco não alocado: {bno}")

    def read_block(self, fid: int, bno: int) -> bytearray:
        a = self._arq(fid)
        self._checar(a, bno)
        self._registrar(fid, bno, False)
        return bytearray(a["blocos"].get(bno, bytes(self.block_size)))

    def write_block(self, fid: int, bno: int, data: bytes) -> None:
        a = self._arq(fid)
        self._checar(a, bno)
        if len(data) > self.block_size:
            raise StorageError(f"dado ({len(data)} B) maior que o bloco ({self.block_size} B)")
        self._registrar(fid, bno, True)
        a["blocos"][bno] = bytes(data).ljust(self.block_size, b"\0")

    def allocate_block(self, fid: int) -> int:
        a = self._arq(fid)
        if a["livres"]:
            return a["livres"].pop()
        bno = a["prox"]
        a["prox"] += 1
        return bno

    def free_block(self, fid: int, bno: int) -> None:
        a = self._arq(fid)
        self._checar(a, bno)
        a["blocos"].pop(bno, None)
        a["livres"].append(bno)

    def num_blocks(self, fid: int) -> int:
        a = self._arq(fid)
        return a["prox"] - 1 - len(a["livres"])

    def header(self, fid: int) -> dict:
        a = self._arq(fid)
        return {"tipo_org": a["tipo_org"], "num_alocados": a["prox"] - 1,
                "livre": a["livres"][-1] if a["livres"] else 0,
                "extent": self.cfg.extent_blocks, "meta": json.loads(json.dumps(a["meta"]))}

    def set_header(self, fid: int, **campos: Any) -> None:
        a = self._arq(fid)
        novo = {**a["meta"], **campos}
        if len(json.dumps(novo)) > self.block_size - 64:
            raise StorageError("meta do cabeçalho não cabe no bloco 0")
        a["meta"] = json.loads(json.dumps(novo))

    # ---- estatísticas
    def io_stats(self, fid: int | None = None) -> dict[str, int]:
        return dict(self._glob if fid is None else self._por[fid])

    def reset_io_stats(self) -> None:
        self._glob = _zeros(CHAVES_IO)
        self._por.clear()


class FakeBufferManager(BufferManagerAPI):
    """Buffer com áreas fixas; ordem de cada área num OrderedDict (frente = mais antigo)."""

    def __init__(self, cfg, fm: FileManagerAPI):
        self.cfg = cfg
        self.fm = fm
        self.block_size = cfg.block_size
        self._cap = dict(cfg.buffer_areas)
        self._areas: dict[str, OrderedDict] = {a: OrderedDict() for a in self._cap}
        self._onde: dict[tuple[int, int], str] = {}
        self._pol = {a: cfg.policy_for(a) for a in self._cap}
        self._st = {a: _zeros(CHAVES_BUFFER) for a in self._cap}

    # ---- internos
    def _area_ok(self, area: str) -> None:
        if area not in self._cap:
            raise StorageError(f"área inexistente: {area}")

    def _frame(self, fid: int, bno: int) -> Frame | None:
        area = self._onde.get((fid, bno))
        return self._areas[area][(fid, bno)] if area else None

    def _tocar(self, fr: Frame) -> None:
        fr.extra.pop("toss", None)
        if self._pol[fr.area] != "FIFO":
            self._areas[fr.area].move_to_end((fr.fid, fr.bno))

    def _vitima(self, area: str) -> Frame | None:
        livres = [f for f in self._areas[area].values() if f.pin_count == 0]
        if not livres:
            return None
        tossed = [f for f in livres if f.extra.get("toss")]
        if tossed:
            return tossed[0]
        return livres[-1] if self._pol[area] == "MRU" else livres[0]

    def _remover(self, fr: Frame) -> None:
        del self._areas[fr.area][(fr.fid, fr.bno)]
        del self._onde[(fr.fid, fr.bno)]

    def _abrir_espaco(self, area: str) -> None:
        if len(self._areas[area]) < self._cap[area]:
            return
        v = self._vitima(area)
        if v is None:
            raise BufferFullError(f"área {area!r}: todas as {self._cap[area]} páginas pinadas")
        if v.dirty:
            self.fm.write_block(v.fid, v.bno, bytes(v.data))
            self._st[area]["dirty_evictions"] += 1
        self._remover(v)

    def _inserir(self, fr: Frame) -> None:
        self._areas[fr.area][(fr.fid, fr.bno)] = fr
        self._onde[(fr.fid, fr.bno)] = fr.area

    # ---- pin/unpin
    def pin(self, fid: int, bno: int, area: str = "dados") -> Frame:
        self._area_ok(area)
        fr = self._frame(fid, bno)
        if fr is not None:
            st = self._st[fr.area]
            st["requests"] += 1
            st["hits"] += 1
            fr.pin_count += 1
            self._tocar(fr)
            return fr
        self._abrir_espaco(area)
        data = self.fm.read_block(fid, bno)
        st = self._st[area]
        st["requests"] += 1
        st["misses"] += 1
        fr = Frame(fid, bno, data, area, pin_count=1)
        self._inserir(fr)
        return fr

    def unpin(self, frame: Frame, dirty: bool = False, toss: bool = False) -> None:
        if frame.pin_count <= 0:
            raise StorageError(f"unpin sem pin: {(frame.fid, frame.bno)}")
        frame.pin_count -= 1
        if dirty:
            frame.dirty = True
        if toss and frame.pin_count == 0:
            frame.extra["toss"] = True

    def new_page(self, fid: int, area: str = "dados") -> Frame:
        self._area_ok(area)
        self._abrir_espaco(area)
        bno = self.fm.allocate_block(fid)
        fr = Frame(fid, bno, bytearray(self.block_size), area, pin_count=1, dirty=True)
        self._inserir(fr)
        return fr

    def free_page(self, fid: int, bno: int) -> None:
        fr = self._frame(fid, bno)
        if fr is not None:
            if fr.pin_count:
                raise StorageError(f"free_page de página pinada: {(fid, bno)}")
            self._remover(fr)
        self.fm.free_block(fid, bno)

    # ---- persistência
    def flush(self, fid: int, bno: int) -> None:
        fr = self._frame(fid, bno)
        if fr is not None and fr.dirty:
            self.fm.write_block(fid, bno, bytes(fr.data))
            fr.dirty = False
            self._st[fr.area]["forced_writes"] += 1

    def flush_all(self) -> None:
        for area in self._areas.values():
            for fr in area.values():
                if fr.dirty:
                    self.fm.write_block(fr.fid, fr.bno, bytes(fr.data))
                    fr.dirty = False

    def drop_all(self) -> None:
        self._checar_sem_pins(StorageError)
        self.flush_all()
        for area in self._areas.values():
            area.clear()
        self._onde.clear()

    # ---- políticas
    def set_policy(self, area: str, nome: str) -> None:
        self._area_ok(area)
        nome = nome.upper()
        if nome not in POLITICAS_VALIDAS:
            raise StorageError(f"política inválida: {nome}")
        self._pol[area] = nome

    def area_capacity(self, area: str) -> int:
        self._area_ok(area)
        return self._cap[area]

    # ---- estatísticas
    def stats(self) -> dict:
        por_area = {}
        glob = _zeros(CHAVES_BUFFER)
        for a, st in self._st.items():
            d = dict(st)
            d["hit_rate"] = d["hits"] / d["requests"] if d["requests"] else 0.0
            por_area[a] = d
            for k in glob:
                glob[k] += st[k]
        glob["hit_rate"] = glob["hits"] / glob["requests"] if glob["requests"] else 0.0
        glob.update(self.fm.io_stats())
        glob["transferencias"] = glob["reads"] + glob["writes"]
        glob["seeks"] = glob["rand_reads"] + glob["rand_writes"]
        glob["por_area"] = por_area
        return glob

    def reset_stats(self) -> None:
        self._st = {a: _zeros(CHAVES_BUFFER) for a in self._cap}
        self.fm.reset_io_stats()

    def _checar_sem_pins(self, exc=AssertionError) -> None:
        pinadas = [(f.fid, f.bno, f.pin_count) for a in self._areas.values()
                   for f in a.values() if f.pin_count]
        if pinadas:
            raise exc(f"páginas pinadas (fid, bno, pins): {pinadas}")

    def assert_no_pins(self) -> None:
        self._checar_sem_pins(AssertionError)

    # ---- repasse
    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int:
        return self.fm.create(nome, tipo_org, meta)

    def open(self, nome: str) -> int:
        return self.fm.open(nome)

    def exists(self, nome: str) -> bool:
        return self.fm.exists(nome)

    def _frames_de(self, fid: int) -> list[Frame]:
        return [f for a in self._areas.values() for f in a.values() if f.fid == fid]

    def close(self, fid: int) -> None:
        for fr in self._frames_de(fid):
            if fr.pin_count:
                raise StorageError(f"close com página pinada: {(fr.fid, fr.bno)}")
            if fr.dirty:
                self.fm.write_block(fr.fid, fr.bno, bytes(fr.data))
            self._remover(fr)
        self.fm.close(fid)

    def delete(self, nome: str) -> None:
        fid = self.fm.fid_de(nome) if hasattr(self.fm, "fid_de") else None
        if fid is not None:
            for fr in self._frames_de(fid):
                if fr.pin_count:
                    raise StorageError(f"delete com página pinada: {(fr.fid, fr.bno)}")
                self._remover(fr)
        self.fm.delete(nome)

    def num_blocks(self, fid: int) -> int:
        return self.fm.num_blocks(fid)

    def header(self, fid: int) -> dict:
        return self.fm.header(fid)

    def set_header(self, fid: int, **campos: Any) -> None:
        self.fm.set_header(fid, **campos)
