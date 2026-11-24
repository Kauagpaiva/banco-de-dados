"""Contratos da Camada 2 (executor) — congelados pelo M0 (E00b).

Implementações: M5 (memory, scan, selection, sort, join_bnl, join_inl), M5J (join_smj, join_hash).
Silberschatz cap. 15 (REFERENCIA_LIVRO §6–7).

Convenções comuns a todos os operadores:
- O 1º argumento é sempre `ctx: StorageContext`; `M=None` → `ctx.work_capacity()`.
- Devolvem `(iterador, Metricas)`. O iterador é preguiçoso; o dict `Metricas` é atualizado
  quando ele se esgota (ou é fechado) com a diferença de `ctx.buffer_stats()` desde o início
  da operação + `tuplas_saida`.
- Tupla de saída de junção = `combinar(r.esquema.nome, rec_r, s.esquema.nome, rec_s)`
  (chaves "<tabela>.<campo>"); esquema correspondente: `esquema_juncao(r.esquema, s.esquema)`.
- Memória de trabalho: no máximo M páginas da área 'trabalho', contabilizadas por `MemoryBudget`;
  proibido acumular em list/dict/set mais tuplas do que cabem nas páginas reservadas.
- `materializar=True` → a saída vai para um TempFile; o iterador lê dele e os blocos gravados
  do resultado são informados à parte em `Metricas['escrita_saida']` (também somados em `writes`).

Este módulo também re-exporta os tipos da Camada 3 de que `src/bench` precisa (o bench só
pode importar o executor).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Iterator, Optional, Protocol, Sequence, Union

from src.access.contracts import (  # noqa: F401  (re-export para src/bench)
    AccessMethod, Campo, CatalogAPI, Esquema, FileOrganization, InfoIndice, InfoTabela, Relacao,
    SecondaryIndex, StorageContext, TempFile, esquema_juncao,
)
from src.common.tipos import (  # noqa: F401
    CAMINHOS_SELECAO, CondJuncao, Metricas, Predicado, metricas_vazias,
)

Entrada = Union[FileOrganization, TempFile, Iterable[dict]]
Resultado = tuple[Iterator[dict], Metricas]


def combinar(nome_r: str, rec_r: dict, nome_s: str, rec_s: dict) -> dict:
    """Tupla de saída de junção: {"<nome_r>.<campo>": v, ..., "<nome_s>.<campo>": v}."""
    saida = {f"{nome_r}.{k}": v for k, v in rec_r.items()}
    saida.update({f"{nome_s}.{k}": v for k, v in rec_s.items()})
    return saida


class MemoryBudgetAPI(ABC):
    """Orçamento de memória de trabalho (M páginas da área 'trabalho').
    Real: `src.executor.memory.MemoryBudget(ctx, M=None)`.

    - `reservar_paginas(n)` pina n páginas de rascunho (`ctx.pin_work_page`); passar de M → MemoryBudgetError.
    - `reservar_tuplas(n, tam)` contabiliza n tuplas de `tam` bytes mantidas em estruturas Python;
      exceder a capacidade das páginas reservadas → MemoryBudgetError.
    - Usar como context manager: `with MemoryBudget(ctx, M) as mb:` libera tudo ao sair.
    """

    @property
    @abstractmethod
    def M(self) -> int: ...

    @property
    @abstractmethod
    def paginas_em_uso(self) -> int: ...

    @abstractmethod
    def reservar_paginas(self, n: int) -> None: ...

    @abstractmethod
    def liberar_paginas(self, n: int) -> None: ...

    @abstractmethod
    def reservar_tuplas(self, n: int, tam: int) -> None: ...

    @abstractmethod
    def liberar_tuplas(self, n: int, tam: int) -> None: ...

    @abstractmethod
    def tuplas_por_pagina(self, tam: int) -> int: ...

    @abstractmethod
    def liberar_tudo(self) -> None: ...

    def __enter__(self) -> "MemoryBudgetAPI":
        return self

    def __exit__(self, *exc) -> None:
        self.liberar_tudo()


# --------------------------------------------------------------------------- assinaturas
class SelectFn(Protocol):
    def __call__(self, ctx: StorageContext, am: AccessMethod, predicado: Predicado,
                 caminho: str) -> Resultado:
        """`selection.select`: caminho ∈ CAMINHOS_SELECAO, escolhido pelo chamador (15.2)."""
        ...


class ExternalSortFn(Protocol):
    def __call__(self, ctx: StorageContext, entrada: Entrada, esquema: Esquema,
                 chave: Union[str, Sequence[str]], *, M: Optional[int] = None,
                 bb: int = 1) -> tuple[TempFile, Metricas]:
        """`sort.external_sort`: runs de M páginas + merge (M−1)-way (15.4). O chamador
        apaga o TempFile devolvido; os runs intermediários são apagados pela função."""
        ...


class JoinFn(Protocol):
    def __call__(self, ctx: StorageContext, r: Relacao, s: Any, cond: CondJuncao, *,
                 M: Optional[int] = None, materializar: bool = False,
                 **opcoes: Any) -> Resultado:
        """Opções específicas:
        block_nested_loop: externa='r'|'s'|'auto', toss=False (15.5.2)
        indexed_nested_loop: s é AccessMethod com índice em cond.campo_s (15.5.3)
        sort_merge_join: usa find_ordered se a organização já fornece ordem (15.5.4)
        hash_join: fudge=1.2, nh=None (15.5.5)"""
        ...


#: Onde cada operador é implementado (módulo, função) — usado pelo teste de stubs.
OPERADORES = {
    "select": ("src.executor.selection", "select"),
    "external_sort": ("src.executor.sort", "external_sort"),
    "block_nested_loop": ("src.executor.join_bnl", "block_nested_loop"),
    "indexed_nested_loop": ("src.executor.join_inl", "indexed_nested_loop"),
    "sort_merge_join": ("src.executor.join_smj", "sort_merge_join"),
    "hash_join": ("src.executor.join_hash", "hash_join"),
}
