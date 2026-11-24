"""Catálogo do sistema (Camada 3) — STUB do M0; implementação: M2 (E03).

Silberschatz 13.4 (dicionário de dados) e 16.3.1 (estatísticas nr, br, fr, V(A)).
Persistido via BufferManager na área 'catalogo'. Contrato: `CatalogAPI`.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.access.contracts import CatalogAPI, Esquema, InfoIndice, InfoTabela
from src.storage.contracts import BufferManagerAPI


class Catalog(CatalogAPI):
    def __init__(self, bm: BufferManagerAPI, nome: str = "catalogo"):
        raise NotImplementedError("M2/E03")

    def registrar_tabela(self, esquema: Esquema, org: str, params: Mapping | None = None,
                         campo_org: str | None = None) -> InfoTabela:
        raise NotImplementedError

    def registrar_indice(self, tabela: str, nome: str, campo: str, tipo: str, unique: bool,
                         clustering: bool = False, primario: bool = False,
                         params: Mapping | None = None) -> InfoIndice:
        raise NotImplementedError

    def tabela(self, nome: str) -> InfoTabela:
        raise NotImplementedError

    def tabelas(self) -> list[str]:
        raise NotImplementedError

    def remover_tabela(self, nome: str) -> None:
        raise NotImplementedError

    def atualizar_estatisticas(self, nome: str, nr: int, br: int, V: Mapping[str, int],
                               fr: float, tam_registro: float | None = None) -> None:
        raise NotImplementedError

    def atualizar_indice(self, tabela: str, campo: str, altura: int, num_blocks: int,
                         fanout: int = 0) -> None:
        raise NotImplementedError

    def definir(self, chave: str, valor: Any) -> None:
        raise NotImplementedError

    def obter(self, chave: str, padrao: Any = None) -> Any:
        raise NotImplementedError
