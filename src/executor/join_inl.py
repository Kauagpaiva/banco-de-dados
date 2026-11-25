"""Indexed nested-loop join (Camada 2) — M5, E11.

Silberschatz 15.5.3 (REFERENCIA_LIVRO §7): para cada tupla de r (externa, lida bloco a
bloco), busca em s as tuplas com s.campo_s = r.campo_r pela estrutura de s nesse campo.
Custo br + nr·c, c = custo de uma seleção por igualdade em s.

Estrutura usada em s (`selection.caminho_igualdade`): organização primária no campo
(B+ → A2/A3, hash → HASH_PRIM) ou índice secundário (A4/HASH_SEC). Sem estrutura → ValueError.

Memória (MemoryBudget, D-M5-08): 1 página pinada para o bloco corrente de r + 1 de E/S
(frames de s/índice e de saída) → M ≥ 2. Nulos em r.campo_r não casam (nenhuma busca).
"""
from __future__ import annotations

from typing import Iterator, Optional

from src.executor.contracts import (
    AccessMethod, CondJuncao, Relacao, Resultado, StorageContext, combinar, esquema_juncao,
)
from src.executor.join_bnl import relacao, validar_cond
from src.executor.memory import MemoryBudget
from src.executor.scan import _fechar, saida_juncao
from src.executor.selection import buscar_igualdade, caminho_igualdade


def indexed_nested_loop(ctx: StorageContext, r: Relacao, s: AccessMethod, cond: CondJuncao, *,
                        M: Optional[int] = None, materializar: bool = False) -> Resultado:
    """r ⋈_{r.campo_r = s.campo_s} s por INL (15.5.3). Ver docstring do módulo."""
    if not isinstance(s, AccessMethod):
        raise TypeError(f"INL exige s como AccessMethod, veio {type(s).__name__}")
    r = relacao(r)
    cond = CondJuncao(*cond)
    validar_cond(r, s.tabela, cond)
    caminho = caminho_igualdade(s, cond.campo_s)
    mb = MemoryBudget(ctx, M)
    if mb.M < 2:
        raise ValueError(f"INL exige M ≥ 2 (1 bloco de r + 1 de E/S); M={mb.M}")
    corpo = _inl(ctx, mb, r, s, cond, caminho)
    return saida_juncao(ctx, corpo, esquema_juncao(r.esquema, s.esquema), materializar)


def _inl(ctx: StorageContext, mb: MemoryBudget, r: Relacao, s: AccessMethod, cond: CondJuncao,
         caminho: str) -> Iterator[dict]:
    nome_r, nome_s = r.esquema.nome, s.esquema.nome
    bs = ctx.bm.block_size
    with mb:
        mb.reservar_paginas(1)
        mb.reservar_paginas_io(1)
        blocos = r.scan_blocos(False)
        try:
            for bloco in blocos:
                if not bloco:
                    continue
                tam = max(1, bs // len(bloco))
                mb.reservar_tuplas(len(bloco), tam)
                for rec_r in bloco:
                    v = rec_r[cond.campo_r]
                    if v is None:
                        continue
                    achados = buscar_igualdade(s, cond.campo_s, v, caminho)
                    try:
                        for rec_s in achados:
                            yield combinar(nome_r, rec_r, nome_s, rec_s)
                    finally:
                        _fechar(achados)
                mb.liberar_tuplas(len(bloco), tam)
        finally:
            _fechar(blocos)
