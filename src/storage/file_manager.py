"""Gerente de Arquivos (Camada 4a) — M1/E01.

Silberschatz 12.3 (disco: seek × transferência), 12.6 (acesso a blocos, sequencial ×
aleatório), 13.2 (arquivo como sequência de blocos). REFERENCIA_LIVRO §1. Contrato: `FileManagerAPI`.

Layout físico (D03): **1 arquivo do SO por estrutura** em `base_dir/<nome>.dat`; o bloco `b`
fica no deslocamento `b * block_size`. **Bloco 0 = cabeçalho**:

    struct '<4sHH16sIIIIII' = magic 'SBD1', versão, reservado, tipo_org (16 B),
                              num_alocados, proximo, livre, extent, num_livres, len(meta)
    seguido de `meta` em JSON UTF-8 (limitado ao que sobra do bloco).

- Alocação por **extents** de `extent` blocos (D02): o arquivo cresce de `extent` em `extent`
  blocos (`num_alocados` = blocos de dados reservados); `proximo` = 1º bloco nunca usado.
- **Lista livre encadeada** (D04): a cabeça fica no cabeçalho (`livre`); cada bloco livre guarda
  `'LIVR' + próximo livre` nos seus primeiros 8 bytes. Liberar = 1 escrita; reusar = 1 leitura
  (para obter o próximo da lista) — ambas contam como I/O.
- **Cabeçalho write-back**: lido do disco no `open` (1 leitura, conta I/O); alterações ficam em
  memória e são gravadas (1 escrita, conta I/O) em `close`/`sync`. Ver `docs/decisoes/M1.md`.
- Seek: braço global (D05), em `IOStats`.
- **Não há cache de blocos**: toda chamada de `read_block`/`write_block` vai ao arquivo do SO.
  Só o BufferManager chama `read_block`/`write_block`.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

from src.common.erros import StorageError
from src.storage.contracts import FileManagerAPI
from src.storage.stats import IOStats

MAGIC = b"SBD1"
VERSAO = 1
HDR = struct.Struct("<4sHH16sIIIIII")
TAM_TIPO_ORG = 16
MAGIC_LIVRE = b"LIVR"
LIVRE = struct.Struct("<4sI")
EXTENSAO = ".dat"
SEEK_MODELS = ("braco_global",)
_NOME_OK = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-]*$")


class _Aberto:
    """Estado de um arquivo aberto: handle do SO + cabeçalho em memória + espelho da lista livre.

    O espelho (`livres`) só guarda **números** de blocos livres (metadado, não conteúdo), usado
    para validar acessos; a cadeia autoritativa está no disco e é conferida a cada reuso.
    """

    def __init__(self, nome: str, caminho: Path, fh, hdr: dict, livres: list[int]):
        self.nome = nome
        self.caminho = caminho
        self.fh = fh
        self.hdr = hdr                    # tipo_org, num_alocados, proximo, livre, extent, meta
        self.livres = livres              # ordem da cadeia: livres[0] == hdr['livre']
        self.livres_set = set(livres)
        self.hdr_dirty = False


class FileManager(FileManagerAPI):
    """Gerente de arquivos sobre arquivos do SO, com contagem de I/O (`self.stats`)."""

    def __init__(self, cfg, base_dir: Path | str | None = None):
        if cfg.seek_model not in SEEK_MODELS:
            raise StorageError(f"modelo de seek não suportado: {cfg.seek_model!r}")
        self.cfg = cfg
        self.block_size: int = cfg.block_size
        self.extent_blocks: int = cfg.extent_blocks
        if self.block_size < HDR.size + 2 or self.extent_blocks < 1:
            raise StorageError("block_size/extent_blocks inválidos")
        self.base_dir = Path(base_dir) if base_dir is not None else Path(cfg.perfil_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.stats = IOStats()
        self._abertos: dict[int, _Aberto] = {}
        self._fid_por_nome: dict[str, int] = {}
        self._prox_fid = 1

    # ------------------------------------------------------------------ helpers internos
    def _caminho(self, nome: str) -> Path:
        if not isinstance(nome, str) or not _NOME_OK.match(nome) or ".." in nome:
            raise StorageError(f"nome de arquivo inválido: {nome!r}")
        return self.base_dir / f"{nome}{EXTENSAO}"

    def _arq(self, fid: int) -> _Aberto:
        try:
            return self._abertos[fid]
        except KeyError:
            raise StorageError(f"fid inválido/fechado: {fid}") from None

    def _meta_json(self, meta: dict) -> bytes:
        try:
            dados = json.dumps(meta, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as e:
            raise StorageError(f"meta do cabeçalho não serializável em JSON: {e}") from None
        if HDR.size + len(dados) > self.block_size:
            raise StorageError(f"meta do cabeçalho ({len(dados)} B) não cabe no bloco 0 "
                               f"({self.block_size - HDR.size} B disponíveis)")
        return dados

    def _codificar_hdr(self, hdr: dict) -> bytes:
        meta = self._meta_json(hdr["meta"])
        tipo = hdr["tipo_org"].encode("utf-8")
        bruto = HDR.pack(MAGIC, VERSAO, 0, tipo, hdr["num_alocados"], hdr["proximo"],
                         hdr["livre"], hdr["extent"], hdr["num_livres"], len(meta)) + meta
        return bruto.ljust(self.block_size, b"\0")

    def _decodificar_hdr(self, bruto: bytes, nome: str) -> dict:
        if len(bruto) < HDR.size:
            raise StorageError(f"{nome}: cabeçalho truncado")
        (magic, versao, _res, tipo, num_aloc, prox, livre, extent, num_livres,
         tam_meta) = HDR.unpack_from(bruto, 0)
        if magic != MAGIC or versao != VERSAO:
            raise StorageError(f"{nome}: cabeçalho inválido (magic/versão)")
        if HDR.size + tam_meta > self.block_size:
            raise StorageError(f"{nome}: tamanho do meta ({tam_meta}) fora do bloco 0")
        if not (1 <= prox <= num_aloc + 1) or num_livres > prox - 1 or extent < 1:
            raise StorageError(f"{nome}: cabeçalho inconsistente")
        try:
            meta = json.loads(bruto[HDR.size:HDR.size + tam_meta].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise StorageError(f"{nome}: meta do cabeçalho corrompido") from None
        return {"tipo_org": tipo.rstrip(b"\0").decode("utf-8"), "num_alocados": num_aloc,
                "proximo": prox, "livre": livre, "extent": extent, "num_livres": num_livres,
                "meta": meta}

    def _ler_fisico(self, a: _Aberto, fid: int, bno: int) -> bytearray:
        a.fh.seek(bno * self.block_size)
        dados = a.fh.read(self.block_size)
        self.stats.registrar(fid, bno, escrita=False)
        return bytearray(dados.ljust(self.block_size, b"\0"))

    def _gravar_fisico(self, a: _Aberto, fid: int, bno: int, dados: bytes) -> None:
        a.fh.seek(bno * self.block_size)
        a.fh.write(dados)
        self.stats.registrar(fid, bno, escrita=True)

    def _gravar_hdr(self, fid: int) -> None:
        a = self._arq(fid)
        self._gravar_fisico(a, fid, 0, self._codificar_hdr(a.hdr))
        a.fh.flush()
        a.hdr_dirty = False

    def _checar_bloco(self, a: _Aberto, bno: int) -> None:
        if not isinstance(bno, int) or bno < 1 or bno >= a.hdr["proximo"]:
            raise StorageError(f"{a.nome}: bloco não alocado: {bno}")
        if bno in a.livres_set:
            raise StorageError(f"{a.nome}: bloco {bno} está na lista livre")

    # ------------------------------------------------------------------ arquivos
    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int:
        caminho = self._caminho(nome)
        if caminho.exists():
            raise StorageError(f"arquivo já existe: {nome}")
        if len(tipo_org.encode("utf-8")) > TAM_TIPO_ORG:
            raise StorageError(f"tipo_org longo demais (máx. {TAM_TIPO_ORG} B): {tipo_org!r}")
        hdr = {"tipo_org": tipo_org, "num_alocados": 0, "proximo": 1, "livre": 0,
               "extent": self.extent_blocks, "num_livres": 0, "meta": dict(meta or {})}
        bruto = self._codificar_hdr(hdr)      # valida meta antes de criar o arquivo
        with open(caminho, "xb") as fh:       # escrita inicial do cabeçalho: criação, não I/O medido
            fh.write(bruto)
        fh = open(caminho, "r+b")
        fid = self._registrar_aberto(nome, caminho, fh, hdr, [])
        return fid

    def _registrar_aberto(self, nome, caminho, fh, hdr, livres) -> int:
        fid = self._prox_fid
        self._prox_fid += 1
        self._abertos[fid] = _Aberto(nome, caminho, fh, hdr, livres)
        self._fid_por_nome[nome] = fid
        return fid

    def open(self, nome: str) -> int:
        if nome in self._fid_por_nome:
            return self._fid_por_nome[nome]
        caminho = self._caminho(nome)
        if not caminho.exists():
            raise StorageError(f"arquivo inexistente: {nome}")
        fh = open(caminho, "r+b")
        try:
            tam = caminho.stat().st_size
            if tam % self.block_size:
                raise StorageError(f"{nome}: tamanho {tam} não é múltiplo do bloco "
                                   f"({self.block_size}) — block_size diferente?")
            fid = self._prox_fid
            a = _Aberto(nome, caminho, fh, {}, [])
            a.hdr = self._decodificar_hdr(self._ler_fisico(a, fid, 0), nome)
            if tam != (1 + a.hdr["num_alocados"]) * self.block_size:
                raise StorageError(f"{nome}: tamanho do arquivo não bate com o cabeçalho")
            livres = self._percorrer_lista_livre(a, fid)
        except BaseException:
            fh.close()
            raise
        return self._registrar_aberto(nome, caminho, fh, a.hdr, livres)

    def _percorrer_lista_livre(self, a: _Aberto, fid: int) -> list[int]:
        """Reconstrói o espelho da lista livre lendo a cadeia no disco (cada passo = 1 leitura)."""
        livres: list[int] = []
        vistos: set[int] = set()
        bno = a.hdr["livre"]
        while bno:
            if bno in vistos or not (1 <= bno < a.hdr["proximo"]):
                raise StorageError(f"{a.nome}: lista livre corrompida em {bno}")
            magic, prox = LIVRE.unpack_from(self._ler_fisico(a, fid, bno), 0)
            if magic != MAGIC_LIVRE:
                raise StorageError(f"{a.nome}: bloco {bno} na lista livre sem marca LIVR")
            vistos.add(bno)
            livres.append(bno)
            bno = prox
        if len(livres) != a.hdr["num_livres"]:
            raise StorageError(f"{a.nome}: num_livres do cabeçalho não bate com a lista")
        return livres

    def exists(self, nome: str) -> bool:
        return self._caminho(nome).exists()

    def fid_de(self, nome: str) -> int | None:
        """Fid se o arquivo `nome` estiver aberto; senão None (uso do BufferManager)."""
        return self._fid_por_nome.get(nome)

    def close(self, fid: int) -> None:
        """Grava o cabeçalho (se alterado) e fecha. Fid desconhecido/fechado: nada a fazer."""
        a = self._abertos.get(fid)
        if a is None:
            return
        try:
            if a.hdr_dirty:
                self._gravar_hdr(fid)
        finally:
            a.fh.close()
            del self._abertos[fid]
            del self._fid_por_nome[a.nome]

    def close_all(self) -> None:
        for fid in list(self._abertos):
            self.close(fid)

    def delete(self, nome: str) -> None:
        caminho = self._caminho(nome)
        fid = self._fid_por_nome.get(nome)
        if fid is not None:                      # fecha sem gravar o cabeçalho
            a = self._abertos.pop(fid)
            del self._fid_por_nome[nome]
            a.fh.close()
        if not caminho.exists():
            raise StorageError(f"arquivo inexistente: {nome}")
        caminho.unlink()

    def sync(self, fid: int | None = None) -> None:
        """Grava cabeçalho(s) alterado(s) (1 escrita cada, conta I/O). `None` = todos os abertos."""
        for f in ([fid] if fid is not None else list(self._abertos)):
            if self._arq(f).hdr_dirty:
                self._gravar_hdr(f)

    # ------------------------------------------------------------------ blocos
    def read_block(self, fid: int, bno: int) -> bytearray:
        a = self._arq(fid)
        self._checar_bloco(a, bno)
        return self._ler_fisico(a, fid, bno)

    def write_block(self, fid: int, bno: int, data: bytes) -> None:
        a = self._arq(fid)
        self._checar_bloco(a, bno)
        if len(data) > self.block_size:
            raise StorageError(f"dado ({len(data)} B) maior que o bloco ({self.block_size} B)")
        self._gravar_fisico(a, fid, bno, bytes(data).ljust(self.block_size, b"\0"))

    def bloco_valido(self, fid: int, bno: int) -> bool:
        """True se `bno` é um bloco de dados em uso (alocado e fora da lista livre)."""
        a = self._arq(fid)
        return isinstance(bno, int) and 1 <= bno < a.hdr["proximo"] and bno not in a.livres_set

    def allocate_block(self, fid: int) -> int:
        a = self._arq(fid)
        h = a.hdr
        if a.livres:                              # reuso: cabeça da lista livre
            bno = a.livres[0]
            magic, prox = LIVRE.unpack_from(self._ler_fisico(a, fid, bno), 0)
            esperado = a.livres[1] if len(a.livres) > 1 else 0
            if magic != MAGIC_LIVRE or prox != esperado:
                raise StorageError(f"{a.nome}: lista livre corrompida no bloco {bno}")
            a.livres.pop(0)
            a.livres_set.discard(bno)
            h["livre"] = prox
            h["num_livres"] -= 1
        else:
            if h["proximo"] > h["num_alocados"]:  # extent atual cheio → novo extent
                h["num_alocados"] += h["extent"]
                a.fh.truncate((1 + h["num_alocados"]) * self.block_size)
            bno = h["proximo"]
            h["proximo"] += 1
        a.hdr_dirty = True
        return bno

    def free_block(self, fid: int, bno: int) -> None:
        a = self._arq(fid)
        self._checar_bloco(a, bno)
        h = a.hdr
        marca = LIVRE.pack(MAGIC_LIVRE, h["livre"]).ljust(self.block_size, b"\0")
        self._gravar_fisico(a, fid, bno, marca)
        a.livres.insert(0, bno)
        a.livres_set.add(bno)
        h["livre"] = bno
        h["num_livres"] += 1
        a.hdr_dirty = True

    def num_blocks(self, fid: int) -> int:
        h = self._arq(fid).hdr
        return h["proximo"] - 1 - h["num_livres"]

    # ------------------------------------------------------------------ cabeçalho
    def header(self, fid: int) -> dict:
        h = self._arq(fid).hdr
        return {"tipo_org": h["tipo_org"], "num_alocados": h["num_alocados"],
                "livre": h["livre"], "extent": h["extent"],
                "meta": json.loads(json.dumps(h["meta"])),
                "proximo": h["proximo"], "num_livres": h["num_livres"],
                "extents": h["num_alocados"] // h["extent"]}

    def set_header(self, fid: int, **campos: Any) -> None:
        a = self._arq(fid)
        novo = {**a.hdr["meta"], **campos}
        self._meta_json(novo)                     # valida tamanho/serialização antes de trocar
        a.hdr["meta"] = json.loads(json.dumps(novo))
        a.hdr_dirty = True

    # ------------------------------------------------------------------ estatísticas
    def io_stats(self, fid: int | None = None) -> dict[str, int]:
        return self.stats.snapshot(fid)

    def reset_io_stats(self) -> None:
        self.stats.reset()
