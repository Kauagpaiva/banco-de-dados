"""Árvore B+ como organização primária (Camada 3) — M3 (E05: busca/inserção; E06: remoção etc.).

Silberschatz 14.3 (estrutura, busca, inserção com split propagado até a raiz), 14.4.1
(organização de arquivo B+: as folhas guardam os registros), 14.3.5 (NOT UNIQUE — E06),
14.5 (bulk loading — E06). REFERENCIA_LIVRO §4. Contrato: `FileOrganization`.

Arquivo: 1 arquivo por árvore (bloco 0 = cabeçalho do FileManager). Meta no cabeçalho:
`raiz`, `altura`, `nregs`, `primeira` (folha mais à esquerda), `nfolhas`, `ninternos`.
Nós internos na área 'indice'; folhas na área 'dados'. Nó = 1 bloco (config `bplus.node_blocks`).

Layout dos nós (todos os inteiros little-endian; B = tamanho do bloco):

    cabeçalho (8 B):  '<BBHI'  tipo (1=folha, 2=interno) · reservado · n · próxima folha (0 = fim)

  Folha:    cabeçalho | diretório de n offsets u16 (em ORDEM DE CHAVE) | ... espaço livre ... |
            registros empacotados a partir do FIM do bloco, cada um `u16 tamanho + bytes do codec`.
            A busca binária opera sobre o diretório do bloco já pinado (decodifica só os
            registros sondados). RID = (bloco da folha, posição no diretório) — **instável**
            em inserção/split/fusão (14.4.2); os testes obtêm o RID atual com `find`.
  Interno:  cabeçalho | filho_0 (u32) | { chave_i (slot fixo de `ks` bytes) , filho_{i+1} (u32) } × n
            chave_i = menor chave do filho_{i+1}. Slot de chave de largura fixa ⇒ busca binária
            direta no buffer. Chave: int '<q' · float '<d' · date '<i'(ordinal) · char/varchar
            `u16 tamanho + utf-8` preenchido até `n` bytes.

Fan-out: `fanout() = n` = nº máximo de ponteiros de um nó interno = (B − 8 − 4) // (ks + 4) + 1.
Nó interno não-raiz: de ⌈n/2⌉ a n ponteiros; raiz interna: ≥ 2. Folha (registros de tamanho
variável ⇒ ocupação por BYTES): a divisão escolhe o ponto mais balanceado, logo toda folha
não-raiz ocupa ≥ (C − m)/2 bytes, com C = B − 8 e m = maior registro (+4 B de diretório/tamanho).
"""
from __future__ import annotations

import datetime
import struct
from typing import Any, Iterator, Mapping, Optional

from src.access.contracts import Esquema, FileOrganization, RecordCodecAPI, padroes
from src.common.erros import ChaveDuplicadaError, OperacaoNaoSuportada, RecordError
from src.common.tipos import RID, Predicado
from src.storage.contracts import BufferManagerAPI

TIPO_FOLHA = 1
TIPO_INTERNO = 2
CAB = struct.Struct("<BBHI")
TAM_CAB = CAB.size                     # 8
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")
SOBRA_REG = 4                          # u16 de tamanho + u16 do diretório, por registro


class _CodecChave:
    """Codifica/decodifica a chave de busca num slot de largura fixa (nós internos)."""

    def __init__(self, campo):
        b = campo.base
        if b not in ("int", "float", "date", "char", "varchar"):
            raise ValueError(f"campo {campo.nome!r} ({campo.tipo}) não pode ser chave da B+")
        self.base = b
        self.n = campo.n
        self.tam = {"int": 8, "float": 8, "date": 4}.get(b, 2 + campo.n)

    def enc(self, v) -> bytes:
        b = self.base
        if b == "int":
            return struct.pack("<q", v)
        if b == "float":
            return struct.pack("<d", v)
        if b == "date":
            return struct.pack("<i", v.toordinal())
        raw = v.encode("utf-8")
        return U16.pack(len(raw)) + raw.ljust(self.n, b"\0")

    def dec(self, buf, off: int):
        b = self.base
        if b == "int":
            return struct.unpack_from("<q", buf, off)[0]
        if b == "float":
            return struct.unpack_from("<d", buf, off)[0]
        if b == "date":
            return datetime.date.fromordinal(struct.unpack_from("<i", buf, off)[0])
        n = U16.unpack_from(buf, off)[0]
        if n > self.n:
            raise AssertionError("chave corrompida no nó interno")
        return bytes(buf[off + 2: off + 2 + n]).decode("utf-8")


class BPlusTree(FileOrganization):
    tipo_org = "bplus"

    def __init__(self, bm: BufferManagerAPI, nome: str, esquema: Esquema, campo: str, *,
                 unique: bool = True, page_impl: type | None = None,
                 codec: RecordCodecAPI | None = None):
        if not unique:
            raise OperacaoNaoSuportada("B+ NOT UNIQUE: previsto na E06")
        self.bm = bm
        self.nome = nome
        self.esquema = esquema
        self.campo = campo
        self.unique = unique
        self._campo = esquema.campo(campo)
        self._kc = _CodecChave(self._campo)
        _, self.codec = padroes(esquema, page_impl, codec)   # page_impl: não usado (layout próprio)
        self.B = bm.block_size
        self.C = self.B - TAM_CAB                              # bytes úteis de uma folha
        self.m = self.codec.max_size + SOBRA_REG               # maior entrada de folha
        if 2 * self.m > self.C:
            raise ValueError(f"registro de até {self.codec.max_size} B não cabe 2× no bloco de {self.B} B")
        self.ks = self._kc.tam
        self._n = (self.B - TAM_CAB - 4) // (self.ks + 4) + 1   # fan-out
        if self._n < 4:
            raise ValueError("fan-out < 4: bloco pequeno demais para a chave")
        self.fid: Optional[int] = None
        self._meta: dict = {}
        self._cursor: Optional[Iterator[RID]] = None

    # ------------------------------------------------------------------ ciclo de vida
    def open(self) -> None:
        if self.bm.exists(self.nome):
            self.fid = self.bm.open(self.nome)
            self._meta = dict(self.bm.header(self.fid)["meta"])
            if self._meta.get("campo") != self.campo:
                raise ValueError(f"{self.nome}: arquivo criado para o campo {self._meta.get('campo')!r}")
        else:
            self.fid = self.bm.create(self.nome, self.tipo_org, {"campo": self.campo})
            with self.bm.fresh_page(self.fid, "dados") as fr:
                self._fmt_folha(fr.data, [], 0)
                raiz = fr.bno
            self._meta = {"campo": self.campo, "raiz": raiz, "altura": 1, "nregs": 0,
                          "primeira": raiz, "nfolhas": 1, "ninternos": 0}
            self._salvar_meta()
        self._cursor = None

    def close(self) -> None:
        if self.fid is not None:
            self._salvar_meta()
            self.bm.close(self.fid)
            self.fid = None

    def reset(self) -> None:
        self._cursor = None

    def _salvar_meta(self) -> None:
        self.bm.set_header(self.fid, **self._meta)

    # ------------------------------------------------------------------ medidas
    def altura(self) -> int:
        """Nº de níveis (raiz folha = 1)."""
        return self._meta["altura"]

    def fanout(self) -> int:
        """n: nº máximo de ponteiros num nó interno."""
        return self._n

    def num_blocks(self) -> int:
        return self._meta["nfolhas"] + self._meta["ninternos"]

    def num_registros(self) -> int:
        return self._meta["nregs"]

    def ocupacao(self) -> dict[str, int]:
        return {"dados": self._meta["nfolhas"], "overflow": 0, "indice": self._meta["ninternos"],
                "total": self.num_blocks(), "registros": self._meta["nregs"]}

    # ------------------------------------------------------------------ nós: folha
    def _fmt_folha(self, buf: bytearray, entradas: list[bytes], nxt: int) -> None:
        """Regrava a folha inteira a partir das entradas (já em ordem de chave)."""
        n = len(entradas)
        CAB.pack_into(buf, 0, TIPO_FOLHA, 0, n, nxt)
        pos = self.B
        for i, e in enumerate(entradas):
            pos -= 2 + len(e)
            U16.pack_into(buf, pos, len(e))
            buf[pos + 2: pos + 2 + len(e)] = e
            U16.pack_into(buf, TAM_CAB + 2 * i, pos)
        if TAM_CAB + 2 * n > pos:
            raise AssertionError("folha estourou o bloco")

    def _ler_folha(self, buf) -> tuple[list[bytes], int]:
        tipo, _, n, nxt = CAB.unpack_from(buf, 0)
        if tipo != TIPO_FOLHA:
            raise AssertionError("nó esperado como folha")
        return [self._entrada(buf, i) for i in range(n)], nxt

    def _entrada(self, buf, i: int) -> bytes:
        off = U16.unpack_from(buf, TAM_CAB + 2 * i)[0]
        if off < TAM_CAB or off + 2 > self.B:
            raise AssertionError("offset de registro fora do bloco")
        ln = U16.unpack_from(buf, off)[0]
        if off + 2 + ln > self.B:
            raise AssertionError("tamanho de registro fora do bloco")
        return bytes(buf[off + 2: off + 2 + ln])

    def _chave_folha(self, buf, i: int):
        return self.codec.decode(self._entrada(buf, i))[self.campo]

    def _pos_folha(self, buf, chave, direita: bool = False) -> int:
        """Busca binária sobre o diretório da folha pinada: 1º índice com chave ≥ `chave`
        (ou > `chave` se `direita`)."""
        lo, hi = 0, CAB.unpack_from(buf, 0)[2]
        while lo < hi:
            mid = (lo + hi) // 2
            k = self._chave_folha(buf, mid)
            if k < chave or (direita and k == chave):
                lo = mid + 1
            else:
                hi = mid
        return lo

    # ------------------------------------------------------------------ nós: interno
    def _fmt_interno(self, buf: bytearray, chaves: list, filhos: list[int]) -> None:
        if len(filhos) != len(chaves) + 1 or len(filhos) > self._n:
            raise AssertionError("nó interno inválido")
        CAB.pack_into(buf, 0, TIPO_INTERNO, 0, len(chaves), 0)
        U32.pack_into(buf, TAM_CAB, filhos[0])
        off = TAM_CAB + 4
        for k, f in zip(chaves, filhos[1:]):
            buf[off: off + self.ks] = self._kc.enc(k)
            U32.pack_into(buf, off + self.ks, f)
            off += self.ks + 4

    def _ler_interno(self, buf) -> tuple[list, list[int]]:
        tipo, _, n, _ = CAB.unpack_from(buf, 0)
        if tipo != TIPO_INTERNO or n + 1 > self._n:
            raise AssertionError("nó interno inválido")
        chaves = [self._kc.dec(buf, self._off_chave(i)) for i in range(n)]
        filhos = [U32.unpack_from(buf, TAM_CAB)[0]] + [
            U32.unpack_from(buf, self._off_chave(i) + self.ks)[0] for i in range(n)]
        return chaves, filhos

    def _off_chave(self, i: int) -> int:
        return TAM_CAB + 4 + i * (self.ks + 4)

    def _filho(self, buf, i: int) -> int:
        off = TAM_CAB if i == 0 else self._off_chave(i - 1) + self.ks
        return U32.unpack_from(buf, off)[0]

    def _indice_filho(self, buf, chave) -> int:
        """Busca binária direta no nó interno pinado: nº de chaves ≤ `chave` (= filho a seguir)."""
        lo, hi = 0, CAB.unpack_from(buf, 0)[2]
        while lo < hi:
            mid = (lo + hi) // 2
            if self._kc.dec(buf, self._off_chave(mid)) <= chave:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # ------------------------------------------------------------------ descida
    def _descer(self, chave) -> tuple[int, list[tuple[int, int]]]:
        """Folha onde `chave` está/entraria + caminho [(bloco interno, índice do filho)] da raiz
        até o pai. Um único bloco pinado por vez."""
        bno = self._meta["raiz"]
        caminho: list[tuple[int, int]] = []
        for _ in range(self._meta["altura"] - 1):
            with self.bm.page(self.fid, bno, "indice") as fr:
                i = self._indice_filho(fr.data, chave)
                prox = self._filho(fr.data, i)
            caminho.append((bno, i))
            bno = prox
        return bno, caminho

    def _folha_esquerda(self) -> int:
        return self._meta["primeira"]

    # ------------------------------------------------------------------ busca
    def _chave_de(self, rec: Mapping[str, Any]):
        v = rec.get(self.campo)
        if v is None:
            raise RecordError(f"chave {self.campo!r} nula")
        return v

    def find(self, campo: str, valor: Any) -> Optional[RID]:
        self._cursor = None
        if campo == self.campo:
            bno, _ = self._descer(valor)
            with self.bm.page(self.fid, bno, "dados") as fr:
                i = self._pos_folha(fr.data, valor)
                achou = i < CAB.unpack_from(fr.data, 0)[2] and self._chave_folha(fr.data, i) == valor
            return RID(bno, i) if achou else None
        self._cursor = (rid for rid, rec in self.scan() if rec.get(campo) == valor)
        return self.find_next()

    def find_next(self) -> Optional[RID]:
        if self._cursor is None:
            return None
        try:
            return next(self._cursor)
        except StopIteration:
            self._cursor = None
            return None

    def read(self, rid: RID) -> dict:
        with self.bm.page(self.fid, rid.bloco, "dados") as fr:
            tipo, _, n, _ = CAB.unpack_from(fr.data, 0)
            if tipo != TIPO_FOLHA or not 0 <= rid.slot < n:
                raise KeyError(f"RID inválido: {rid}")
            raw = self._entrada(fr.data, rid.slot)
        return self.codec.decode(raw)

    # ------------------------------------------------------------------ inserção
    def insert(self, rec: Mapping[str, Any]) -> RID:
        chave = self._chave_de(rec)
        raw = self.codec.encode(rec)
        bno, caminho = self._descer(chave)
        with self.bm.page(self.fid, bno, "dados", dirty=True) as fr:
            entradas, nxt = self._ler_folha(fr.data)
            i = self._pos_folha(fr.data, chave)
            if i < len(entradas) and self.codec.decode(entradas[i])[self.campo] == chave:
                raise ChaveDuplicadaError(f"{self.campo}={chave!r}")
            entradas.insert(i, raw)
            if sum(len(e) + SOBRA_REG for e in entradas) <= self.C:
                self._fmt_folha(fr.data, entradas, nxt)
                self._meta["nregs"] += 1
                self._salvar_meta()
                return RID(bno, i)
            # ---- split de folha (14.3.2): metade mais balanceada por bytes; sobe cópia da 1ª chave da direita
            k = self._ponto_split(entradas)
            esq, dir_ = entradas[:k], entradas[k:]
            with self.bm.fresh_page(self.fid, "dados") as nova:
                self._fmt_folha(nova.data, dir_, nxt)
                novo_bno = nova.bno
            self._fmt_folha(fr.data, esq, novo_bno)
        self._meta["nregs"] += 1
        self._meta["nfolhas"] += 1
        sep = self.codec.decode(dir_[0])[self.campo]
        self._propagar(caminho, sep, novo_bno)
        self._salvar_meta()
        return RID(bno, i) if i < k else RID(novo_bno, i - k)

    def _ponto_split(self, entradas: list[bytes]) -> int:
        """Índice k (1..n-1) que melhor equilibra os bytes de [:k] e [k:], ambos cabendo na folha."""
        tam = [len(e) + SOBRA_REG for e in entradas]
        total, esq, melhor, dif = sum(tam), 0, None, None
        for k in range(1, len(entradas)):
            esq += tam[k - 1]
            if esq <= self.C and total - esq <= self.C:
                d = abs(total - 2 * esq)
                if dif is None or d < dif:
                    melhor, dif = k, d
        if melhor is None:
            raise AssertionError("split de folha impossível")
        return melhor

    def _propagar(self, caminho: list[tuple[int, int]], sep, novo: int) -> None:
        """Insere (sep, novo) no pai; divide nós internos cheios, subindo até criar nova raiz (14.3.2)."""
        while caminho:
            bno, i = caminho.pop()
            with self.bm.page(self.fid, bno, "indice", dirty=True) as fr:
                chaves, filhos = self._ler_interno(fr.data)
                chaves.insert(i, sep)
                filhos.insert(i + 1, novo)
                if len(filhos) <= self._n:
                    self._fmt_interno(fr.data, chaves, filhos)
                    return
                mid = len(chaves) // 2           # chave do meio sobe (não fica em nenhum dos dois)
                sep = chaves[mid]
                with self.bm.fresh_page(self.fid, "indice") as nova:
                    self._fmt_interno(nova.data, chaves[mid + 1:], filhos[mid + 1:])
                    novo = nova.bno
                self._fmt_interno(fr.data, chaves[:mid], filhos[:mid + 1])
                self._meta["ninternos"] += 1
        with self.bm.fresh_page(self.fid, "indice") as raiz:      # a raiz foi dividida: nova raiz
            self._fmt_interno(raiz.data, [sep], [self._meta["raiz"], novo])
            self._meta["raiz"] = raiz.bno
        self._meta["altura"] += 1
        self._meta["ninternos"] += 1

    # ------------------------------------------------------------------ varreduras
    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        for bno, recs in self._folhas(self._folha_esquerda(), 0, toss):
            for i, r in enumerate(recs):
                yield RID(bno, i), r

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        for _, recs in self._folhas(self._folha_esquerda(), 0, toss):
            yield recs

    def _folhas(self, bno: int, i0: int, toss: bool) -> Iterator[tuple[int, list[dict]]]:
        """Percorre a cadeia de folhas a partir de (bno, i0); solta a página antes de cada yield."""
        while bno:
            with self.bm.page(self.fid, bno, "dados", toss=toss) as fr:
                entradas, nxt = self._ler_folha(fr.data)
            yield bno, [self.codec.decode(e) for e in entradas[i0:]]
            bno, i0 = nxt, 0

    def _faixa(self, lo, hi, incl_lo: bool, incl_hi: bool) -> Iterator[tuple[RID, dict]]:
        if lo is None:
            bno, i0 = self._folha_esquerda(), 0
        else:
            bno, _ = self._descer(lo)
            with self.bm.page(self.fid, bno, "dados") as fr:
                i0 = self._pos_folha(fr.data, lo, direita=not incl_lo)
        while bno:
            with self.bm.page(self.fid, bno, "dados") as fr:
                entradas, nxt = self._ler_folha(fr.data)
            for i in range(i0, len(entradas)):
                rec = self.codec.decode(entradas[i])
                k = rec[self.campo]
                if hi is not None and (k > hi or (k == hi and not incl_hi)):
                    return
                yield RID(bno, i), rec
            bno, i0 = nxt, 0

    def find_ordered(self, campo: str, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[tuple[RID, dict]]:
        if campo != self.campo:
            raise OperacaoNaoSuportada(f"B+ ordenada por {self.campo!r}, não por {campo!r}")
        return self._faixa(lo, hi, incl_lo, incl_hi)

    def find_all(self, campo: str, op: str, valor: Any) -> Iterator[tuple[RID, dict]]:
        pred = Predicado(campo, op, valor)
        pred.validar()
        if campo != self.campo:
            return ((rid, r) for rid, r in self.scan() if pred.avaliar(r))
        if op == "=":
            return self._faixa(valor, valor, True, True)
        if op in ("<", "<="):
            return self._faixa(None, valor, True, op == "<=")
        return self._faixa(valor, None, op == ">=", True)

    # ------------------------------------------------------------------ invariantes
    def check_invariants(self) -> None:
        """AssertionError se: ordem, ocupação mínima (exceto raiz), folhas na mesma profundidade,
        encadeamento completo/ordenado ou contagem de registros falharem."""
        folhas: list[int] = []
        contagem = [0, 0, 0]               # registros, folhas, internos
        min_folha = (self.C - self.m) // 2
        min_filhos = (self._n + 1) // 2

        def falha(msg: str):
            raise AssertionError(msg)

        def visita(bno: int, nivel: int, lo, hi) -> None:
            ehraiz = nivel == 1
            if nivel == self._meta["altura"]:                       # folha
                with self.bm.page(self.fid, bno, "dados") as fr:
                    entradas, _ = self._ler_folha(fr.data)
                ks = [self.codec.decode(e)[self.campo] for e in entradas]
                if ks != sorted(ks) or len(set(ks)) != len(ks):
                    falha(f"folha {bno}: chaves fora de ordem/duplicadas")
                if ks and ((lo is not None and ks[0] < lo) or (hi is not None and ks[-1] >= hi)):
                    falha(f"folha {bno}: chave fora do intervalo do pai")
                uso = sum(len(e) + SOBRA_REG for e in entradas)
                if uso > self.C:
                    falha(f"folha {bno}: estourou o bloco")
                if not ehraiz and (not entradas or uso < min_folha):
                    falha(f"folha {bno}: ocupação mínima violada ({uso} B < {min_folha} B)")
                folhas.append(bno)
                contagem[0] += len(entradas)
                contagem[1] += 1
                return
            with self.bm.page(self.fid, bno, "indice") as fr:
                chaves, filhos = self._ler_interno(fr.data)
            if chaves != sorted(chaves) or len(set(chaves)) != len(chaves):
                falha(f"interno {bno}: chaves fora de ordem")
            if len(filhos) < (2 if ehraiz else min_filhos):
                falha(f"interno {bno}: ocupação mínima violada ({len(filhos)} ponteiros)")
            if chaves and ((lo is not None and chaves[0] < lo) or (hi is not None and chaves[-1] >= hi)):
                falha(f"interno {bno}: chave fora do intervalo do pai")
            contagem[2] += 1
            limites = [lo] + chaves + [hi]
            for j, f in enumerate(filhos):
                visita(f, nivel + 1, limites[j], limites[j + 1])

        visita(self._meta["raiz"], 1, None, None)
        # encadeamento: a cadeia de `próxima` deve visitar as folhas na ordem da árvore
        cadeia, bno = [], self._meta["primeira"]
        while bno:
            if len(cadeia) > len(folhas):
                falha("encadeamento de folhas com ciclo")
            cadeia.append(bno)
            with self.bm.page(self.fid, bno, "dados") as fr:
                bno = CAB.unpack_from(fr.data, 0)[3]
        if cadeia != folhas:
            falha("encadeamento de folhas incompleto ou fora de ordem")
        if contagem[0] != self._meta["nregs"]:
            falha(f"contagem de registros: {contagem[0]} nas folhas × {self._meta['nregs']} no cabeçalho")
        if contagem[1] != self._meta["nfolhas"] or contagem[2] != self._meta["ninternos"]:
            falha("contagem de nós diverge do cabeçalho")

    # ------------------------------------------------------------------ E06 (pendente)
    def bulk_load(self, registros_ordenados, fill: float = 0.8) -> None:
        """Constrói a árvore bottom-up a partir de registros já ordenados por `campo` (14.5)."""
        raise NotImplementedError("M3/E06")

    def delete(self, rid: RID) -> None:
        raise NotImplementedError("M3/E06")

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        raise NotImplementedError("M3/E06")

    def reorganize(self) -> None:
        raise NotImplementedError("M3/E06")
