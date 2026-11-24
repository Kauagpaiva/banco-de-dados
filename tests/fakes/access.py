"""Fakes da Camada 3 (M0): codec JSON, slotted page JSON, catálogo em memória, heap
(`FakeTable`), índice em dict (`FakeIndex`), arquivo temporário e contexto.

Todos passam pelo BufferManager recebido (real ou fake), portanto **contam I/O pelo mesmo
contrato**. São corretos e simples — não eficientes. Formatos de bytes NÃO são os reais.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import struct
from typing import Any, Iterator, Mapping, Optional

from src.access.contracts import (
    AccessMethod, Campo, CatalogAPI, Esquema, FileOrganization, InfoIndice, InfoTabela,
    RecordCodecAPI, SecondaryIndex, SlottedPageAPI, StorageContext, TempFile,
)
from src.common.erros import (
    ChaveDuplicadaError, CorruptedPageError, OperacaoNaoSuportada, RecordError,
)
from src.common.tipos import RID, Predicado
from src.storage.contracts import BufferManagerAPI, Frame

__all__ = ["validar_registro", "FakeCodec", "FakeSlottedPage", "FakeCatalog", "FakeTable",
           "FakeIndex", "FakeTempFile", "FakeStorageContext", "AccessMethod"]


# =========================================================================== validação
def _validar_valor(c: Campo, v: Any) -> None:
    b = c.base
    if b == "int":
        ok = isinstance(v, int) and not isinstance(v, bool)
    elif b == "float":
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
    elif b == "date":
        ok = isinstance(v, dt.date) and not isinstance(v, dt.datetime)
    elif b in ("char", "varchar"):
        ok = isinstance(v, str) and len(v.encode("utf-8")) <= c.n
        if ok and b == "char" and v != v.rstrip(" \0"):
            raise RecordError(f"{c.nome}: char(n) não pode terminar em espaço/\\0")
    else:  # list
        ok = (isinstance(v, list) and len(v) <= c.max_itens and
              all(isinstance(x, str) and len(x.encode("utf-8")) <= c.n for x in v))
    if not ok:
        raise RecordError(f"{c.nome}: valor inválido para {c.tipo}: {v!r}")


def validar_registro(esquema: Esquema, rec: Mapping[str, Any]) -> None:
    """Regras de valor do contrato (src.access.contracts) — RecordError se violadas."""
    extras = set(rec) - set(esquema.nomes())
    if extras:
        raise RecordError(f"{esquema.nome}: campos desconhecidos {sorted(extras)}")
    for c in esquema.campos:
        if c.nome not in rec:
            raise RecordError(f"{esquema.nome}: falta o campo {c.nome}")
        v = rec[c.nome]
        if v is None:
            if not c.nulo:
                raise RecordError(f"{esquema.nome}.{c.nome}: nulo em campo NOT NULL")
            continue
        _validar_valor(c, v)


# =========================================================================== codec
class FakeCodec(RecordCodecAPI):
    """JSON (UTF-8) da lista de valores na ordem do esquema; datas como {"d": iso}."""

    def __init__(self, esquema: Esquema):
        self.esquema = esquema
        tam = 2
        for c in esquema.campos:
            b = c.base
            if b in ("char", "varchar"):
                tam += 2 * c.n + 3
            elif b == "list":
                tam += c.max_itens * (2 * c.n + 3) + 3
            else:
                tam += 26
        self._max = tam

    @property
    def max_size(self) -> int:
        return self._max

    def encode(self, rec: Mapping[str, Any]) -> bytes:
        validar_registro(self.esquema, rec)
        vals = []
        for c in self.esquema.campos:
            v = rec[c.nome]
            if v is not None and c.base == "date":
                v = {"d": v.isoformat()}
            elif v is not None and c.base == "float":
                v = float(v)
            vals.append(v)
        data = json.dumps(vals, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > self._max:
            raise RecordError(f"registro codificado ({len(data)} B) > max_size ({self._max} B)")
        return data

    def decode(self, data: bytes) -> dict:
        try:
            vals = json.loads(bytes(data).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise RecordError(f"registro ilegível: {e}") from None
        if not isinstance(vals, list) or len(vals) != len(self.esquema.campos):
            raise RecordError("registro com nº de campos errado")
        rec = {}
        for c, v in zip(self.esquema.campos, vals):
            if v is not None and c.base == "date":
                v = dt.date.fromisoformat(v["d"])
            rec[c.nome] = v
        return rec


# =========================================================================== página
_CAB = struct.Struct("<II")  # (reserva, tamanho do JSON)


class FakeSlottedPage(SlottedPageAPI):
    """Página = cabeçalho (reserva, len) + JSON [b64|null, ...] + ... + área reservada no fim.
    Slots nunca são renumerados nem reusados. `free_space` é exato para este formato."""

    @staticmethod
    def _ler(buf: bytearray) -> tuple[int, list]:
        reserva, n = _CAB.unpack_from(buf, 0)
        if reserva > len(buf) or _CAB.size + n > len(buf) - reserva:
            raise CorruptedPageError(f"cabeçalho fora do bloco (reserva={reserva}, len={n})")
        try:
            slots = json.loads(bytes(buf[_CAB.size:_CAB.size + n]) or b"[]")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CorruptedPageError("diretório de slots ilegível") from None
        return reserva, slots

    @staticmethod
    def _gravar(buf: bytearray, reserva: int, slots: list) -> bool:
        data = json.dumps(slots, separators=(",", ":")).encode("ascii")
        if _CAB.size + len(data) > len(buf) - reserva:
            return False
        fim_antigo = _CAB.size + _CAB.unpack_from(buf, 0)[1]
        buf[_CAB.size:_CAB.size + len(data)] = data
        if fim_antigo > _CAB.size + len(data):
            buf[_CAB.size + len(data):fim_antigo] = bytes(fim_antigo - _CAB.size - len(data))
        _CAB.pack_into(buf, 0, reserva, len(data))
        return True

    @staticmethod
    def format(buf: bytearray, reserva: int = 0) -> None:
        if reserva < 0 or _CAB.size + 2 > len(buf) - reserva:
            raise ValueError(f"reserva inválida: {reserva}")
        buf[: len(buf) - reserva] = bytes(len(buf) - reserva)
        _CAB.pack_into(buf, 0, reserva, 0)
        FakeSlottedPage._gravar(buf, reserva, [])

    @staticmethod
    def insert(buf: bytearray, rec: bytes) -> Optional[int]:
        reserva, slots = FakeSlottedPage._ler(buf)
        slots.append(base64.b64encode(bytes(rec)).decode("ascii"))
        if not FakeSlottedPage._gravar(buf, reserva, slots):
            return None
        return len(slots) - 1

    @staticmethod
    def get(buf: bytearray, slot: int) -> Optional[bytes]:
        _, slots = FakeSlottedPage._ler(buf)
        if not 0 <= slot < len(slots) or slots[slot] is None:
            return None
        return base64.b64decode(slots[slot])

    @staticmethod
    def delete(buf: bytearray, slot: int) -> None:
        reserva, slots = FakeSlottedPage._ler(buf)
        if not 0 <= slot < len(slots) or slots[slot] is None:
            raise KeyError(f"slot vazio: {slot}")
        slots[slot] = None
        FakeSlottedPage._gravar(buf, reserva, slots)

    @staticmethod
    def update(buf: bytearray, slot: int, rec: bytes) -> bool:
        reserva, slots = FakeSlottedPage._ler(buf)
        if not 0 <= slot < len(slots) or slots[slot] is None:
            raise KeyError(f"slot vazio: {slot}")
        slots[slot] = base64.b64encode(bytes(rec)).decode("ascii")
        return FakeSlottedPage._gravar(buf, reserva, slots)

    @staticmethod
    def compact(buf: bytearray) -> None:
        FakeSlottedPage._ler(buf)  # nada a compactar neste formato; só valida

    @staticmethod
    def free_space(buf: bytearray) -> int:
        reserva, slots = FakeSlottedPage._ler(buf)
        usado = len(json.dumps(slots, separators=(",", ":")))
        livre = len(buf) - reserva - _CAB.size - usado - (3 if slots else 2)  # ,"" ou ""
        return max(0, livre // 4 * 3)

    @staticmethod
    def slots(buf: bytearray) -> Iterator[int]:
        _, slots = FakeSlottedPage._ler(buf)
        return iter([i for i, s in enumerate(slots) if s is not None])

    @staticmethod
    def count(buf: bytearray) -> int:
        _, slots = FakeSlottedPage._ler(buf)
        return sum(s is not None for s in slots)

    @staticmethod
    def reserva(buf: bytearray) -> tuple[int, int]:
        reserva, _ = FakeSlottedPage._ler(buf)
        return len(buf) - reserva, reserva

    @staticmethod
    def capacidade_max(block_size: int, reserva: int = 0) -> int:
        return max(0, (block_size - reserva - _CAB.size - len('[""]')) // 4 * 3)


# =========================================================================== catálogo
class FakeCatalog(CatalogAPI):
    """Catálogo em memória (o real persiste na área 'catalogo')."""

    def __init__(self, bm: BufferManagerAPI | None = None, nome: str = "catalogo"):
        self._tab: dict[str, InfoTabela] = {}
        self._val: dict[str, Any] = {}

    def registrar_tabela(self, esquema, org, params=None, campo_org=None) -> InfoTabela:
        info = InfoTabela(esquema.nome, esquema, org, campo_org, dict(params or {}))
        self._tab[esquema.nome] = info
        return info

    def registrar_indice(self, tabela, nome, campo, tipo, unique, clustering=False,
                         primario=False, params=None) -> InfoIndice:
        info = self.tabela(tabela)
        idx = InfoIndice(nome, tabela, campo, tipo, unique, clustering, primario,
                         params=dict(params or {}))
        info.indices = [i for i in info.indices if i.campo != campo] + [idx]
        return idx

    def tabela(self, nome: str) -> InfoTabela:
        return self._tab[nome]

    def tabelas(self) -> list[str]:
        return sorted(self._tab)

    def remover_tabela(self, nome: str) -> None:
        del self._tab[nome]

    def atualizar_estatisticas(self, nome, nr, br, V, fr, tam_registro=None) -> None:
        t = self.tabela(nome)
        t.nr, t.br, t.V, t.fr = nr, br, dict(V), fr
        if tam_registro is not None:
            t.tam_registro = tam_registro

    def atualizar_indice(self, tabela, campo, altura, num_blocks, fanout=0) -> None:
        idx = self.tabela(tabela).indice(campo)
        if idx is None:
            raise KeyError(f"{tabela}: sem índice em {campo}")
        idx.altura, idx.num_blocks, idx.fanout = altura, num_blocks, fanout

    def definir(self, chave: str, valor: Any) -> None:
        self._val[chave] = json.loads(json.dumps(valor))

    def obter(self, chave: str, padrao: Any = None) -> Any:
        return self._val.get(chave, padrao)


# =========================================================================== heap fake
class _ArquivoDeRegistros:
    """Base comum de FakeTable/FakeTempFile: blocos de slotted pages via BufferManager."""
    area = "dados"

    def _iniciar(self, bm, nome, esquema, page_impl, codec):
        self.bm = bm
        self.nome = nome
        self.esquema = esquema
        self.page = page_impl or FakeSlottedPage
        self.codec = codec or FakeCodec(esquema)
        self.fid: Optional[int] = None
        self._blocos: list[int] = []
        self._n = 0

    def _append(self, rec: Mapping[str, Any]) -> RID:
        data = self.codec.encode(rec)
        if self._blocos:
            bno = self._blocos[-1]
            with self.bm.page(self.fid, bno, self.area) as fr:
                slot = self.page.insert(fr.data, data)
                if slot is not None:
                    fr.mark_dirty()
                    self._n += 1
                    return RID(bno, slot)
        with self.bm.fresh_page(self.fid, self.area) as fr:
            self.page.format(fr.data)
            slot = self.page.insert(fr.data, data)
            bno = fr.bno
        if slot is None:
            self.bm.free_page(self.fid, bno)
            raise RecordError(f"registro de {len(data)} B não cabe numa página vazia")
        self._blocos.append(bno)
        self._n += 1
        return RID(bno, slot)

    def _registros_do_bloco(self, bno: int, toss: bool = False) -> list[tuple[RID, dict]]:
        with self.bm.page(self.fid, bno, self.area, toss=toss) as fr:
            brutos = [(s, self.page.get(fr.data, s)) for s in self.page.slots(fr.data)]
        return [(RID(bno, s), self.codec.decode(b)) for s, b in brutos]

    def _scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        for bno in list(self._blocos):
            # a página é solta antes do yield: nenhum pin fica pendente no consumidor
            yield from self._registros_do_bloco(bno, toss)

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        for bno in list(self._blocos):
            yield [r for _, r in self._registros_do_bloco(bno, toss)]

    def num_blocks(self) -> int:
        return len(self._blocos)

    def num_registros(self) -> int:
        return self._n


class FakeTable(_ArquivoDeRegistros, FileOrganization):
    """Heap simples (FileOrganization) sobre o BufferManager: insere no último bloco."""
    tipo_org = "heap"
    campo = None
    unique = False

    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, *,
                 page_impl: type | None = None, codec: RecordCodecAPI | None = None):
        self._iniciar(bm, nome, esquema, page_impl, codec)
        self._cursor: Optional[Iterator] = None

    def open(self) -> None:
        if self.bm.exists(self.nome):
            self.fid = self.bm.open(self.nome)
            meta = self.bm.header(self.fid)["meta"]
            self._blocos, self._n = list(meta.get("blocos", [])), meta.get("n", 0)
        else:
            self.fid = self.bm.create(self.nome, "heap")

    def close(self) -> None:
        self.bm.set_header(self.fid, blocos=self._blocos, n=self._n)
        self.bm.close(self.fid)

    def reset(self) -> None:
        self._cursor = None

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

    def read(self, rid: RID) -> dict:
        with self.bm.page(self.fid, rid.bloco, self.area) as fr:
            b = self.page.get(fr.data, rid.slot)
        if b is None:
            raise KeyError(f"RID inexistente: {rid}")
        return self.codec.decode(b)

    def insert(self, rec: Mapping[str, Any]) -> RID:
        return self._append(rec)

    def delete(self, rid: RID) -> None:
        with self.bm.page(self.fid, rid.bloco, self.area, dirty=True) as fr:
            if self.page.get(fr.data, rid.slot) is None:
                raise KeyError(f"RID inexistente: {rid}")
            self.page.delete(fr.data, rid.slot)
        self._n -= 1

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        data = self.codec.encode(rec)
        with self.bm.page(self.fid, rid.bloco, self.area, dirty=True) as fr:
            if self.page.get(fr.data, rid.slot) is None:
                raise KeyError(f"RID inexistente: {rid}")
            if self.page.update(fr.data, rid.slot, data):
                return rid
        self.delete(rid)
        return self.insert(rec)

    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        return self._scan(toss)

    def find_all(self, campo: str, op: str, valor: Any) -> Iterator[tuple[RID, dict]]:
        pred = Predicado(campo, op, valor).validar()
        self.esquema.campo(campo)
        return ((rid, r) for rid, r in self._scan() if pred.avaliar(r))

    def find_ordered(self, campo, lo=None, hi=None, incl_lo=True, incl_hi=True):
        raise OperacaoNaoSuportada("heap não fornece ordem")

    def reorganize(self) -> None:
        for bno in self._blocos:
            with self.bm.page(self.fid, bno, self.area, dirty=True) as fr:
                self.page.compact(fr.data)

    def ocupacao(self) -> dict[str, int]:
        n = len(self._blocos)
        return {"dados": n, "overflow": 0, "indice": 0, "total": n, "registros": self._n}


# =========================================================================== índice fake
class FakeIndex(SecondaryIndex):
    """Índice secundário em dict. Cada busca/alteração toca 1 página (área 'indice') para que
    o custo apareça nas estatísticas do buffer (1 acesso por operação)."""

    def __init__(self, bm: BufferManagerAPI, nome: str, campo: Campo | str, *,
                 unique: bool = False, clustering: bool = False, refs_por_chave: bool = False,
                 page_impl: type | None = None):
        self.bm, self.nome = bm, nome
        self.campo = campo.nome if isinstance(campo, Campo) else campo
        self.unique, self.clustering, self.refs_por_chave = unique, clustering, refs_por_chave
        self._d: dict[Any, list] = {}
        self.fid: Optional[int] = None
        self._bloco = 0

    def open(self) -> None:
        if self.bm.exists(self.nome):
            self.fid = self.bm.open(self.nome)
            self._bloco = 1
        else:
            self.fid = self.bm.create(self.nome, "indice")
            with self.bm.fresh_page(self.fid, "indice") as fr:
                self._bloco = fr.bno

    def close(self) -> None:
        self.bm.close(self.fid)

    def _tocar(self, dirty: bool = False) -> None:
        with self.bm.page(self.fid, self._bloco, "indice", dirty=dirty):
            pass

    def insert(self, chave: Any, ref: Any) -> None:
        self._tocar(dirty=True)
        if self.unique and self._d.get(chave):
            raise ChaveDuplicadaError(f"{self.nome}: chave repetida {chave!r}")
        self._d.setdefault(chave, []).append(ref)

    def delete(self, chave: Any, ref: Any) -> None:
        self._tocar(dirty=True)
        refs = self._d.get(chave, [])
        if ref not in refs:
            raise KeyError(f"{self.nome}: par inexistente ({chave!r}, {ref!r})")
        refs.remove(ref)
        if not refs:
            del self._d[chave]

    def search_eq(self, chave: Any) -> Iterator[Any]:
        self._tocar()
        return iter(list(self._d.get(chave, [])))

    def search_range(self, lo=None, hi=None, incl_lo=True, incl_hi=True) -> Iterator[Any]:
        self._tocar()

        def dentro(k):
            if lo is not None and (k < lo or (k == lo and not incl_lo)):
                return False
            if hi is not None and (k > hi or (k == hi and not incl_hi)):
                return False
            return True
        return iter([r for k in sorted(self._d) if dentro(k) for r in self._d[k]])

    def altura(self) -> int:
        return 1

    def num_blocks(self) -> int:
        return 1


# =========================================================================== temporário fake
class FakeTempFile(_ArquivoDeRegistros, TempFile):
    area = "trabalho"

    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, *,
                 page_impl: type | None = None, codec: RecordCodecAPI | None = None):
        self._iniciar(bm, nome, esquema, page_impl, codec)
        self.fid = bm.create(nome, "temp")
        self._apagado = False

    def append(self, rec: Mapping[str, Any]) -> None:
        self._append(rec)

    def blocks(self) -> Iterator[int]:
        return iter(list(self._blocos))

    def records_in_block(self, bno: int) -> list[dict]:
        return [r for _, r in self._registros_do_bloco(bno)]

    def scan(self, toss: bool = False) -> Iterator[dict]:
        return (r for _, r in self._scan(toss))

    def close(self) -> None:
        pass  # o fake não mantém página de append pinada

    def delete(self) -> None:
        if not self._apagado:
            self.bm.delete(self.nome)
            self._apagado = True


# =========================================================================== contexto fake
class FakeStorageContext(StorageContext):
    """Contexto sobre qualquer BufferManager (real ou fake)."""
    _RASCUNHO = "__rascunho__"

    def __init__(self, cfg, bm: BufferManagerAPI | None = None, catalog: CatalogAPI | None = None,
                 *, page_impl: type | None = None, codec_factory=None):
        if bm is None:
            from tests.fakes.storage import FakeBufferManager, FakeFileManager
            bm = FakeBufferManager(cfg, FakeFileManager(cfg))
        self.cfg = cfg
        self._bm = bm
        self._catalog = catalog or FakeCatalog(bm)
        self._page_impl = page_impl
        self._codec_factory = codec_factory or FakeCodec
        self._temps: list[TempFile] = []
        self._seq = 0
        self._fid_rascunho: Optional[int] = None

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
            self._fid_rascunho = (self._bm.open(nome) if self._bm.exists(nome)
                                  else self._bm.create(nome, "temp"))
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
        t = FakeTempFile(self._bm, nome, esquema, page_impl=self._page_impl,
                         codec=self._codec_factory(esquema))
        self._temps.append(t)
        return t

    def close(self) -> None:
        for t in self._temps:
            t.delete()
        self._temps.clear()
