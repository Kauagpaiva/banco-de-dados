"""Ordenação externa sort-merge (Camada 2) — M5, E11.

Silberschatz 15.4 (REFERENCIA_LIVRO §7):
1. **Geração de runs:** lê M blocos da entrada, ordena em memória, grava um run (TempFile na
   área 'trabalho'); repete até o fim → ⌈b/M⌉ runs.
2. **Merge:** junta grupos de N = ⌊M/bb⌋ − 1 runs (1 buffer de bb blocos por run + bb de
   saída) em runs maiores, passo a passo, até restar 1. Runs intermediários são apagados.

Memória (MemoryBudget, D-M5-08): na geração, M−1 páginas de rascunho pinadas + 1 página de
E/S (o frame do append do run); cada bloco lido conta como 1 página de tuplas. No merge,
N·bb páginas pinadas para os buffers de entrada + bb de E/S para a saída. Nenhuma lista
Python guarda mais tuplas do que as páginas reservadas comportam.

Ordem: crescente pela tupla de campos de `chave`; nulos primeiro (como o SQLite). Estável.
Métricas: diferença de stats da chamada inteira; `tuplas_saida` = registros do resultado;
`escrita_saida` = blocos do arquivo final (forçados a disco ao fim, também em `writes`).
"""
from __future__ import annotations

import heapq
from typing import Any, Callable, Iterator, Optional, Sequence, Union

from src.executor.contracts import Entrada, Esquema, Metricas, StorageContext, TempFile
from src.executor.memory import MemoryBudget
from src.executor.scan import Medidor, _fechar, forcar_gravacao

#: Tamanho (bytes) assumido por tipo base, para entradas sem blocos (iteráveis de dicts).
_TAM_BASE = {"int": 8, "float": 8, "date": 4}
_SOBRECARGA_CAMPO = 2          # offset/tamanho por campo variável (estimativa conservadora)


def external_sort(ctx: StorageContext, entrada: Entrada, esquema: Esquema,
                  chave: Union[str, Sequence[str]], *, M: Optional[int] = None,
                  bb: int = 1) -> tuple[TempFile, Metricas]:
    """Ordena `entrada` por `chave` com M páginas de trabalho (15.4). O chamador apaga o
    TempFile devolvido. M/bb inválidos ou campo inexistente → ValueError (sem I/O)."""
    ordem = chave_ordenacao(esquema, chave)
    if not isinstance(bb, int) or bb < 1:
        raise ValueError(f"bb inválido: {bb!r}")
    mb = MemoryBudget(ctx, M)
    if mb.M // bb - 1 < 2:
        raise ValueError(f"M={mb.M}, bb={bb}: o merge precisa de ⌊M/bb⌋−1 ≥ 2 (M ≥ 3·bb)")

    criados: list[TempFile] = []
    with Medidor(ctx) as med:
        try:
            with mb:
                runs = _gerar_runs(ctx, mb, entrada, esquema, ordem, criados)
                while len(runs) > 1:
                    runs = _passo_merge(ctx, mb, runs, esquema, ordem, bb, criados)
            if runs:
                final = runs[0]
            else:                                   # entrada vazia → arquivo vazio
                final = ctx.temp_file(esquema, "sort")
                criados.append(final)
                final.close()
            escrita = forcar_gravacao(ctx, final)
        except BaseException:
            for t in criados:
                t.delete()
            raise
    metricas = med.metricas
    metricas["tuplas_saida"] = final.num_registros()
    metricas["escrita_saida"] = escrita
    return final, metricas


# =========================================================================== chave
def chave_ordenacao(esquema: Esquema, chave: Union[str, Sequence[str]]) -> Callable[[dict], tuple]:
    """Função-chave de ordenação: tupla de (não-nulo, valor) por campo — nulos primeiro."""
    campos = (chave,) if isinstance(chave, str) else tuple(chave)
    if not campos:
        raise ValueError("chave de ordenação vazia")
    nomes = set(esquema.nomes())
    faltando = [c for c in campos if c not in nomes]
    if faltando:
        raise ValueError(f"{esquema.nome}: campos de ordenação inexistentes {faltando}")

    def k(rec: dict) -> tuple:
        return tuple((rec[c] is not None, rec[c]) for c in campos)
    return k


# =========================================================================== entrada em blocos
def blocos_entrada(entrada: Entrada, esquema: Esquema, block_size: int) -> Iterator[list[dict]]:
    """Blocos (listas de registros) da entrada. Organizações/TempFiles: `scan_blocos`;
    iteráveis: pseudo-blocos de ⌊block_size / tamanho estimado⌋ registros."""
    if hasattr(entrada, "scan_blocos") and not isinstance(entrada, (list, tuple)):
        interno: Iterator = entrada.scan_blocos(False)
    else:
        por_bloco = max(1, block_size // tamanho_estimado(esquema))
        interno = _agrupar(iter(entrada), por_bloco)
    try:
        for bloco in interno:
            yield bloco
    finally:
        _fechar(interno)


def _agrupar(it: Iterator[dict], n: int) -> Iterator[list[dict]]:
    bloco: list[dict] = []
    for rec in it:
        if not isinstance(rec, dict):
            raise TypeError(f"registro deve ser dict, veio {type(rec).__name__}")
        bloco.append(rec)
        if len(bloco) == n:
            yield bloco
            bloco = []
    if bloco:
        yield bloco


def tamanho_estimado(esquema: Esquema) -> int:
    """Limite superior simples do registro codificado (só para entradas sem blocos)."""
    total = 0
    for c in esquema.campos:
        if c.base in _TAM_BASE:
            total += _TAM_BASE[c.base]
        elif c.base == "list":
            total += c.max_itens * (c.n + _SOBRECARGA_CAMPO) + _SOBRECARGA_CAMPO
        else:                                         # char(n) / varchar(n)
            total += c.n + _SOBRECARGA_CAMPO
    return max(1, total + _SOBRECARGA_CAMPO * len(esquema.campos))


def _tam_por_tupla(block_size: int, n: int) -> int:
    """Um bloco de n tuplas ocupa exatamente 1 página do orçamento."""
    return max(1, block_size // n)


# =========================================================================== fase 1: runs
def _gerar_runs(ctx: StorageContext, mb: MemoryBudget, entrada: Entrada, esquema: Esquema,
                ordem, criados: list) -> list[TempFile]:
    """15.4.1: runs de M blocos ordenados em memória."""
    M, bs = mb.M, ctx.bm.block_size
    mb.reservar_paginas(M - 1)
    mb.reservar_paginas_io(1)
    runs: list[TempFile] = []
    buf: list[dict] = []
    reservas: list[tuple[int, int]] = []

    def descarregar() -> None:
        buf.sort(key=ordem)
        run = ctx.temp_file(esquema, "run")
        criados.append(run)
        for rec in buf:
            run.append(rec)
        run.close()
        runs.append(run)
        buf.clear()
        for n, tam in reservas:
            mb.liberar_tuplas(n, tam)
        reservas.clear()

    it = blocos_entrada(entrada, esquema, bs)
    try:
        for bloco in it:
            if not bloco:
                continue
            tam = _tam_por_tupla(bs, len(bloco))
            mb.reservar_tuplas(len(bloco), tam)
            reservas.append((len(bloco), tam))
            buf.extend(bloco)
            if len(reservas) == M:
                descarregar()
    finally:
        _fechar(it)
    if buf:
        descarregar()
    mb.liberar_paginas_io(1)
    mb.liberar_paginas(M - 1)
    return runs


# =========================================================================== fase 2: merge
class _Cursor:
    """Buffer de entrada de um run no merge: bb blocos por vez (15.4.1)."""

    def __init__(self, run: TempFile, mb: MemoryBudget, bb: int, block_size: int):
        self._blocos = iter(list(run.blocks()))
        self._run = run
        self._mb = mb
        self._bb = bb
        self._bs = block_size
        self._buf: list[dict] = []
        self._i = 0
        self._reservas: list[tuple[int, int]] = []

    def proximo(self) -> Optional[dict]:
        while self._i >= len(self._buf):
            self.liberar()
            if not self._carregar():
                return None
        rec = self._buf[self._i]
        self._i += 1
        return rec

    def _carregar(self) -> bool:
        lidos = 0
        for bno in self._blocos:
            regs = self._run.records_in_block(bno)
            lidos += 1
            if regs:
                tam = _tam_por_tupla(self._bs, len(regs))
                self._mb.reservar_tuplas(len(regs), tam)
                self._reservas.append((len(regs), tam))
                self._buf.extend(regs)
            if lidos == self._bb:
                break
        return lidos > 0

    def liberar(self) -> None:
        for n, tam in self._reservas:
            self._mb.liberar_tuplas(n, tam)
        self._reservas.clear()
        self._buf = []
        self._i = 0


def _passo_merge(ctx: StorageContext, mb: MemoryBudget, runs: list[TempFile], esquema: Esquema,
                 ordem, bb: int, criados: list) -> list[TempFile]:
    """Um passo: grupos de ⌊M/bb⌋−1 runs viram 1 run cada; o grupo de 1 run passa intacto."""
    n = mb.M // bb - 1
    novos: list[TempFile] = []
    for i in range(0, len(runs), n):
        grupo = runs[i:i + n]
        if len(grupo) == 1:
            novos.append(grupo[0])
            continue
        novos.append(_merge(ctx, mb, grupo, esquema, ordem, bb, criados))
        for run in grupo:
            run.delete()
            criados.remove(run)
    return novos


def _merge(ctx: StorageContext, mb: MemoryBudget, grupo: list[TempFile], esquema: Esquema,
           ordem, bb: int, criados: list) -> TempFile:
    """Merge (N)-way com heap de prioridade: (chave, índice do run) — estável e sem comparar dicts."""
    paginas = len(grupo) * bb
    mb.reservar_paginas(paginas)
    mb.reservar_paginas_io(bb)
    cursores = [_Cursor(run, mb, bb, ctx.bm.block_size) for run in grupo]
    try:
        heap: list[tuple[Any, int, dict]] = []
        for i, c in enumerate(cursores):
            rec = c.proximo()
            if rec is not None:
                heap.append((ordem(rec), i, rec))
        heapq.heapify(heap)
        saida = ctx.temp_file(esquema, "run")
        criados.append(saida)
        while heap:
            _, i, rec = heapq.heappop(heap)
            saida.append(rec)
            nxt = cursores[i].proximo()
            if nxt is not None:
                heapq.heappush(heap, (ordem(nxt), i, nxt))
        saida.close()
    finally:
        for c in cursores:
            c.liberar()
        mb.liberar_paginas_io(bb)
        mb.liberar_paginas(paginas)
    return saida
