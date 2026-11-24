"""Contratos da Camada 4 (Gerente de Arquivos + Buffer Pool) — congelados pelo M0 (E00b).

Implementação real: M1 (`file_manager.py`, `buffer_manager.py`, `replacement.py`, `stats.py`).
Fakes: `tests/fakes/storage.py`. Testes de contrato: `tests/contratos/test_contrato_buffer.py`.

Silberschatz: 12.3/13.2 (arquivos e blocos), 13.5 (buffer: pin, dirty, forced output, toss-immediate, MRU).

Regras:
- **Só o BufferManager chama `read_block`/`write_block` do FileManager.**
- Todo `pin` tem `unpin` → use `bm.page(...)`/`bm.fresh_page(...)` (context managers abaixo).
- Página alterada → `dirty=True` no `page(...)` ou `frame.mark_dirty()`.
- Blocos de dados de um arquivo começam em 1 (bloco 0 = cabeçalho, D03).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from src.common.tipos import CHAVES_BUFFER, CHAVES_DERIVADAS, CHAVES_IO, CHAVES_STATS

__all__ = ["Frame", "FileManagerAPI", "BufferManagerAPI", "PolicyAPI",
           "CHAVES_STATS", "CHAVES_BUFFER", "CHAVES_IO", "CHAVES_DERIVADAS", "AREAS"]

#: Áreas do buffer (D10). Capacidades em `cfg.buffer_areas`.
AREAS = ("catalogo", "indice", "dados", "trabalho")


@dataclass(eq=False)
class Frame:
    """Quadro do buffer pool: uma página (= 1 bloco) residente.

    `data` é o bytearray do bloco (tamanho `block_size`); quem altera deve marcar dirty.
    """
    fid: int
    bno: int
    data: bytearray
    area: str = "dados"
    pin_count: int = 0
    dirty: bool = False
    ref_bit: bool = False
    extra: dict = field(default_factory=dict, repr=False)  # uso livre da política

    def mark_dirty(self) -> None:
        self.dirty = True


class FileManagerAPI(ABC):
    """Gerente de arquivos (Camada 4a). Construtor real: `FileManager(cfg, base_dir=None)`
    (`base_dir` padrão = `cfg.perfil_dir`). Não mantém cache de blocos.

    Contagem de I/O (modelo de seek D05, braço global): acesso a (fid,b) é sequencial se o
    último acesso físico foi (fid,b-1); caso contrário é aleatório (1 seek). Leitura/escrita
    do cabeçalho também conta.
    """

    @abstractmethod
    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int:
        """Cria o arquivo `nome` (erro se existir) e devolve o fid aberto."""

    @abstractmethod
    def open(self, nome: str) -> int:
        """Abre arquivo existente e devolve o fid (o mesmo fid se já aberto)."""

    @abstractmethod
    def exists(self, nome: str) -> bool: ...

    @abstractmethod
    def close(self, fid: int) -> None: ...

    @abstractmethod
    def delete(self, nome: str) -> None:
        """Apaga o arquivo do disco (fecha antes, se aberto)."""

    @abstractmethod
    def read_block(self, fid: int, bno: int) -> bytearray:
        """Lê o bloco `bno` (≥ 1). **Só o BufferManager chama.**"""

    @abstractmethod
    def write_block(self, fid: int, bno: int, data: bytes) -> None:
        """Grava o bloco; `len(data) > block_size` → StorageError. **Só o BufferManager chama.**"""

    @abstractmethod
    def allocate_block(self, fid: int) -> int:
        """Reusa bloco da lista livre; senão o próximo (novo extent quando necessário)."""

    @abstractmethod
    def free_block(self, fid: int, bno: int) -> None: ...

    @abstractmethod
    def num_blocks(self, fid: int) -> int:
        """Blocos em uso (exclui livres e cabeçalho)."""

    @abstractmethod
    def header(self, fid: int) -> dict:
        """Cabeçalho: {'tipo_org', 'num_alocados', 'livre', 'extent', 'meta': {...}}."""

    @abstractmethod
    def set_header(self, fid: int, **campos: Any) -> None:
        """Atualiza campos de `meta` no cabeçalho (JSON curto limitado ao bloco)."""

    @abstractmethod
    def io_stats(self, fid: int | None = None) -> dict[str, int]:
        """Contadores CHAVES_IO globais (fid=None) ou do arquivo `fid`."""

    @abstractmethod
    def reset_io_stats(self) -> None: ...


class PolicyAPI(ABC):
    """Política de substituição (`replacement.py`): LRU, MRU, FIFO, CLOCK. Silberschatz 13.5.2."""

    nome: str = ""

    @abstractmethod
    def on_load(self, frame: Frame) -> None: ...

    @abstractmethod
    def on_access(self, frame: Frame) -> None: ...

    @abstractmethod
    def on_unpin(self, frame: Frame, toss: bool = False) -> None:
        """`toss=True` → a página passa a ser a próxima vítima (toss-immediate)."""

    @abstractmethod
    def on_evict(self, frame: Frame) -> None: ...

    @abstractmethod
    def victim(self, frames: list[Frame]) -> Frame | None:
        """Escolhe vítima só entre frames com `pin_count == 0`; None se não houver."""


class BufferManagerAPI(ABC):
    """Gerente de buffer (Camada 4b). Construtor real: `BufferManager(cfg, fm)`.

    Áreas fixas (`cfg.buffer_areas`), política por área (`cfg.policy_for(area)`).
    Uma página pertence à área em que foi carregada; pedir a mesma página com outra área
    devolve o frame residente (hit) sem mudar de área.

    `stats()` devolve dict com todas as chaves de `CHAVES_STATS` (globais) e
    `'por_area': {area: {chaves de CHAVES_BUFFER}}`. Invariante: hits + misses == requests.
    `new_page` não conta request (não há leitura de disco).
    """

    cfg: Any
    block_size: int

    # ---- pin/unpin -----------------------------------------------------------------
    @abstractmethod
    def pin(self, fid: int, bno: int, area: str = "dados") -> Frame: ...

    @abstractmethod
    def unpin(self, frame: Frame, dirty: bool = False, toss: bool = False) -> None: ...

    @abstractmethod
    def new_page(self, fid: int, area: str = "dados") -> Frame:
        """allocate_block + pin de página zerada (dirty), sem ler do disco."""

    @abstractmethod
    def free_page(self, fid: int, bno: int) -> None:
        """Descarta a página do buffer (sem gravar) e libera o bloco. Erro se pinada."""

    @contextmanager
    def page(self, fid: int, bno: int, area: str = "dados", dirty: bool = False,
             toss: bool = False) -> Iterator[Frame]:
        """`with bm.page(fid, bno) as fr:` — pin + unpin garantido (mesmo com exceção).
        Alterações feitas via `fr.mark_dirty()` também valem."""
        fr = self.pin(fid, bno, area)
        try:
            yield fr
        finally:
            self.unpin(fr, dirty=dirty, toss=toss)

    @contextmanager
    def fresh_page(self, fid: int, area: str = "dados") -> Iterator[Frame]:
        """`with bm.fresh_page(fid) as fr:` — new_page + unpin(dirty=True) garantido.
        O número do bloco novo é `fr.bno`."""
        fr = self.new_page(fid, area)
        try:
            yield fr
        finally:
            self.unpin(fr, dirty=True)

    # ---- persistência ---------------------------------------------------------------
    @abstractmethod
    def flush(self, fid: int, bno: int) -> None:
        """Forced output: grava a página se dirty (conta `forced_writes`)."""

    @abstractmethod
    def flush_all(self) -> None:
        """Grava todas as páginas dirty (conta `writes`, não `forced_writes`)."""

    @abstractmethod
    def drop_all(self) -> None:
        """flush_all + esvazia o pool (cold start). Erro se houver página pinada."""

    # ---- políticas/áreas ------------------------------------------------------------
    @abstractmethod
    def set_policy(self, area: str, nome: str) -> None: ...

    @abstractmethod
    def area_capacity(self, area: str) -> int: ...

    # ---- estatísticas ---------------------------------------------------------------
    @abstractmethod
    def stats(self) -> dict: ...

    @abstractmethod
    def reset_stats(self) -> None:
        """Zera contadores do buffer **e** do FileManager."""

    @abstractmethod
    def assert_no_pins(self) -> None:
        """AssertionError listando (fid, bno, pin_count) se houver página pinada."""

    # ---- repasse ao FileManager (camadas acima não importam o FileManager) -----------
    @abstractmethod
    def create(self, nome: str, tipo_org: str, meta: dict | None = None) -> int: ...

    @abstractmethod
    def open(self, nome: str) -> int: ...

    @abstractmethod
    def exists(self, nome: str) -> bool: ...

    @abstractmethod
    def close(self, fid: int) -> None:
        """Grava as páginas dirty do arquivo, tira-as do pool e fecha."""

    @abstractmethod
    def delete(self, nome: str) -> None:
        """Descarta (sem gravar) as páginas do arquivo e o apaga."""

    @abstractmethod
    def num_blocks(self, fid: int) -> int: ...

    @abstractmethod
    def header(self, fid: int) -> dict: ...

    @abstractmethod
    def set_header(self, fid: int, **campos: Any) -> None: ...
