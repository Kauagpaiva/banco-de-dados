"""Gerente de Buffer Pool (Camada 4b) — M1/E02.

Silberschatz 13.5 (buffer: pin/unpin, dirty, forced output, toss-immediate, MRU) e 19.5
(REFERENCIA_LIVRO §2). Contrato: `BufferManagerAPI` (os context managers `page`/`fresh_page`
vêm prontos do contrato). **Único módulo que chama `FileManager.read_block/write_block`.**

Organização:
- áreas fixas (`cfg.buffer_areas`: catalogo, indice, dados, trabalho), cada uma com capacidade
  própria e uma instância de política (`cfg.policy_for(area)`); substituição só dentro da área;
- tabela única (fid, bno) → Frame: uma página reside em no máximo uma área (a da carga);
- estatísticas de buffer por área (CHAVES_BUFFER) + I/O do FileManager (CHAVES_IO).
"""
from __future__ import annotations

from typing import Any

from src.common.config import POLITICAS_VALIDAS
from src.common.erros import BufferFullError, StorageError
from src.common.tipos import CHAVES_BUFFER
from src.storage.contracts import BufferManagerAPI, Frame, PolicyAPI
from src.storage.file_manager import FileManager
from src.storage.replacement import criar_politica

_CONTADORES = tuple(k for k in CHAVES_BUFFER if k != "hit_rate")


def _zeros() -> dict[str, int]:
    return {k: 0 for k in _CONTADORES}


class BufferManager(BufferManagerAPI):
    def __init__(self, cfg, fm: FileManager):
        self.cfg = cfg
        self.fm = fm
        self.block_size = cfg.block_size
        self._cap: dict[str, int] = dict(cfg.buffer_areas)
        self._areas: dict[str, dict[tuple[int, int], Frame]] = {a: {} for a in self._cap}
        self._tabela: dict[tuple[int, int], Frame] = {}
        self._nome_pol: dict[str, str] = {a: cfg.policy_for(a).upper() for a in self._cap}
        self._pol: dict[str, PolicyAPI] = {a: criar_politica(n) for a, n in self._nome_pol.items()}
        self._st: dict[str, dict[str, int]] = {a: _zeros() for a in self._cap}
        self._toss_padrao = bool(cfg.toss_immediate)
        self._prefetch = max(0, int(cfg.prefetch))

    # ================================================================== internos
    def _area_ok(self, area: str) -> None:
        if area not in self._cap:
            raise StorageError(f"área inexistente: {area!r} (áreas: {list(self._cap)})")

    def _gravar(self, fr: Frame) -> None:
        """Única saída de dados do pool para o disco."""
        self.fm.write_block(fr.fid, fr.bno, bytes(fr.data))
        fr.dirty = False

    def _remover(self, fr: Frame) -> None:
        self._pol[fr.area].on_evict(fr)
        del self._areas[fr.area][(fr.fid, fr.bno)]
        del self._tabela[(fr.fid, fr.bno)]

    def _abrir_espaco(self, area: str) -> bool:
        """Garante 1 quadro livre na área, expulsando a vítima da política (gravando se dirty).
        Devolve False se a área está cheia e toda página está pinada."""
        quadros = self._areas[area]
        if len(quadros) < self._cap[area]:
            return True
        v = self._pol[area].victim(list(quadros.values()))
        if v is None:
            return False
        if v.pin_count:
            raise StorageError(f"política {self._nome_pol[area]} escolheu página pinada {(v.fid, v.bno)}")
        if v.dirty:
            self._gravar(v)
            self._st[area]["dirty_evictions"] += 1
        self._remover(v)
        return True

    def _exigir_espaco(self, area: str) -> None:
        if not self._abrir_espaco(area):
            raise BufferFullError(f"área {area!r}: todas as {self._cap[area]} páginas estão pinadas")

    def _instalar(self, fid: int, bno: int, data: bytearray, area: str, *,
                  pin: int, dirty: bool) -> Frame:
        fr = Frame(fid, bno, data, area, pin_count=pin, dirty=dirty)
        self._areas[area][(fid, bno)] = fr
        self._tabela[(fid, bno)] = fr
        self._pol[area].on_load(fr)
        return fr

    def _bloco_valido(self, fid: int, bno: int) -> bool:
        valido = getattr(self.fm, "bloco_valido", None)
        return True if valido is None else valido(fid, bno)

    def _prefetch_apos(self, fid: int, bno: int, area: str) -> None:
        """Lê antecipadamente até k blocos seguintes (não contam request; I/O conta)."""
        for b in range(bno + 1, bno + 1 + self._prefetch):
            if (fid, b) in self._tabela:
                continue
            if not self._bloco_valido(fid, b) or not self._abrir_espaco(area):
                return
            self._instalar(fid, b, self.fm.read_block(fid, b), area, pin=0, dirty=False)

    def _frames_de(self, fid: int) -> list[Frame]:
        return [f for f in self._tabela.values() if f.fid == fid]

    def _checar_sem_pins(self, frames, exc, oper: str) -> None:
        pinadas = [(f.fid, f.bno, f.pin_count) for f in frames if f.pin_count]
        if pinadas:
            raise exc(f"{oper}: páginas pinadas (fid, bno, pins): {pinadas}")

    # ================================================================== pin/unpin
    def pin(self, fid: int, bno: int, area: str = "dados") -> Frame:
        self._area_ok(area)
        fr = self._tabela.get((fid, bno))
        if fr is not None:                                  # acerto: conta na área do frame
            st = self._st[fr.area]
            st["requests"] += 1
            st["hits"] += 1
            fr.pin_count += 1
            self._pol[fr.area].on_access(fr)
            return fr
        if not self._bloco_valido(fid, bno):                # antes de expulsar alguém à toa
            raise StorageError(f"bloco inválido/livre: fid={fid} bno={bno}")
        self._exigir_espaco(area)
        data = self.fm.read_block(fid, bno)
        st = self._st[area]
        st["requests"] += 1
        st["misses"] += 1
        fr = self._instalar(fid, bno, data, area, pin=1, dirty=False)
        if self._prefetch:
            self._prefetch_apos(fid, bno, area)
        return fr

    def unpin(self, frame: Frame, dirty: bool = False, toss: bool = False) -> None:
        if frame.pin_count <= 0:
            raise StorageError(f"unpin sem pin: {(frame.fid, frame.bno)}")
        if self._tabela.get((frame.fid, frame.bno)) is not frame:
            raise StorageError(f"unpin de frame que não está no pool: {(frame.fid, frame.bno)}")
        frame.pin_count -= 1
        if dirty:
            frame.dirty = True
        if frame.pin_count == 0:
            self._pol[frame.area].on_unpin(frame, toss or self._toss_padrao)

    def new_page(self, fid: int, area: str = "dados") -> Frame:
        self._area_ok(area)
        self._exigir_espaco(area)          # antes de alocar: sem bloco órfão se o pool estiver cheio
        bno = self.fm.allocate_block(fid)
        return self._instalar(fid, bno, bytearray(self.block_size), area, pin=1, dirty=True)

    def free_page(self, fid: int, bno: int) -> None:
        fr = self._tabela.get((fid, bno))
        if fr is not None:
            if fr.pin_count:
                raise StorageError(f"free_page de página pinada: {(fid, bno)}")
            self._remover(fr)              # descarta sem gravar
        self.fm.free_block(fid, bno)

    # ================================================================== persistência
    def flush(self, fid: int, bno: int) -> None:
        fr = self._tabela.get((fid, bno))
        if fr is not None and fr.dirty:
            self._gravar(fr)
            self._st[fr.area]["forced_writes"] += 1

    def flush_all(self) -> None:
        """Grava as páginas dirty em ordem (fid, bno) — escrita em lote favorece sequência —
        e os cabeçalhos alterados (`fm.sync`)."""
        for chave in sorted(k for k, f in self._tabela.items() if f.dirty):
            self._gravar(self._tabela[chave])
        sync = getattr(self.fm, "sync", None)
        if sync is not None:
            sync()

    def drop_all(self) -> None:
        self._checar_sem_pins(self._tabela.values(), StorageError, "drop_all")
        self.flush_all()
        for quadros in self._areas.values():
            quadros.clear()
        self._tabela.clear()
        self._pol = {a: criar_politica(n) for a, n in self._nome_pol.items()}

    def close_all(self) -> None:
        """Extra (fora do contrato): drop_all + fecha todos os arquivos do FileManager."""
        self.drop_all()
        fechar = getattr(self.fm, "close_all", None)
        if fechar is not None:
            fechar()

    # ================================================================== políticas/áreas
    def set_policy(self, area: str, nome: str) -> None:
        """Troca a política da área; quadros residentes entram na nova na ordem de carga."""
        self._area_ok(area)
        nome = str(nome).upper()
        if nome not in POLITICAS_VALIDAS:
            raise StorageError(f"política inválida: {nome!r} (válidas: {POLITICAS_VALIDAS})")
        nova = criar_politica(nome)
        for fr in self._areas[area].values():
            fr.extra.clear()
            fr.ref_bit = False
            nova.on_load(fr)
        self._nome_pol[area] = nome
        self._pol[area] = nova

    def policy(self, area: str) -> str:
        """Extra: nome da política atual da área."""
        self._area_ok(area)
        return self._nome_pol[area]

    def area_capacity(self, area: str) -> int:
        self._area_ok(area)
        return self._cap[area]

    # ================================================================== estatísticas
    def stats(self) -> dict:
        por_area: dict[str, dict] = {}
        glob: dict[str, Any] = _zeros()
        for a, st in self._st.items():
            d: dict[str, Any] = dict(st)
            d["hit_rate"] = d["hits"] / d["requests"] if d["requests"] else 0.0
            por_area[a] = d
            for k in _CONTADORES:
                glob[k] += st[k]
        glob["hit_rate"] = glob["hits"] / glob["requests"] if glob["requests"] else 0.0
        glob.update(self.fm.io_stats())
        glob["transferencias"] = glob["reads"] + glob["writes"]
        glob["seeks"] = glob["rand_reads"] + glob["rand_writes"]
        glob["por_area"] = por_area
        return glob

    def reset_stats(self) -> None:
        self._st = {a: _zeros() for a in self._cap}
        self.fm.reset_io_stats()

    def assert_no_pins(self) -> None:
        self._checar_sem_pins(self._tabela.values(), AssertionError, "assert_no_pins")

    # ================================================================== repasse ao FileManager
    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int:
        return self.fm.create(nome, tipo_org, meta)

    def open(self, nome: str) -> int:
        return self.fm.open(nome)

    def exists(self, nome: str) -> bool:
        return self.fm.exists(nome)

    def close(self, fid: int) -> None:
        frames = self._frames_de(fid)
        self._checar_sem_pins(frames, StorageError, "close")
        for fr in sorted(frames, key=lambda f: f.bno):
            if fr.dirty:
                self._gravar(fr)
            self._remover(fr)
        self.fm.close(fid)

    def delete(self, nome: str) -> None:
        fid_de = getattr(self.fm, "fid_de", None)
        fid = fid_de(nome) if fid_de is not None else None
        if fid is not None:
            frames = self._frames_de(fid)
            self._checar_sem_pins(frames, StorageError, "delete")
            for fr in frames:              # descarta sem gravar
                self._remover(fr)
        self.fm.delete(nome)

    def num_blocks(self, fid: int) -> int:
        return self.fm.num_blocks(fid)

    def header(self, fid: int) -> dict:
        return self.fm.header(fid)

    def set_header(self, fid: int, **campos: Any) -> None:
        self.fm.set_header(fid, **campos)
