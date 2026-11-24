"""Modelo de custo analítico — STUB do M0; implementação: M6 (E13).

Silberschatz 15.2–15.5 (REFERENCIA_LIVRO §6–7). Cada função devolve
`{'transferencias': x, 'seeks': y}` a partir das estatísticas do catálogo (`InfoTabela`,
`InfoIndice`) e de M/bb. Fontes de divergência esperadas vs. medido (documentar no M6):
buffer quente, raiz da B+ residente, overflow de hash, blocos parcialmente cheios, cabeçalhos.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from src.executor.contracts import InfoIndice, InfoTabela


class Custo(TypedDict):
    transferencias: float
    seeks: float


def custo_selecao(caminho: str, tabela: InfoTabela, *, indice: Optional[InfoIndice] = None,
                  sc: float = 1.0) -> Custo:
    """A1_linear, A1_chave, A2..A6, HASH_PRIM, HASH_SEC (Fig. 15.3). `sc` = tuplas que satisfazem."""
    raise NotImplementedError("M6/E13")


def custo_sort(b: int, M: int, bb: int = 1) -> Custo:
    """Ordenação externa de b blocos (15.4)."""
    raise NotImplementedError("M6/E13")


def custo_bnl(r: InfoTabela, s: InfoTabela, M: int) -> Custo:
    """Block nested-loop com r externa (15.5.2)."""
    raise NotImplementedError("M6/E13")


def custo_inl(r: InfoTabela, s: InfoTabela, indice_s: InfoIndice, c: Optional[Custo] = None) -> Custo:
    """Indexed nested-loop: br + nr·c (15.5.3)."""
    raise NotImplementedError("M6/E13")


def custo_smj(r: InfoTabela, s: InfoTabela, M: int, bb: int = 1, *, ordenado_r: bool = False,
              ordenado_s: bool = False) -> Custo:
    """Sort-merge join (15.5.4)."""
    raise NotImplementedError("M6/E13")


def custo_hash_join(r: InfoTabela, s: InfoTabela, M: int, bb: int = 1,
                    nh: Optional[int] = None) -> Custo:
    """Partition-hash join com s como build (15.5.5), incluindo particionamento recursivo."""
    raise NotImplementedError("M6/E13")


def comparar(medido: dict, estimado: Custo) -> dict:
    """{'dif_abs_transf', 'dif_rel_transf', 'dif_abs_seeks', 'dif_rel_seeks'}."""
    raise NotImplementedError("M6/E13")
