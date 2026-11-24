"""Contratos da Camada 3 (métodos de acesso) — congelados pelo M0 (E00b).

Implementações reais: M2 (record, page, catalog, heap, tempfile, context), M3 (bplus),
M4 (hashfile, hash_index), M8 (secondary_bplus, access_methods).
Fakes: `tests/fakes/access.py`. Testes de contrato: `tests/contratos/`.

Silberschatz 13.2–13.4 (registros, slotted page, catálogo), 13.3 (organizações),
14.2–14.5 (índices). Convenções:

- Registro = `dict` campo → valor Python: int · float · `datetime.date` · str (char/varchar) ·
  `list[str]` · `None` (só se `Campo.nulo`).
- Injeção de dependências: toda estrutura recebe `bm` (BufferManagerAPI) e, opcionalmente,
  `page_impl` (classe SlottedPageAPI) e `codec` (RecordCodecAPI). `None` → implementação real
  (`padroes()`); os testes passam os fakes enquanto o real não estiver em `main`.
- Construtor não toca no disco; `open()` cria o arquivo se não existir, senão abre.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional, Protocol, runtime_checkable

from src.common.tipos import RID
from src.storage.contracts import BufferManagerAPI, Frame

# =========================================================================== esquema
_RE_TIPO = re.compile(r"^(int|float|date|char\((\d+)\)|varchar\((\d+)\)|list\[varchar\((\d+)\)\])$")


@dataclass(frozen=True)
class Campo:
    """Campo de um esquema. `tipo` ∈ {'int','float','date','char(n)','varchar(n)',
    'list[varchar(n)]'}. `max_itens` só vale para listas (limite de itens)."""
    nome: str
    tipo: str
    nulo: bool = False
    max_itens: int = 4

    def __post_init__(self):
        if not _RE_TIPO.match(self.tipo):
            raise ValueError(f"tipo inválido para {self.nome}: {self.tipo!r}")

    @property
    def base(self) -> str:
        """'int' | 'float' | 'date' | 'char' | 'varchar' | 'list'."""
        return self.tipo.split("(")[0].split("[")[0]

    @property
    def n(self) -> int:
        """Tamanho máximo em bytes (UTF-8) de char/varchar ou de cada item da lista; 0 se fixo."""
        m = _RE_TIPO.match(self.tipo)
        assert m
        return int(m.group(2) or m.group(3) or m.group(4) or 0)

    @property
    def variavel(self) -> bool:
        return self.base in ("varchar", "list")


@dataclass(frozen=True)
class Esquema:
    """Esquema de relação: nome, campos (ordem física) e chave primária (lista de nomes)."""
    nome: str
    campos: tuple[Campo, ...]
    chave: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "campos", tuple(self.campos))
        object.__setattr__(self, "chave", tuple(self.chave))
        nomes = [c.nome for c in self.campos]
        if len(set(nomes)) != len(nomes):
            raise ValueError(f"{self.nome}: campos repetidos")
        for k in self.chave:
            if k not in nomes:
                raise ValueError(f"{self.nome}: chave {k!r} não é campo")

    def nomes(self) -> list[str]:
        return [c.nome for c in self.campos]

    def campo(self, nome: str) -> Campo:
        for c in self.campos:
            if c.nome == nome:
                return c
        raise KeyError(f"{self.nome}: campo inexistente {nome!r}")


def esquema_juncao(r: Esquema, s: Esquema, nome: str | None = None) -> Esquema:
    """Esquema da saída de junção: campos `"<r.nome>.<campo>"` seguidos de `"<s.nome>.<campo>"`
    (tipos e nulidade preservados). Ver `src.executor.contracts.combinar`."""
    campos = [Campo(f"{e.nome}.{c.nome}", c.tipo, c.nulo, c.max_itens)
              for e in (r, s) for c in e.campos]
    return Esquema(nome or f"{r.nome}_x_{s.nome}", tuple(campos), ())


# =========================================================================== registro
class RecordCodecAPI(ABC):
    """Codifica dict ↔ bytes segundo um Esquema (Silberschatz 13.2.2, Fig. 13.5; D08).
    Construtor real: `RecordCodec(esquema)`.

    - `encode` valida tipos, nulos e tamanhos (`RecordError`); `decode(encode(r)) == r`.
    - char(n): str com ≤ n bytes UTF-8, sem espaços/`\\0` à direita (o round-trip preserva o valor).
    - `max_size`: maior registro codificado possível para o esquema.
    """
    esquema: Esquema

    @abstractmethod
    def encode(self, rec: Mapping[str, Any]) -> bytes: ...

    @abstractmethod
    def decode(self, data: bytes) -> dict: ...

    @property
    @abstractmethod
    def max_size(self) -> int: ...


class SlottedPageAPI(ABC):
    """Página com slots sobre `frame.data` (bytearray do bloco), sem copiar o bloco
    (Silberschatz 13.2.2, Fig. 13.6; D07). **Todos os métodos são estáticos.**

    - `format(buf, reserva)`: inicializa página vazia; os últimos `reserva` bytes ficam livres
      para o chamador (ponteiro de overflow do hash, próxima folha da B+...) — ver `reserva()`.
    - Números de slot são estáveis: `delete` e `compact` nunca renumeram (RIDs estáveis).
    - Toda leitura de offset/len valida `0 <= off <= off+len <= len(buf)` → `CorruptedPageError`.
    - `insert` devolve o slot ou None se não couber; `update` devolve False se não couber.
    """

    @staticmethod
    @abstractmethod
    def format(buf: bytearray, reserva: int = 0) -> None: ...

    @staticmethod
    @abstractmethod
    def insert(buf: bytearray, rec: bytes) -> Optional[int]: ...

    @staticmethod
    @abstractmethod
    def get(buf: bytearray, slot: int) -> Optional[bytes]:
        """Bytes do registro ou None se o slot está vazio/removido/inexistente."""

    @staticmethod
    @abstractmethod
    def delete(buf: bytearray, slot: int) -> None: ...

    @staticmethod
    @abstractmethod
    def update(buf: bytearray, slot: int, rec: bytes) -> bool: ...

    @staticmethod
    @abstractmethod
    def compact(buf: bytearray) -> None: ...

    @staticmethod
    @abstractmethod
    def free_space(buf: bytearray) -> int:
        """Bytes livres contíguos para um novo registro (já descontado o slot novo)."""

    @staticmethod
    @abstractmethod
    def slots(buf: bytearray) -> Iterator[int]:
        """Slots ocupados, em ordem crescente."""

    @staticmethod
    @abstractmethod
    def count(buf: bytearray) -> int:
        """Número de registros vivos."""

    @staticmethod
    @abstractmethod
    def reserva(buf: bytearray) -> tuple[int, int]:
        """(offset, tamanho) da área reservada ao chamador no fim do bloco."""

    @staticmethod
    @abstractmethod
    def capacidade_max(block_size: int, reserva: int = 0) -> int:
        """Maior registro (bytes) que cabe numa página vazia."""


# =========================================================================== catálogo
@dataclass
class InfoIndice:
    """Metadados de um índice (consumidos pelo modelo de custo, M6)."""
    nome: str
    tabela: str
    campo: str
    tipo: str                      # 'bplus' | 'hash'
    unique: bool
    clustering: bool = False
    primario: bool = False         # True = é a própria organização (B+/Hash primário)
    altura: int = 0                # hi (B+); 1 para hash
    num_blocks: int = 0
    fanout: int = 0                # n (B+)
    params: dict = field(default_factory=dict)


@dataclass
class InfoTabela:
    """Estatísticas de catálogo de uma tabela (Silberschatz 16.3.1): o formato que o
    `cost_model` consome. nr = nº de tuplas · br = nº de blocos · fr = tuplas/bloco ·
    V[A] = nº de valores distintos de A."""
    nome: str
    esquema: Esquema
    org: str                       # 'heap' | 'bplus' | 'hash'
    campo_org: Optional[str] = None
    params: dict = field(default_factory=dict)
    nr: int = 0
    br: int = 0
    fr: float = 0.0
    tam_registro: float = 0.0      # tamanho médio codificado (bytes)
    V: dict[str, int] = field(default_factory=dict)
    indices: list[InfoIndice] = field(default_factory=list)

    def indice(self, campo: str) -> Optional[InfoIndice]:
        for i in self.indices:
            if i.campo == campo:
                return i
        return None


class CatalogAPI(ABC):
    """Catálogo do sistema (Silberschatz 13.4). Construtor real: `Catalog(bm, nome="catalogo")`;
    persistido num arquivo próprio via BufferManager (área 'catalogo')."""

    @abstractmethod
    def registrar_tabela(self, esquema: Esquema, org: str, params: Mapping | None = None,
                         campo_org: str | None = None) -> InfoTabela: ...

    @abstractmethod
    def registrar_indice(self, tabela: str, nome: str, campo: str, tipo: str, unique: bool,
                         clustering: bool = False, primario: bool = False,
                         params: Mapping | None = None) -> InfoIndice: ...

    @abstractmethod
    def tabela(self, nome: str) -> InfoTabela:
        """KeyError se não registrada."""

    @abstractmethod
    def tabelas(self) -> list[str]: ...

    @abstractmethod
    def remover_tabela(self, nome: str) -> None: ...

    @abstractmethod
    def atualizar_estatisticas(self, nome: str, nr: int, br: int, V: Mapping[str, int],
                               fr: float, tam_registro: float | None = None) -> None: ...

    @abstractmethod
    def atualizar_indice(self, tabela: str, campo: str, altura: int, num_blocks: int,
                         fanout: int = 0) -> None: ...

    @abstractmethod
    def definir(self, chave: str, valor: Any) -> None:
        """Valor livre persistido (ex.: limiares de CR do gerador, E09). JSON-serializável."""

    @abstractmethod
    def obter(self, chave: str, padrao: Any = None) -> Any: ...


# =========================================================================== relações
@runtime_checkable
class Relacao(Protocol):
    """O que os operadores de junção/ordenação consomem: FileOrganization ou TempFile."""
    esquema: Esquema

    def num_blocks(self) -> int: ...

    def num_registros(self) -> int: ...

    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        """Um item por bloco de dados (na ordem física), com os registros do bloco.
        Só 1 página pinada por vez, solta antes do `yield`."""
        ...


class FileOrganization(ABC):
    """Organização primária de arquivo (Silberschatz 13.3; enunciado §3).
    Implementações: `HeapFile` (heap.py), `BPlusTree` (bplus.py), `HashFile` (hashfile.py).

    Construtores reais (keyword-only após `esquema`):
      HeapFile(bm, nome, esquema, *, page_impl=None, codec=None, fragmentacao_max=0.25)
      BPlusTree(bm, nome, esquema, campo, *, unique=True, page_impl=None, codec=None)
      HashFile(bm, nome, esquema, campo, *, unique=True, n_buckets=None, nr_estimado=None,
               page_impl=None, codec=None)

    Iteradores (`scan`, `find_all`, `find_ordered`, `scan_blocos`) mantêm no máximo 1 página
    pinada e a soltam em `finally`. `find`/`find_next` formam um cursor (`reset()` reinicia).
    """
    nome: str
    esquema: Esquema
    tipo_org: str                       # 'heap' | 'bplus' | 'hash'
    campo: Optional[str] = None         # campo de organização (None no heap)
    unique: bool = True

    # ---- ciclo de vida
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def reset(self) -> None:
        """Reinicia o cursor de find/find_next."""

    # ---- registro a registro
    @abstractmethod
    def find(self, campo: str, valor: Any) -> Optional[RID]:
        """Primeiro registro com campo == valor (pela estrutura se `campo` for o da organização,
        senão linear); inicia o cursor."""

    @abstractmethod
    def find_next(self) -> Optional[RID]:
        """Próximo registro do cursor aberto por `find`; None ao fim."""

    @abstractmethod
    def read(self, rid: RID) -> dict: ...

    @abstractmethod
    def insert(self, rec: Mapping[str, Any]) -> RID:
        """`ChaveDuplicadaError` se UNIQUE e a chave já existir."""

    @abstractmethod
    def delete(self, rid: RID) -> None: ...

    @abstractmethod
    def update(self, rid: RID, rec: Mapping[str, Any]) -> RID:
        """Devolve o RID novo (pode mudar se o registro não couber no bloco/chave mudar)."""

    # ---- conjunto a conjunto
    @abstractmethod
    def scan(self, toss: bool = False) -> Iterator[tuple[RID, dict]]:
        """Varredura física bloco a bloco (`toss=True` → toss-immediate em cada página)."""

    @abstractmethod
    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]:
        """Ver `Relacao.scan_blocos`."""

    @abstractmethod
    def find_all(self, campo: str, op: str, valor: Any) -> Iterator[tuple[RID, dict]]: ...

    @abstractmethod
    def find_ordered(self, campo: str, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[tuple[RID, dict]]:
        """Registros com lo ≤ campo ≤ hi em ordem de `campo` (None = sem limite).
        `OperacaoNaoSuportada` se a organização não fornece ordem nesse campo."""

    # ---- manutenção / medidas
    @abstractmethod
    def reorganize(self) -> None: ...

    @abstractmethod
    def num_blocks(self) -> int:
        """Blocos em uso do arquivo (dados + overflow + nós internos)."""

    @abstractmethod
    def num_registros(self) -> int: ...

    @abstractmethod
    def ocupacao(self) -> dict[str, int]:
        """Chaves `CHAVES_OCUPACAO`: dados, overflow, indice, total (blocos), registros."""


class SecondaryIndex(ABC):
    """Índice secundário (Silberschatz 14.2, 14.3.5, 14.4.2, 14.5).
    `ref` é RID ou, se `refs_por_chave`, o valor da chave primária (organização B+, 14.4.2).

    Construtores reais:
      HashIndex(bm, nome, campo: Campo, *, nr_estimado=None, n_buckets=None, page_impl=None)  # UNIQUE
      BPlusIndex(bm, nome, campo: Campo, *, unique=False, clustering=False,
                 refs_por_chave=False, page_impl=None)
    """
    nome: str
    campo: str
    unique: bool = False
    clustering: bool = False
    refs_por_chave: bool = False

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def insert(self, chave: Any, ref: Any) -> None:
        """`ChaveDuplicadaError` se UNIQUE e a chave já existir."""

    @abstractmethod
    def delete(self, chave: Any, ref: Any) -> None:
        """Remove o par (chave, ref); KeyError se não existir."""

    @abstractmethod
    def search_eq(self, chave: Any) -> Iterator[Any]: ...

    @abstractmethod
    def search_range(self, lo: Any = None, hi: Any = None, incl_lo: bool = True,
                     incl_hi: bool = True) -> Iterator[Any]:
        """Refs com chave na faixa, em ordem de chave (`OperacaoNaoSuportada` em hash)."""

    @abstractmethod
    def altura(self) -> int: ...

    @abstractmethod
    def num_blocks(self) -> int: ...


class TempFile(ABC):
    """Arquivo temporário (runs da ordenação, partições do hash join, saída materializada).
    Páginas na área 'trabalho'. Construtor real: `ArquivoTemporario(bm, nome, esquema, *,
    page_impl=None, codec=None)`; obtido via `StorageContext.temp_file(esquema)`."""
    nome: str
    esquema: Esquema

    @abstractmethod
    def append(self, rec: Mapping[str, Any]) -> None: ...

    @abstractmethod
    def blocks(self) -> Iterator[int]:
        """Números dos blocos de dados, na ordem de escrita."""

    @abstractmethod
    def records_in_block(self, bno: int) -> list[dict]:
        """Registros de um bloco (pin + unpin internos)."""

    @abstractmethod
    def scan(self, toss: bool = False) -> Iterator[dict]: ...

    @abstractmethod
    def scan_blocos(self, toss: bool = False) -> Iterator[list[dict]]: ...

    @abstractmethod
    def num_blocks(self) -> int: ...

    @abstractmethod
    def num_registros(self) -> int: ...

    @abstractmethod
    def close(self) -> None:
        """Termina a escrita (solta página de append, se houver). Leitura continua possível."""

    @abstractmethod
    def delete(self) -> None:
        """Apaga o arquivo (descarta páginas do buffer sem gravar)."""


class StorageContext(ABC):
    """O que o executor precisa do armazenamento sem importar `storage`.
    Real: `src.access.context.criar_contexto(cfg, base_dir=None, *, bm=None, catalog=None)` (M2);
    `bm`/`catalog` injetáveis para testar o contexto real sobre fakes."""
    cfg: Any

    @property
    @abstractmethod
    def bm(self) -> BufferManagerAPI:
        """Buffer manager (para as estruturas da Camada 3; o executor não pina páginas de dados)."""

    @property
    @abstractmethod
    def catalog(self) -> CatalogAPI: ...

    @abstractmethod
    def buffer_stats(self) -> dict:
        """`bm.stats()` (chaves CHAVES_STATS + 'por_area')."""

    @abstractmethod
    def reset_stats(self) -> None: ...

    @abstractmethod
    def drop_all(self) -> None:
        """Cold start: grava dirty e esvazia o buffer."""

    @abstractmethod
    def set_policy(self, area: str, nome: str) -> None: ...

    @abstractmethod
    def work_capacity(self) -> int:
        """M = capacidade da área 'trabalho'."""

    @abstractmethod
    def pin_work_page(self) -> Frame:
        """Pina uma página de rascunho da área 'trabalho' (conta para M)."""

    @abstractmethod
    def unpin_work_page(self, frame: Frame) -> None:
        """Solta e descarta a página de rascunho."""

    @abstractmethod
    def temp_file(self, esquema: Esquema, prefixo: str = "tmp") -> TempFile:
        """Cria arquivo temporário com nome único."""

    @abstractmethod
    def close(self) -> None:
        """Fecha arquivos e apaga temporários remanescentes."""


# =========================================================================== método de acesso
@dataclass
class AccessMethod:
    """(organização primária, índices secundários) de uma tabela — combinações da tabela 4.2
    do enunciado; montado pelo registry de `access_methods.py` (M8)."""
    tabela: FileOrganization
    indices: dict[str, SecondaryIndex] = field(default_factory=dict)   # campo → índice
    descricao: str = ""

    @property
    def esquema(self) -> Esquema:
        return self.tabela.esquema

    def indice(self, campo: str) -> Optional[SecondaryIndex]:
        return self.indices.get(campo)


# =========================================================================== helpers
def padroes(esquema: Esquema | None, page_impl: type | None = None,
            codec: RecordCodecAPI | None = None) -> tuple[type, Optional[RecordCodecAPI]]:
    """Resolve dependências injetadas: None → implementação real (import tardio)."""
    if page_impl is None:
        from src.access.page import SlottedPage
        page_impl = SlottedPage
    if codec is None and esquema is not None:
        from src.access.record import RecordCodec
        codec = RecordCodec(esquema)
    return page_impl, codec


def validar_op(op: str) -> None:
    from src.common.tipos import OPS
    if op not in OPS:
        raise ValueError(f"operador inválido: {op!r}")


__all__ = [
    "Campo", "Esquema", "esquema_juncao", "RecordCodecAPI", "SlottedPageAPI", "InfoIndice",
    "InfoTabela", "CatalogAPI", "Relacao", "FileOrganization", "SecondaryIndex", "TempFile",
    "StorageContext", "AccessMethod", "padroes", "validar_op",
]
