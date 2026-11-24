"""Tipos simples compartilhados entre camadas (contrato M0 — E00b).

Nada aqui depende de outra camada: `storage`, `access`, `executor` e `bench` importam daqui.
"""
from __future__ import annotations

from typing import Any, NamedTuple, TypedDict


class RID(NamedTuple):
    """Identificador de registro: (bloco, slot) — ver D06."""
    bloco: int
    slot: int


class PageId(NamedTuple):
    """Identificador de página no buffer: (fid, bno)."""
    fid: int
    bno: int


# --------------------------------------------------------------------------- predicados
OPS = ("=", "<", "<=", ">", ">=")


class Predicado(NamedTuple):
    """Predicado de seleção `campo op valor` (op ∈ OPS). Silberschatz 15.2."""
    campo: str
    op: str
    valor: Any

    def validar(self) -> "Predicado":
        if self.op not in OPS:
            raise ValueError(f"operador inválido: {self.op!r} (válidos: {OPS})")
        return self

    def avaliar(self, rec: dict) -> bool:
        """Avalia o predicado sobre um registro (dict). Valor nulo nunca satisfaz."""
        v = rec.get(self.campo)
        if v is None:
            return False
        op = self.op
        if op == "=":
            return v == self.valor
        if op == "<":
            return v < self.valor
        if op == "<=":
            return v <= self.valor
        if op == ">":
            return v > self.valor
        if op == ">=":
            return v >= self.valor
        raise ValueError(f"operador inválido: {op!r}")


class CondJuncao(NamedTuple):
    """Condição de equijunção `r.campo_r = s.campo_s`. Silberschatz 15.5."""
    campo_r: str
    campo_s: str


# --------------------------------------------------------------------------- métricas
#: Contadores do BufferManager (globais e por área).
CHAVES_BUFFER = ("requests", "hits", "misses", "hit_rate", "dirty_evictions", "forced_writes")
#: Contadores de I/O do FileManager (modelo de seek D05).
CHAVES_IO = ("reads", "writes", "seq_reads", "rand_reads", "seq_writes", "rand_writes")
#: Derivadas: transferencias = reads + writes ; seeks = rand_reads + rand_writes.
CHAVES_DERIVADAS = ("transferencias", "seeks")
#: Todas as chaves globais devolvidas por `BufferManager.stats()`.
CHAVES_STATS = CHAVES_BUFFER + CHAVES_IO + CHAVES_DERIVADAS


class Metricas(TypedDict, total=False):
    """Métricas de uma operação do executor: chaves de `CHAVES_STATS` + `tuplas_saida`.

    Os operadores devolvem `(iterador, Metricas)`; o dict é preenchido/atualizado quando o
    iterador se esgota (ou é fechado). Antes disso os valores podem estar incompletos.
    """
    requests: int
    hits: int
    misses: int
    hit_rate: float
    dirty_evictions: int
    forced_writes: int
    reads: int
    writes: int
    seq_reads: int
    rand_reads: int
    seq_writes: int
    rand_writes: int
    transferencias: int
    seeks: int
    tuplas_saida: int
    escrita_saida: int     # blocos gravados do resultado materializado (0 se não materializado)


def metricas_vazias() -> Metricas:
    """Metricas com todos os contadores zerados."""
    m: Metricas = {k: 0 for k in CHAVES_STATS}  # type: ignore[assignment]
    m["hit_rate"] = 0.0
    m["tuplas_saida"] = 0
    return m


def diferenca_metricas(depois: dict, antes: dict) -> Metricas:
    """depois − antes para os contadores (hit_rate recalculado)."""
    m = metricas_vazias()
    for k in CHAVES_STATS:
        if k != "hit_rate":
            m[k] = depois.get(k, 0) - antes.get(k, 0)  # type: ignore[literal-required]
    m["hit_rate"] = m["hits"] / m["requests"] if m["requests"] else 0.0
    return m


# --------------------------------------------------------------------------- seleção
#: Caminhos de acesso da seleção, escolhidos explicitamente pelo chamador (15.2, Fig. 15.3).
CAMINHOS_SELECAO = ("A1_linear", "A1_chave", "A2", "A3", "A4", "A5", "A6", "HASH_PRIM", "HASH_SEC")

#: Tipos de organização primária de arquivo.
TIPOS_ORG = ("heap", "bplus", "hash")

#: Chaves de `FileOrganization.ocupacao()` (blocos).
CHAVES_OCUPACAO = ("dados", "overflow", "indice", "total", "registros")
