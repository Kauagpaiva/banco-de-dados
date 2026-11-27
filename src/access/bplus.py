"""Árvore B+ como organização primária (Camada 3) — M3 (E05: busca/inserção; E06: remoção, NOT UNIQUE, bulk load).

Silberschatz 14.3 (estrutura, busca, inserção com split propagado até a raiz), 14.4.1
(organização de arquivo B+: as folhas guardam os registros), 14.3.5 (NOT UNIQUE),
14.5 (bulk loading). REFERENCIA_LIVRO §4. Contrato: `FileOrganization`.

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

NOT UNIQUE (14.3.5): cada entrada de folha ganha o prefixo `u64 uniquificador` (contador crescente em
`prox_uniq`, no cabeçalho) e a chave de ordenação passa a ser a tupla `(valor, uniquificador)`; nos nós
internos o slot da chave ganha +8 B. Duplicatas ficam contíguas, em ordem de inserção.

Remoção (14.3.3): folha/nó abaixo do mínimo → fusão com o irmão se couber num nó, senão
redistribuição; propaga até a raiz; raiz interna com 1 filho é removida (altura diminui).
Bulk loading (14.5/14.4): folhas preenchidas até `fill` e níveis internos construídos de baixo para cima.

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
from src.common.erros import ChaveDuplicadaError, OperacaoNaoSuportada, RecordError, StorageError
from src.common.tipos import RID, Predicado
from src.storage.contracts import BufferManagerAPI

TIPO_FOLHA = 1
TIPO_INTERNO = 2
CAB = struct.Struct("<BBHI")
TAM_CAB = CAB.size                     # 8
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")
U64 = struct.Struct("<Q")
UMAX = (1 << 64) - 1
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
        self._pre = 0 if unique else 8                         # prefixo do uniquificador na entrada
        self.m = self.codec.max_size + SOBRA_REG + self._pre   # maior entrada de folha
        if 2 * self.m > self.C:
            raise ValueError(f"registro de até {self.codec.max_size} B não cabe 2× no bloco de {self.B} B")
        self.ks = self._kc.tam + self._pre                     # slot da chave nos nós internos
        self._n = (self.B - TAM_CAB - 4) // (self.ks + 4) + 1   # fan-out
        if self._n < 4:
            raise ValueError("fan-out < 4: bloco pequeno demais para a chave")
        self._min_folha = (self.C - self.m) // 2                # bytes
        self._min_filhos = (self._n + 1) // 2                   # ⌈n/2⌉ ponteiros
        self.fid: Optional[int] = None
        self._meta: dict = {}
        self._cursor: Optional[Iterator[RID]] = None

    # ------------------------------------------------------------------ ciclo de vida
    def open(self) -> None:
        if self.bm.exists(self.nome):
            self.fid = self.bm.open(self.nome)
            self._meta = dict(self.bm.header(self.fid)["meta"])
            if self._meta.get("campo") != self.campo or self._meta.get("unico") != self.unique:
                raise ValueError(f"{self.nome}: arquivo criado com outro campo/modo (UNIQUE)")
        else:
            self.fid = self.bm.create(self.nome, self.tipo_org, {"campo": self.campo})
            self._meta = {"campo": self.campo, "unico": self.unique, "prox_uniq": 1}
            self._nova_raiz_vazia()
        self._cursor = None

    def _nova_raiz_vazia(self) -> None:
        with self.bm.fresh_page(self.fid, "dados") as fr:
            self._fmt_folha(fr.data, [], 0)
            raiz = fr.bno
        self._meta.update(raiz=raiz, altura=1, nregs=0, primeira=raiz, nfolhas=1, ninternos=0)
        self._salvar_meta()

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

    # ------------------------------------------------------------------ chaves
    # Chave de ordenação: o valor (UNIQUE) ou a tupla (valor, uniquificador) (NOT UNIQUE).
    def _kmin(self, v):
        return v if self.unique else (v, 0)

    def _kmax(self, v):
        return v if self.unique else (v, UMAX)

    def _enc_k(self, k) -> bytes:
        return self._kc.enc(k) if self.unique else self._kc.enc(k[0]) + U64.pack(k[1])

    def _dec_k(self, buf, off: int):
        v = self._kc.dec(buf, off)
        return v if self.unique else (v, U64.unpack_from(buf, off + self._kc.tam)[0])

    def _mk_entrada(self, rec: Mapping[str, Any], uniq: int = 0) -> bytes:
        raw = self.codec.encode(rec)
        return raw if self.unique else U64.pack(uniq) + raw

    def _rec(self, e: bytes) -> dict:
        return self.codec.decode(e if self.unique else e[8:])

    def _k_entrada(self, e: bytes):
        v = self._rec(e)[self.campo]
        return v if self.unique else (v, U64.unpack_from(e, 0)[0])

    def _chave_de(self, rec: Mapping[str, Any]):
        v = rec.get(self.campo)
        if v is None:
            raise RecordError(f"chave {self.campo!r} nula")
        return v

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
        return self._k_entrada(self._entrada(buf, i))

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

    def _uso(self, entradas: list[bytes]) -> int:
        return sum(len(e) + SOBRA_REG for e in entradas)

    # ------------------------------------------------------------------ nós: interno
    def _fmt_interno(self, buf: bytearray, chaves: list, filhos: list[int]) -> None:
        if len(filhos) != len(chaves) + 1 or len(filhos) > self._n:
            raise AssertionError("nó interno inválido")
        CAB.pack_into(buf, 0, TIPO_INTERNO, 0, len(chaves), 0)
        U32.pack_into(buf, TAM_CAB, filhos[0])
        off = TAM_CAB + 4
        for k, f in zip(chaves, filhos[1:]):
            buf[off: off + self.ks] = self._enc_k(k)
            U32.pack_into(buf, off + self.ks, f)
            off += self.ks + 4

    def _ler_interno(self, buf) -> tuple[list, list[int]]:
        tipo, _, n, _ = CAB.unpack_from(buf, 0)
        if tipo != TIPO_INTERNO or n + 1 > self._n:
            raise AssertionError("nó interno inválido")
        chaves = [self._dec_k(buf, self._off_chave(i)) for i in range(n)]
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
            if self._dec_k(buf, self._off_chave(mid)) <= chave:
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

    # ------------------------------------------------------------------ busca
    def find(self, campo: str, valor: Any) -> Optional[RID]:
        self._cursor = None
        if campo == self.campo and self.unique:
            bno, _ = self._descer(valor)
            with self.bm.page(self.fid, bno, "dados") as fr:
                i = self._pos_folha(fr.data, valor)
                achou = i < CAB.unpack_from(fr.data, 0)[2] and self._chave_folha(fr.data, i) == valor
            return RID(bno, i) if achou else None
        if campo == self.campo:                    # NOT UNIQUE: duplicatas contíguas (14.3.5)
            self._cursor = (rid for rid, _ in self._faixa(valor, valor, True, True))
        else:
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
        return self._rec(raw)

    # ------------------------------------------------------------------ inserção
    def insert(self, rec: Mapping[str, Any]) -> RID:
        v = self._chave_de(rec)
        if self.unique:
            chave, raw = v, self._mk_entrada(rec)
        else:
            uniq = self._meta["prox_uniq"]
            chave, raw = (v, uniq), self._mk_entrada(rec, uniq)
        bno, caminho = self._descer(chave)
        with self.bm.page(self.fid, bno, "dados", dirty=True) as fr:
            entradas, nxt = self._ler_folha(fr.data)
            i = self._pos_folha(fr.data, chave)
            if self.unique and i < len(entradas) and self._k_entrada(entradas[i]) == chave:
                raise ChaveDuplicadaError(f"{self.campo}={chave!r}")
            entradas.insert(i, raw)
            if not self.unique:
                self._meta["prox_uniq"] += 1
            if self._uso(entradas) <= self.C:
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
        self._propagar(caminho, self._k_entrada(dir_[0]), novo_bno)
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

    # ------------------------------------------------------------------ remoção (E06)
    def _localizar(self, rid: RID):
        """(chave, caminho) do registro apontado por `rid`; KeyError se o RID for inválido. RIDs são posicionais e
        instáveis (14.4.2): um RID antigo pode apontar para outro registro — use RIDs recém-obtidos."""
        try:
            with self.bm.page(self.fid, rid.bloco, "dados") as fr:
                tipo, _, n, _ = CAB.unpack_from(fr.data, 0)
                if tipo != TIPO_FOLHA or not 0 <= rid.slot < n:
                    raise KeyError(f"RID inválido: {rid}")
                chave = self._chave_folha(fr.data, rid.slot)
        except (AssertionError, StorageError) as e:
            raise KeyError(f"RID inválido: {rid}") from e
        folha, caminho = self._descer(chave)
        if folha != rid.bloco:
            raise KeyError(f"RID obsoleto: {rid}")
        return chave, caminho

    def delete(self, rid: RID) -> None:
        """Remove o registro; folha abaixo do mínimo → redistribuição/fusão, propagando até a raiz (14.3.3)."""
        _, caminho = self._localizar(rid)
        with self.bm.page(self.fid, rid.bloco, "dados", dirty=True) as fr:
            entradas, nxt = self._ler_folha(fr.data)
            del entradas[rid.slot]
            self._fmt_folha(fr.data, entradas, nxt)
            abaixo = bool(caminho) and self._uso(entradas) < self._min_folha
        self._meta["nregs"] -= 1
        if abaixo:
            self._rebalancear(rid.bloco, caminho)
        self._salvar_meta()

    def _rebalancear(self, bno: int, caminho: list[tuple[int, int]]) -> None:
        """`bno` (não-raiz) ficou abaixo do mínimo: combina com um irmão, subindo enquanto o pai ficar abaixo."""
        folha = True
        while caminho:
            pbno, i = caminho.pop()
            nfilhos = self._combinar(bno, pbno, i, folha)
            if nfilhos is None:                      # redistribuição: o pai não mudou de tamanho
                return
            if not caminho:                          # pai é a raiz
                if nfilhos == 1:
                    self._encolher_raiz()
                return
            if nfilhos >= self._min_filhos:
                return
            bno, folha = pbno, False

    def _combinar(self, bno: int, pbno: int, i: int, folha: bool) -> Optional[int]:
        """Funde `bno` (filho i do pai `pbno`) com um irmão se couber num nó; senão redistribui.
        Devolve o nº de filhos do pai após a fusão, ou None se foi redistribuição."""
        area = "dados" if folha else "indice"
        fundiu = False
        with self.bm.page(self.fid, pbno, "indice", dirty=True) as fp:
            chaves, filhos = self._ler_interno(fp.data)
            ci = i - 1 if i > 0 else 0               # par (ci, ci+1) separado por chaves[ci]
            lb, rb = filhos[ci], filhos[ci + 1]
            with self.bm.page(self.fid, lb, area, dirty=True) as fl, \
                    self.bm.page(self.fid, rb, area, dirty=True) as fr:
                if folha:
                    el, _ = self._ler_folha(fl.data)
                    er, nr = self._ler_folha(fr.data)
                    comb = el + er
                    if self._uso(comb) <= self.C:
                        self._fmt_folha(fl.data, comb, nr)
                        fundiu = True
                    else:
                        k = self._ponto_split(comb)
                        self._fmt_folha(fl.data, comb[:k], rb)
                        self._fmt_folha(fr.data, comb[k:], nr)
                        chaves[ci] = self._k_entrada(comb[k])
                else:
                    kl, cl = self._ler_interno(fl.data)
                    kr, cr = self._ler_interno(fr.data)
                    ck, cc = kl + [chaves[ci]] + kr, cl + cr
                    if len(cc) <= self._n:
                        self._fmt_interno(fl.data, ck, cc)
                        fundiu = True
                    else:
                        k = len(cc) // 2             # ambos os lados ≥ ⌈n/2⌉ (len(cc) ≥ n+1)
                        self._fmt_interno(fl.data, ck[:k - 1], cc[:k])
                        self._fmt_interno(fr.data, ck[k:], cc[k:])
                        chaves[ci] = ck[k - 1]
            if fundiu:
                del chaves[ci]
                del filhos[ci + 1]
            self._fmt_interno(fp.data, chaves, filhos)
        if not fundiu:
            return None
        self.bm.free_page(self.fid, rb)
        self._meta["nfolhas" if folha else "ninternos"] -= 1
        return len(filhos)

    def _encolher_raiz(self) -> None:
        """Raiz interna com um único filho: o filho vira a raiz e a altura diminui (14.3.3)."""
        raiz = self._meta["raiz"]
        with self.bm.page(self.fid, raiz, "indice") as fr:
            _, filhos = self._ler_interno(fr.data)
        self.bm.free_page(self.fid, raiz)
        self._meta["raiz"] = filhos[0]
        self._meta["altura"] -= 1
        self._meta["ninternos"] -= 1

    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        """Mesma chave e cabe na folha → troca no lugar (RID igual); senão remove + insere (RID novo)."""
        novo_v = self._chave_de(rec)
        chave, caminho = self._localizar(rid)
        antigo_v = chave if self.unique else chave[0]
        cabe = abaixo = False
        if novo_v == antigo_v:
            with self.bm.page(self.fid, rid.bloco, "dados", dirty=True) as fr:
                entradas, nxt = self._ler_folha(fr.data)
                entradas[rid.slot] = self._mk_entrada(rec, 0 if self.unique else chave[1])
                uso = self._uso(entradas)
                if uso <= self.C:
                    self._fmt_folha(fr.data, entradas, nxt)
                    abaixo = bool(caminho) and uso < self._min_folha
                    cabe = True
            if cabe:
                if abaixo:                           # registro encolheu: folha pode ter caído abaixo do mínimo
                    self._rebalancear(rid.bloco, caminho)
                    self._salvar_meta()
                    return self._achar_exato(chave)
                return rid
        elif self.unique and self.find(self.campo, novo_v) is not None:
            raise ChaveDuplicadaError(f"{self.campo}={novo_v!r}")
        self.delete(rid)
        return self.insert(rec)

    def _achar_exato(self, chave) -> RID:
        bno, _ = self._descer(chave)
        with self.bm.page(self.fid, bno, "dados") as fr:
            i = self._pos_folha(fr.data, chave)
        return RID(bno, i)

    # ------------------------------------------------------------------ varreduras
    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        for bno, recs in self._folhas(self._meta["primeira"], 0, toss):
            for i, r in enumerate(recs):
                yield RID(bno, i), r

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        for _, recs in self._folhas(self._meta["primeira"], 0, toss):
            yield recs

    def _folhas(self, bno: int, i0: int, toss: bool) -> Iterator[tuple[int, list[dict]]]:
        """Percorre a cadeia de folhas a partir de (bno, i0); solta a página antes de cada yield."""
        while bno:
            with self.bm.page(self.fid, bno, "dados", toss=toss) as fr:
                entradas, nxt = self._ler_folha(fr.data)
            yield bno, [self._rec(e) for e in entradas[i0:]]
            bno, i0 = nxt, 0

    def _faixa(self, lo, hi, incl_lo: bool, incl_hi: bool) -> Iterator[tuple[RID, dict]]:
        if lo is None:
            bno, i0 = self._meta["primeira"], 0
        else:
            k_lo = self._kmin(lo) if incl_lo else self._kmax(lo)
            bno, _ = self._descer(k_lo)
            with self.bm.page(self.fid, bno, "dados") as fr:
                i0 = self._pos_folha(fr.data, k_lo, direita=not incl_lo)
        k_hi = None if hi is None else (self._kmax(hi) if incl_hi else self._kmin(hi))
        while bno:
            with self.bm.page(self.fid, bno, "dados") as fr:
                entradas, nxt = self._ler_folha(fr.data)
            for i in range(i0, len(entradas)):
                if k_hi is not None:
                    k = self._k_entrada(entradas[i])
                    if k > k_hi or (k == k_hi and not incl_hi):
                        return
                yield RID(bno, i), self._rec(entradas[i])
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

    # ------------------------------------------------------------------ bulk loading (E06)
    def bulk_load(self, registros_ordenados, fill: float = 0.8) -> None:
        """Constrói a árvore bottom-up a partir de registros já ordenados por `campo` (14.5).

        Só em árvore vazia. Folhas preenchidas até `fill` (em bytes; mínimo exigido pelas invariantes),
        encadeadas; níveis internos criados de baixo para cima até a raiz. As duas últimas folhas/nós de
        cada nível são reequilibrados para respeitar a ocupação mínima. Memória: ≤ 3 folhas por vez."""
        if self._meta["nregs"] or self._meta["altura"] != 1:
            raise ValueError("bulk_load exige árvore vazia (use reorganize())")
        if not 0 < fill <= 1:
            raise ValueError("fill deve estar em (0, 1]")
        alvo = min(self.C, max(int(fill * self.C), (self.C + self.m) // 2))
        raiz_vazia = self._meta["raiz"]
        folhas: list[tuple[int, Any]] = []           # (bloco, menor chave) em ordem
        a = b = None                                  # janela de 2 folhas pendentes: (bno, entradas)
        cur: list[bytes] = []
        uso = 0
        n = 0
        ultima = None

        def aloca() -> int:
            with self.bm.fresh_page(self.fid, "dados") as fr:
                return fr.bno

        def grava(folha, nxt: int) -> None:
            bno, ents = folha
            with self.bm.page(self.fid, bno, "dados", dirty=True) as fr:
                self._fmt_folha(fr.data, ents, nxt)
            folhas.append((bno, self._k_entrada(ents[0])))

        def fecha(ents: list[bytes]) -> None:
            nonlocal a, b
            novo = (aloca(), ents)
            if a is not None:
                grava(a, b[0])                        # a.próxima = b
            a, b = b, novo

        for rec in registros_ordenados:
            v = self._chave_de(rec)
            if self.unique:
                k, e = v, self._mk_entrada(rec)
            else:
                k, e = (v, self._meta["prox_uniq"] + n), self._mk_entrada(rec, self._meta["prox_uniq"] + n)
            if ultima is not None and (k < ultima or (self.unique and k == ultima)):
                raise ValueError(f"bulk_load: registros fora de ordem/duplicados em {self.campo}={v!r}")
            ultima = k
            n += 1
            tam = len(e) + SOBRA_REG
            if cur and uso + tam > alvo:
                fecha(cur)
                cur, uso = [], 0
            cur.append(e)
            uso += tam
        if n == 0:
            return
        fecha(cur)
        # reequilibra as duas últimas folhas se a última ficou abaixo do mínimo
        if a is not None and self._uso(b[1]) < self._min_folha:
            comb = a[1] + b[1]
            if self._uso(comb) <= self.C:
                self.bm.free_page(self.fid, b[0])
                a, b = (a[0], comb), None
            else:
                k = self._ponto_split(comb)
                a, b = (a[0], comb[:k]), (b[0], comb[k:])
        if a is not None:
            grava(a, b[0] if b else 0)
        if b is not None:
            grava(b, 0)
        # --- níveis internos
        self.bm.free_page(self.fid, raiz_vazia)       # a folha vazia original sai (a 1ª folha nova é `primeira`)
        nivel = folhas
        internos = 0
        altura = 1
        while len(nivel) > 1:
            cap = max(self._min_filhos, min(self._n, -(-int(fill * self._n * 1000) // 1000)))
            grupos = [nivel[j:j + cap] for j in range(0, len(nivel), cap)]
            if len(grupos) > 1 and len(grupos[-1]) < self._min_filhos:
                comb = grupos[-2] + grupos[-1]
                if len(comb) <= self._n:
                    grupos[-2:] = [comb]
                else:
                    k = len(comb) // 2
                    grupos[-2:] = [comb[:k], comb[k:]]
            prox = []
            for g in grupos:
                with self.bm.fresh_page(self.fid, "indice") as fr:
                    self._fmt_interno(fr.data, [c for _, c in g[1:]], [bno for bno, _ in g])
                    prox.append((fr.bno, g[0][1]))
            internos += len(prox)
            nivel = prox
            altura += 1
        self._meta.update(raiz=nivel[0][0], altura=altura, nregs=n, primeira=folhas[0][0],
                          nfolhas=len(folhas), ninternos=internos)
        if not self.unique:
            self._meta["prox_uniq"] += n
        self._salvar_meta()

    def _limpar(self) -> None:
        """Libera todos os nós e recria a raiz folha vazia (preserva o contador de uniquificadores)."""
        def libera(bno: int, nivel: int) -> None:
            if nivel < self._meta["altura"]:
                with self.bm.page(self.fid, bno, "indice") as fr:
                    _, filhos = self._ler_interno(fr.data)
                for f in filhos:
                    libera(f, nivel + 1)
            self.bm.free_page(self.fid, bno)
        libera(self._meta["raiz"], 1)
        self._nova_raiz_vazia()

    def reorganize(self) -> None:
        """Reconstrói a árvore por bulk load (ocupação alta, folhas contíguas): copia em streaming para
        uma árvore temporária, limpa esta e recarrega a partir da temporária."""
        tmp = BPlusTree(self.bm, f"{self.nome}.reorg", self.esquema, self.campo, unique=self.unique,
                        codec=self.codec)
        if self.bm.exists(tmp.nome):                 # sobra de uma reorganização interrompida
            self.bm.delete(tmp.nome)
        tmp.open()
        try:
            tmp.bulk_load((r for _, r in self.scan()))
            self._limpar()
            self.bulk_load((r for _, r in tmp.scan()))
        finally:
            tmp.close()
            self.bm.delete(tmp.nome)
        self._cursor = None

    # ------------------------------------------------------------------ invariantes
    def check_invariants(self) -> None:
        """AssertionError se: ordem, ocupação mínima (exceto raiz), folhas na mesma profundidade,
        encadeamento completo/ordenado ou contagem de registros falharem."""
        folhas: list[int] = []
        contagem = [0, 0, 0]               # registros, folhas, internos

        def falha(msg: str):
            raise AssertionError(msg)

        def visita(bno: int, nivel: int, lo, hi) -> None:
            ehraiz = nivel == 1
            if nivel == self._meta["altura"]:                       # folha
                with self.bm.page(self.fid, bno, "dados") as fr:
                    entradas, _ = self._ler_folha(fr.data)
                ks = [self._k_entrada(e) for e in entradas]
                if any(a >= b for a, b in zip(ks, ks[1:])):
                    falha(f"folha {bno}: chaves fora de ordem/duplicadas")
                if ks and ((lo is not None and ks[0] < lo) or (hi is not None and ks[-1] >= hi)):
                    falha(f"folha {bno}: chave fora do intervalo do pai")
                uso = self._uso(entradas)
                if uso > self.C:
                    falha(f"folha {bno}: estourou o bloco")
                if not ehraiz and (not entradas or uso < self._min_folha):
                    falha(f"folha {bno}: ocupação mínima violada ({uso} B < {self._min_folha} B)")
                folhas.append(bno)
                contagem[0] += len(entradas)
                contagem[1] += 1
                return
            with self.bm.page(self.fid, bno, "indice") as fr:
                chaves, filhos = self._ler_interno(fr.data)
            if any(a >= b for a, b in zip(chaves, chaves[1:])):
                falha(f"interno {bno}: chaves fora de ordem")
            if len(filhos) < (2 if ehraiz else self._min_filhos):
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
