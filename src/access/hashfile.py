"""Hash estático externo como organização primária (Camada 3) — M4 (E07).

Silberschatz 14.5 (hashing estático, buckets, *overflow chaining*, skew). REFERENCIA_LIVRO §5.

Layout do arquivo:
- bloco 0: cabeçalho (FileManager) com `meta = {n_buckets, campo, unique, n, n_overflow}`;
- blocos 1..nB: buckets primários **contíguos**, alocados todos na criação;
  nB = ceil(nr / (fr · fill_factor)), fr = capacidade da página / tamanho máximo do registro;
- blocos > nB: buckets de overflow, encadeados a partir do bucket primário.

Cada bucket é uma slotted page cuja área reservada (fim do bloco) guarda o ponteiro de overflow
(`<Q`, 0 = fim da cadeia). Busca **e** remoção percorrem a cadeia inteira; bloco de overflow que
fica vazio é desencadeado e devolvido à lista livre. Função de hash: FNV-1a 64 (determinística;
`hash()` do Python não serve, pois é randomizado por execução). Contrato: `FileOrganization`.
"""
from __future__ import annotations

import datetime as dt
import heapq
import math
import struct
from typing import Any, Callable, Iterator, Mapping, Optional

from src.access.contracts import Esquema, FileOrganization, RecordCodecAPI, padroes
from src.common.erros import (ChaveDuplicadaError, ConfigError, CorruptedPageError,
                              OperacaoNaoSuportada, RecordError, StorageError)
from src.common.tipos import RID, Predicado
from src.storage.contracts import BufferManagerAPI

#: Ponteiro de overflow guardado na área reservada de cada bucket (nº do bloco; 0 = nenhum).
_PTR = struct.Struct("<Q")
RESERVA_OVERFLOW = _PTR.size

_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK64 = (1 << 64) - 1


def fnv1a64(dado: bytes) -> int:
    """FNV-1a de 64 bits (determinístico, ao contrário de `hash()` do Python)."""
    h = _FNV_OFFSET
    for b in bytes(dado):
        h ^= b
        h = (h * _FNV_PRIME) & _MASK64
    return h


def _soma_bytes(dado: bytes) -> int:
    """Função ingênua (soma dos bytes) — só para comparação de dispersão nos testes."""
    return sum(bytes(dado))


def _degenerada(dado: bytes) -> int:
    """Tudo no bucket 0 — força cadeias longas de overflow (teste de pior caso)."""
    return 0


#: Nome em `cfg.hash_funcao` → função bytes → int.
FUNCOES_HASH: dict[str, Callable[[bytes], int]] = {
    "fnv1a64": fnv1a64,
    "soma": _soma_bytes,
    "degenerada": _degenerada,
}


def chave_bytes(valor: Any) -> bytes:
    """Serialização determinística do valor da chave para a função de hash.
    Prefixo de tipo evita colisões triviais entre tipos diferentes."""
    if valor is None:
        return b"N"
    if isinstance(valor, bool):
        return b"b" + (b"\x01" if valor else b"\x00")
    if isinstance(valor, int):
        return b"i" + str(valor).encode("ascii")
    if isinstance(valor, float):
        return b"f" + struct.pack("<d", valor)
    if isinstance(valor, dt.date):
        return b"d" + struct.pack("<i", valor.toordinal())
    if isinstance(valor, str):
        return b"s" + valor.encode("utf-8")
    if isinstance(valor, (list, tuple)):
        return b"l" + b"\x1f".join(chave_bytes(v) for v in valor)
    raise TypeError(f"tipo de chave não suportado no hash: {type(valor).__name__}")


class HashFile(FileOrganization):
    """Arquivo hash estático (Silberschatz 14.5.1–14.5.2), organização primária por `campo`."""
    tipo_org = "hash"
    #: Área do buffer onde ficam as páginas (o HashIndex usa 'indice').
    area = "dados"

    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, campo: str, *,
                 unique: bool = True, n_buckets: int | None = None,
                 nr_estimado: int | None = None, page_impl: type | None = None,
                 codec: RecordCodecAPI | None = None):
        esquema.campo(campo)                       # KeyError se o campo não existe
        if n_buckets is None and nr_estimado is None:
            raise ValueError("HashFile: informe n_buckets ou nr_estimado")
        if n_buckets is not None and n_buckets < 1:
            raise ValueError(f"n_buckets inválido: {n_buckets}")
        self.bm = bm
        self.nome = nome
        self.esquema = esquema
        self.campo = campo
        self.unique = unique
        self.page, self.codec = padroes(esquema, page_impl, codec)
        self._nb_pedido = n_buckets
        self._nr_estimado = nr_estimado
        nome_f = getattr(bm.cfg, "hash_funcao", "fnv1a64")
        if nome_f not in FUNCOES_HASH:
            raise ConfigError(f"hash.funcao desconhecida: {nome_f!r} (válidas: {list(FUNCOES_HASH)})")
        self._funcao = FUNCOES_HASH[nome_f]
        self.fid: Optional[int] = None
        self.n_buckets = 0
        self._n = 0
        self._n_overflow = 0
        self._cursor: Optional[Iterator[RID]] = None

    # ------------------------------------------------------------------ dimensionamento
    def _fr_estimado(self) -> int:
        """Registros por bloco no pior caso: capacidade da página / maior registro."""
        cap = self.page.capacidade_max(self.bm.block_size, RESERVA_OVERFLOW)
        return max(1, cap // max(1, self.codec.max_size))

    def _calcular_nb(self) -> int:
        if self._nb_pedido is not None:
            return self._nb_pedido
        fill = float(getattr(self.bm.cfg, "hash_fill_factor", 0.8))
        return max(1, math.ceil(self._nr_estimado / (self._fr_estimado() * fill)))

    # ------------------------------------------------------------------ ciclo de vida
    def _exigir_aberto(self) -> None:
        if self.fid is None:
            raise StorageError(f"{self.nome}: arquivo hash não está aberto")

    def open(self) -> None:
        if self.fid is not None:
            return
        if self.bm.exists(self.nome):
            self.fid = self.bm.open(self.nome)
            meta = self.bm.header(self.fid)["meta"]
            self.n_buckets = int(meta["n_buckets"])
            self._n = int(meta.get("n", 0))
            self._n_overflow = int(meta.get("n_overflow", 0))
            self.unique = bool(meta.get("unique", self.unique))
            return
        nb = self._calcular_nb()
        self.fid = self.bm.create(self.nome, "hash")
        for i in range(nb):
            with self.bm.fresh_page(self.fid, self.area) as fr:
                if fr.bno != i + 1:
                    raise StorageError(f"{self.nome}: bucket {i} caiu no bloco {fr.bno} "
                                       "(buckets primários devem ser contíguos 1..nB)")
                self._formatar(fr.data)
        self.n_buckets = nb
        self._n = 0
        self._n_overflow = 0
        self._gravar_meta()

    def _gravar_meta(self) -> None:
        self.bm.set_header(self.fid, n_buckets=self.n_buckets, campo=self.campo,
                           unique=self.unique, n=self._n, n_overflow=self._n_overflow)

    def close(self) -> None:
        if self.fid is None:
            return
        self._gravar_meta()
        self.bm.close(self.fid)
        self.fid = None
        self._cursor = None

    def reset(self) -> None:
        self._cursor = None

    # ------------------------------------------------------------------ página/bucket
    def _formatar(self, buf: bytearray) -> None:
        self.page.format(buf, RESERVA_OVERFLOW)
        self._set_prox(buf, 0)

    def _get_prox(self, buf: bytearray) -> int:
        off, n = self.page.reserva(buf)
        if n < _PTR.size or off < 0 or off + _PTR.size > len(buf):
            raise CorruptedPageError(f"{self.nome}: área reservada inválida ({off}, {n})")
        prox = _PTR.unpack_from(buf, off)[0]
        if prox != 0 and prox <= self.n_buckets:
            raise CorruptedPageError(f"{self.nome}: ponteiro de overflow {prox} aponta para bucket primário")
        return prox

    def _set_prox(self, buf: bytearray, prox: int) -> None:
        off, n = self.page.reserva(buf)
        if n < _PTR.size or off < 0 or off + _PTR.size > len(buf):
            raise CorruptedPageError(f"{self.nome}: área reservada inválida ({off}, {n})")
        _PTR.pack_into(buf, off, prox)

    def bucket_de(self, valor: Any) -> int:
        """Índice (0..nB-1) do bucket da chave `valor`."""
        return self._funcao(chave_bytes(valor)) % self.n_buckets

    def _cadeia(self, bucket: int, toss: bool = False
                ) -> Iterator[tuple[int, int, list[tuple[int, bytes]], int]]:
        """Percorre a cadeia do bucket: (anterior, bno, [(slot, bytes)], próximo).
        A página é solta **antes** do yield (no máximo 1 pin por vez)."""
        self._exigir_aberto()
        anterior, bno, vistos = 0, bucket + 1, 0
        while bno:
            with self.bm.page(self.fid, bno, self.area, toss=toss) as fr:
                itens = [(s, self.page.get(fr.data, s)) for s in self.page.slots(fr.data)]
                prox = self._get_prox(fr.data)
            yield anterior, bno, itens, prox
            vistos += 1
            if vistos > self.n_buckets + self._n_overflow:
                raise CorruptedPageError(f"{self.nome}: ciclo na cadeia do bucket {bucket}")
            anterior, bno = bno, prox

    def _chave(self, dado: bytes) -> Any:
        return self.codec.decode(dado)[self.campo]

    # ------------------------------------------------------------------ registro a registro
    def _busca_chave(self, valor: Any) -> Iterator[tuple[RID, dict]]:
        """Registros com campo == valor: percorre a cadeia toda (14.5); UNIQUE para no 1º."""
        for _, bno, itens, _ in self._cadeia(self.bucket_de(valor)):
            for slot, dado in itens:
                rec = self.codec.decode(dado)
                if rec[self.campo] == valor:
                    yield RID(bno, slot), rec
                    if self.unique:
                        return

    def find(self, campo: str, valor: Any) -> Optional[RID]:
        self._cursor = (rid for rid, _ in self.find_all(campo, "=", valor))
        return self.find_next()

    def find_next(self) -> Optional[RID]:
        if self._cursor is None:
            return None
        rid = next(self._cursor, None)
        if rid is None:
            self._cursor = None
        return rid

    def read(self, rid: RID) -> dict:
        self._exigir_aberto()
        self._checar_rid(rid)
        with self.bm.page(self.fid, rid.bloco, self.area) as fr:
            dado = self.page.get(fr.data, rid.slot)
        if dado is None:
            raise KeyError(f"{self.nome}: RID inexistente {rid}")
        return self.codec.decode(dado)

    def _checar_rid(self, rid: RID) -> None:
        if rid.bloco < 1 or rid.slot < 0:
            raise KeyError(f"{self.nome}: RID inválido {rid}")

    def insert(self, rec: Mapping[str, Any]) -> RID:
        self._exigir_aberto()
        dado = self.codec.encode(rec)
        if len(dado) > self.page.capacidade_max(self.bm.block_size, RESERVA_OVERFLOW):
            raise RecordError(f"{self.nome}: registro de {len(dado)} B não cabe num bucket")
        valor = rec[self.campo]
        bucket = self.bucket_de(valor)
        alvo, ultimo = 0, bucket + 1
        bno, vistos = bucket + 1, 0
        while bno:
            with self.bm.page(self.fid, bno, self.area) as fr:
                if self.unique:
                    for s in self.page.slots(fr.data):
                        if self._chave(self.page.get(fr.data, s)) == valor:
                            raise ChaveDuplicadaError(f"{self.nome}: chave repetida {valor!r}")
                if not alvo and self.page.free_space(fr.data) >= len(dado):
                    alvo = bno
                    if not self.unique:            # NOT UNIQUE: insere no 1º bloco com espaço
                        slot = self.page.insert(fr.data, dado)
                        if slot is not None:
                            fr.mark_dirty()
                            self._n += 1
                            return RID(bno, slot)
                        alvo = 0
                prox = self._get_prox(fr.data)
            ultimo, bno = bno, prox
            vistos += 1
            if vistos > self.n_buckets + self._n_overflow:
                raise CorruptedPageError(f"{self.nome}: ciclo na cadeia do bucket {bucket}")
        if alvo:
            with self.bm.page(self.fid, alvo, self.area) as fr:
                slot = self.page.insert(fr.data, dado)
                if slot is not None:
                    fr.mark_dirty()
                    self._n += 1
                    return RID(alvo, slot)
        return self._novo_overflow(ultimo, dado)

    def _novo_overflow(self, ultimo: int, dado: bytes) -> RID:
        """Aloca bloco de overflow, insere `dado` e o encadeia após `ultimo`."""
        with self.bm.fresh_page(self.fid, self.area) as fr:
            self._formatar(fr.data)
            slot = self.page.insert(fr.data, dado)
            novo = fr.bno
        if slot is None:
            self.bm.free_page(self.fid, novo)
            raise RecordError(f"{self.nome}: registro de {len(dado)} B não cabe num bucket vazio")
        if novo <= self.n_buckets:
            raise StorageError(f"{self.nome}: overflow alocado no bloco {novo} (≤ nB)")
        with self.bm.page(self.fid, ultimo, self.area, dirty=True) as fr:
            self._set_prox(fr.data, novo)
        self._n_overflow += 1
        self._n += 1
        return RID(novo, slot)

    def _remover(self, anterior: int, bno: int, slot: int) -> None:
        """Remove o slot; bloco de overflow que fica vazio sai da cadeia e é liberado."""
        with self.bm.page(self.fid, bno, self.area, dirty=True) as fr:
            if self.page.get(fr.data, slot) is None:
                raise KeyError(f"{self.nome}: RID inexistente {RID(bno, slot)}")
            self.page.delete(fr.data, slot)
            vazio = self.page.count(fr.data) == 0
            prox = self._get_prox(fr.data)
        self._n -= 1
        if vazio and bno > self.n_buckets and anterior:
            with self.bm.page(self.fid, anterior, self.area, dirty=True) as fr:
                self._set_prox(fr.data, prox)
            self.bm.free_page(self.fid, bno)
            self._n_overflow -= 1

    def _localizar(self, rid: RID) -> tuple[int, Any]:
        """(bloco anterior na cadeia, chave) do RID — percorre a cadeia da chave inteira."""
        valor = self.read(rid)[self.campo]
        for anterior, bno, _, _ in self._cadeia(self.bucket_de(valor)):
            if bno == rid.bloco:
                return anterior, valor
        raise CorruptedPageError(f"{self.nome}: RID {rid} fora da cadeia do bucket da sua chave")

    def delete(self, rid: RID) -> None:
        anterior, _ = self._localizar(rid)
        self._remover(anterior, rid.bloco, rid.slot)

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        anterior, valor_antigo = self._localizar(rid)
        novo_valor = rec[self.campo]
        dado = self.codec.encode(rec)
        if novo_valor == valor_antigo:
            with self.bm.page(self.fid, rid.bloco, self.area) as fr:
                if self.page.update(fr.data, rid.slot, dado):
                    fr.mark_dirty()
                    return rid
        elif self.unique and next(self._busca_chave(novo_valor), None) is not None:
            raise ChaveDuplicadaError(f"{self.nome}: chave repetida {novo_valor!r}")
        self._remover(anterior, rid.bloco, rid.slot)
        return self.insert(rec)

    # ------------------------------------------------------------------ conjunto a conjunto
    def _blocos_fisicos(self, toss: bool = False) -> Iterator[tuple[int, list[tuple[int, bytes]]]]:
        """Todos os blocos de dados em ordem (aprox.) física: buckets 1..nB em sequência e
        depois os de overflow em ordem crescente de bloco (min-heap de ponteiros pendentes;
        cada bloco é lido uma única vez). Página solta antes do yield."""
        self._exigir_aberto()
        pendentes: list[int] = []
        for bno in range(1, self.n_buckets + 1):
            with self.bm.page(self.fid, bno, self.area, toss=toss) as fr:
                itens = [(s, self.page.get(fr.data, s)) for s in self.page.slots(fr.data)]
                prox = self._get_prox(fr.data)
            if prox:
                heapq.heappush(pendentes, prox)
            yield bno, itens
        lidos = 0
        while pendentes:
            bno = heapq.heappop(pendentes)
            with self.bm.page(self.fid, bno, self.area, toss=toss) as fr:
                itens = [(s, self.page.get(fr.data, s)) for s in self.page.slots(fr.data)]
                prox = self._get_prox(fr.data)
            if prox:
                heapq.heappush(pendentes, prox)
            lidos += 1
            if lidos > self._n_overflow:
                raise CorruptedPageError(f"{self.nome}: mais blocos de overflow que o registrado")
            yield bno, itens

    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        for bno, itens in self._blocos_fisicos(toss):
            for slot, dado in itens:
                yield RID(bno, slot), self.codec.decode(dado)

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        for _, itens in self._blocos_fisicos(toss):
            yield [self.codec.decode(d) for _, d in itens]

    def find_all(self, campo: str, op: str, valor: Any) -> Iterator[tuple[RID, dict]]:
        pred = Predicado(campo, op, valor).validar()
        self.esquema.campo(campo)
        if campo == self.campo and op == "=":
            return self._busca_chave(valor)
        return ((rid, r) for rid, r in self.scan() if pred.avaliar(r))

    def find_ordered(self, campo: str, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[tuple[RID, dict]]:
        raise OperacaoNaoSuportada("hash estático não fornece ordem (Silberschatz 14.5)")

    # ------------------------------------------------------------------ manutenção/medidas
    def reorganize(self) -> None:
        """Compacta cada bloco (slots estáveis ⇒ RIDs preservados). nB é fixo (hash estático)."""
        self._exigir_aberto()
        for b in range(self.n_buckets):
            for _, bno, _, _ in self._cadeia(b):    # 1 pin por vez; só nº de bloco em memória
                with self.bm.page(self.fid, bno, self.area, dirty=True) as fr:
                    self.page.compact(fr.data)

    def num_blocks(self) -> int:
        self._exigir_aberto()
        return self.bm.num_blocks(self.fid)

    def num_registros(self) -> int:
        return self._n

    def ocupacao(self) -> dict[str, int]:
        return {"dados": self.n_buckets, "overflow": self._n_overflow, "indice": 0,
                "total": self.num_blocks(), "registros": self._n}

    def estatisticas(self) -> dict:
        """{'buckets', 'overflow', 'cadeia_max', 'cadeia_media', 'fator_carga', 'cv_ocupacao'}.

        cadeia = nº de blocos de overflow encadeados a um bucket primário (0 = sem overflow);
        fator_carga = nr / (nB · fr), com fr = capacidade da página / tamanho médio medido;
        cv_ocupacao = desvio-padrão / média dos registros por bucket (skew, 14.5.1)."""
        cadeias, ocup = [], []
        bytes_total = 0
        for b in range(self.n_buckets):
            nblocos, nregs = 0, 0
            for _, _, itens, _ in self._cadeia(b):
                nblocos += 1
                nregs += len(itens)
                bytes_total += sum(len(d) for _, d in itens)
            cadeias.append(nblocos - 1)
            ocup.append(nregs)
        nr = sum(ocup)
        media = nr / self.n_buckets
        cv = (math.sqrt(sum((x - media) ** 2 for x in ocup) / self.n_buckets) / media) if media else 0.0
        if nr:
            cap = self.page.capacidade_max(self.bm.block_size, RESERVA_OVERFLOW)
            fr = max(1.0, cap / (bytes_total / nr))
            carga = nr / (self.n_buckets * fr)
        else:
            carga = 0.0
        return {"buckets": self.n_buckets, "overflow": sum(cadeias),
                "cadeia_max": max(cadeias), "cadeia_media": sum(cadeias) / self.n_buckets,
                "fator_carga": carga, "cv_ocupacao": cv}
